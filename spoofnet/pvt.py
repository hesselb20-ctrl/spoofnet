"""Weighted least-squares position, velocity and clock, batched over epochs.

Model (shared by the simulator and the detectors, see DESIGN.md section 7):
    pr_i  = |sat_i - x| + b
    prr_i = (v_sat_i - v) . u_i + d,   u_i = (sat_i - x) / |sat_i - x|
Light-time, Sagnac, satellite clock and atmosphere corrections are needed for
real ephemeris and are part of the milestone 6 work.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np


@dataclass
class Solution:
    x: np.ndarray        # (T, 3) ECEF position
    b: np.ndarray        # (T,) clock bias, m
    v: np.ndarray        # (T, 3) ECEF velocity
    d: np.ndarray        # (T,) clock drift, m/s
    sig_pos: np.ndarray  # (T,) formal position sigma, m
    sig_b: np.ndarray    # (T,) formal clock sigma, m
    rms: np.ndarray      # (T,) weighted residual RMS in sigmas
    n: np.ndarray        # (T,) measurements with non-negligible weight
    ok: np.ndarray       # (T,) bool
    sig_v: np.ndarray = None   # (T,) velocity sigma, m/s, scaled by the Doppler residuals
    sig_d: np.ndarray = None   # (T,) clock drift sigma, m/s, scaled by the Doppler residuals


def _normal_solve(h, w, y):
    """Solve batched weighted normal equations. h (T,n,4), w (T,n), y (T,n)."""
    hw = h * w[..., None]
    nmat = np.einsum("tni,tnj->tij", hw, h)
    g = np.einsum("tni,tn->ti", hw, y)
    nmat = nmat + 1e-9 * np.eye(4)[None]
    dx = np.linalg.solve(nmat, g[..., None])[..., 0]
    return dx, nmat


def solve(pr, prr, w, sat_pos, sat_vel, x0, iters: int = 5, robust: str | None = "huber") -> Solution:
    """pr, prr, w: (T, n) with NaN allowed in pr/prr and w = 0 for unusable signals.
    sat_pos, sat_vel: (T, n, 3). x0: (T, 3) linearisation point, NaN rows give ok = False."""
    t_n = pr.shape[0]
    have_sat = np.all(np.isfinite(sat_pos), axis=-1)       # recorded logs: not every satellite has ephemeris
    good = np.isfinite(pr) & (w > 0) & have_sat
    if not have_sat.all():
        sat_pos = np.where(have_sat[..., None], sat_pos, 2.0e7)
        sat_vel = np.where(have_sat[..., None] & np.isfinite(sat_vel), sat_vel, 0.0)
    w0 = np.where(good, w, 0.0)
    pr0 = np.where(good, pr, 0.0)
    x = np.where(np.isfinite(x0), x0, 0.0).copy()
    have_x0 = np.all(np.isfinite(x0), axis=1)

    def geom(xc):
        dvec = sat_pos - xc[:, None, :]
        r = np.linalg.norm(dvec, axis=-1)
        return r, dvec / np.maximum(r, 1.0)[..., None]

    r, u = geom(x)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        b = np.nanmedian(np.where(good, pr0 - r, np.nan), axis=1)
    b = np.where(np.isfinite(b), b, 0.0)
    wr = w0
    nmat = None
    for it in range(iters):
        r, u = geom(x)
        res = np.where(good, pr0 - r - b[:, None], 0.0)
        if robust and it >= 2:
            z = np.abs(res) * np.sqrt(w0)
            if robust == "tukey":
                # Scale from the residual spread itself so the majority-consistent set wins.
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    med = np.nanmedian(np.where(good, z, np.nan), axis=1)
                c = 4.685 * np.maximum(np.where(np.isfinite(med), med, 1.0) / 0.6745, 1.0)[:, None]
                wr = w0 * np.where(z < c, (1 - (z / c) ** 2) ** 2, 0.0)
            else:
                wr = w0 * np.minimum(1.0, 2.5 / np.maximum(z, 1e-9))
        h = np.concatenate([-u, np.ones_like(r)[..., None]], axis=-1)
        dx, nmat = _normal_solve(h, wr, res)
        dx = np.clip(dx, -5e6, 5e6)
        x = x + dx[:, :3]
        b = b + dx[:, 3]

    r, u = geom(x)
    res = np.where(good, pr0 - r - b[:, None], 0.0)
    n_eff = np.sum(wr > 0.05 * np.maximum(w0, 1e-12), axis=1)
    dof = np.maximum(n_eff - 4, 1)
    rms = np.sqrt(np.sum(wr * res**2, axis=1) / dof)
    cov = np.linalg.inv(nmat)
    sig_pos = np.sqrt(np.clip(np.trace(cov[:, :3, :3], axis1=1, axis2=2), 0, None))
    sig_b = np.sqrt(np.clip(cov[:, 3, 3], 0, None))

    goodv = good & np.isfinite(prr)
    wv = np.where(goodv, wr, 0.0) * 400.0            # Doppler is about 20x tighter than code in m vs m/s
    y = np.where(goodv, prr - np.einsum("tni,tni->tn", sat_vel, u), 0.0)
    h = np.concatenate([-u, np.ones_like(r)[..., None]], axis=-1)
    vd, nv = _normal_solve(h, wv, y)
    res_v = np.where(goodv, y - np.einsum("tni,ti->tn", h, vd), 0.0)
    rms_v = np.maximum(np.sqrt(np.sum(wv * res_v**2, axis=1) / dof), 1.0)
    cov_v = np.linalg.inv(nv)
    sig_v = np.sqrt(np.clip(np.trace(cov_v[:, :3, :3], axis1=1, axis2=2), 0, None)) * rms_v
    sig_d = np.sqrt(np.clip(cov_v[:, 3, 3], 0, None)) * rms_v

    ok = have_x0 & (n_eff >= 4) & (sig_pos < 500.0) & np.all(np.isfinite(x), axis=1)
    return Solution(x, b, vd[:, :3], vd[:, 3], sig_pos, sig_b, rms, n_eff, ok, sig_v, sig_d)


def signal_weights(ms) -> np.ndarray:
    from .data import code_sigma_m
    return np.where(np.isfinite(ms.cn0) & np.isfinite(ms.pr),
                    1.0 / code_sigma_m(ms.cn0, ms.sig_band[None, :]) ** 2, 0.0)


def group_masks(ms) -> dict:
    """Signals grouped by constellation and band: 'G1', 'E1', 'R1', 'C1', 'G5', 'E5', 'C5'."""
    out = {}
    for ci, cname in enumerate("GERC"):
        for bi, bname in ((0, "1"), (1, "5")):
            m = (ms.sig_const == ci) & (ms.sig_band == bi)
            if m.sum() >= 4:
                out[cname + bname] = m
    return out


def solve_groups(ms, x0, isb=None, sat_pos=None, sat_vel=None, iters: int = 5) -> dict:
    """One independent solution per constellation and band."""
    w = signal_weights(ms)
    sp = ms.sat_pos[:, ms.sig_sat] if sat_pos is None else sat_pos
    sv = ms.sat_vel[:, ms.sig_sat] if sat_vel is None else sat_vel
    pr = ms.pr if isb is None else ms.pr - isb
    out = {}
    for name, m in group_masks(ms).items():
        out[name] = solve(pr[:, m], ms.prr[:, m], w[:, m], sp[:, m], sv[:, m], x0, iters=iters, robust="huber")
    return out


def consensus_solve(ms, x0, isb=None, sat_pos=None, sat_vel=None) -> Solution:
    """All-signal solution that follows the largest self-consistent set of signals.

    Each constellation/band group proposes a solution; the proposal that the most
    signals agree with wins, and the final fix uses only the agreeing signals.
    """
    from .data import code_sigma_m
    w = signal_weights(ms)
    sp = ms.sat_pos[:, ms.sig_sat] if sat_pos is None else sat_pos
    sv = ms.sat_vel[:, ms.sig_sat] if sat_vel is None else sat_vel
    pr = ms.pr if isb is None else ms.pr - isb
    good = w > 0
    tol = np.maximum(4.0 * code_sigma_m(np.where(good, ms.cn0, 40.0), ms.sig_band[None, :]), 15.0)
    base = solve(pr, ms.prr, w, sp, sv, x0, iters=6, robust="huber")
    cands = [base] + [s for s in solve_groups(ms, x0, isb, sp, sv, iters=6).values()]
    best_score = np.full(pr.shape[0], -1.0)
    best_inl = good.copy()
    best_x = base.x.copy()
    for s in cands:
        res = np.where(good, pr - np.linalg.norm(sp - s.x[:, None, :], axis=-1) - s.b[:, None], np.inf)
        inl = good & (np.abs(res) < tol) & s.ok[:, None] & (s.n >= 5)[:, None]
        score = inl.sum(axis=1).astype(float)
        upd = score > best_score
        best_score = np.where(upd, score, best_score)
        best_inl = np.where(upd[:, None], inl, best_inl)
        best_x = np.where(upd[:, None], s.x, best_x)
    use = best_score >= 5
    w_fin = np.where(use[:, None], w * best_inl, w)
    x_init = np.where(use[:, None], best_x, base.x)
    x_init = np.where(np.isfinite(x0), x_init, np.nan)
    return solve(pr, ms.prr, w_fin, sp, sv, x_init, iters=3, robust="huber")
