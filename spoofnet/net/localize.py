"""Interference source localisation from C/N0 loss across devices (DESIGN.md section 8).

For device i with C/N0 loss d_i (dB), the interference-to-noise ratio in dB is
    x_i = 10 log10(10^(d_i/10) - 1)
and the model is
    x_i = P - 10 n log10(r_i) + e_i
with r_i the distance to the source at (x, y). Three kinds of observation:
    meas   two-sided residual
    sat    all signals lost: "at least this strong"  (one-sided)
    clean  logging and unaffected: "at most this strong" (one-sided)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

X_CLEAN_DB = -2.3        # J/N of a 2 dB loss, the smallest a device reliably reports
CHI2_95_2DOF = 5.991


@dataclass
class Obs:
    e: float                 # east, m (local frame)
    n: float                 # north, m
    kind: str                # meas | sat | clean
    drop_db: float = np.nan  # measured loss (meas) or lower bound on the loss (sat)
    weight: float = 1.0      # device tier weight
    pos_sigma_m: float = 0.0 # position uncertainty of the report (cell size)


def jn_db(drop_db):
    d = np.clip(np.asarray(drop_db, dtype=float), 0.3, 60.0)
    return 10.0 * np.log10(10.0 ** (d / 10.0) - 1.0)


def _sigma_x(drop_db, sigma_drop=1.5):
    """Error of x from an error in the measured loss: small losses carry little information."""
    d = np.clip(np.asarray(drop_db, dtype=float), 0.3, 60.0)
    g = 10.0 ** (d / 10.0)
    return sigma_drop * g / (g - 1.0)


def locate(obs: list, n_exp: float = 2.0, fit_n: bool = False, shadow_db: float = 4.0) -> dict | None:
    """Estimate the source position. Returns None when there is too little to work with."""
    meas = [o for o in obs if o.kind == "meas"]
    sat = [o for o in obs if o.kind == "sat"]
    clean = [o for o in obs if o.kind == "clean"]
    if len(meas) + len(sat) < 3 or len(meas) < 2:
        return None
    pos = np.array([[o.e, o.n] for o in obs])
    kind = np.array([{"meas": 0, "sat": 1, "clean": 2}[o.kind] for o in obs])
    drop = np.array([o.drop_db for o in obs], dtype=float)
    x_obs = np.where(kind == 0, jn_db(np.nan_to_num(drop, nan=3.0)),
                     np.where(kind == 1, jn_db(np.nan_to_num(drop, nan=20.0)), X_CLEAN_DB))
    w = np.sqrt(np.array([o.weight for o in obs]))
    psig = np.array([o.pos_sigma_m for o in obs])
    fit_n = fit_n and len(meas) >= 8

    def unpack(p):
        return p[0], p[1], p[2], (p[3] if fit_n else n_exp)

    def resid(p):
        sx, sy, pw, n = unpack(p)
        r = np.maximum(np.hypot(pos[:, 0] - sx, pos[:, 1] - sy), 10.0)
        model = pw - 10.0 * n * np.log10(r)
        # Position error of the report maps into dB through the slope of the path-loss law.
        s_pos = 10.0 * n / np.log(10.0) * psig / r
        sig = np.sqrt(np.where(kind == 0, _sigma_x(np.nan_to_num(drop, nan=3.0)), 2.0) ** 2 + shadow_db**2 + s_pos**2)
        d = x_obs - model
        d = np.where(kind == 1, np.clip(d, 0.0, None), np.where(kind == 2, np.clip(-d, 0.0, None) * -1.0, d))
        return w * d / sig

    strong = sorted(meas + sat, key=lambda o: -(o.drop_db if np.isfinite(o.drop_db) else 25.0) - (5.0 if o.kind == "sat" else 0.0))
    starts = [(o.e, o.n) for o in strong[:4]]
    aff = np.array([[o.e, o.n] for o in meas + sat])
    wts = np.array([10.0 ** (min(o.drop_db if np.isfinite(o.drop_db) else 25.0, 30.0) / 10.0) for o in meas + sat])
    starts.append(tuple((aff * wts[:, None]).sum(axis=0) / wts.sum()))
    span = max(float(np.ptp(aff[:, 0])), float(np.ptp(aff[:, 1])), 500.0)
    c = aff.mean(axis=0)
    starts += [(c[0] + dx * span, c[1] + dy * span) for dx in (-0.6, 0.0, 0.6) for dy in (-0.6, 0.0, 0.6)]
    best = None
    lo = [-np.inf, -np.inf, -50.0] + ([1.8] if fit_n else [])
    hi = [np.inf, np.inf, 250.0] + ([4.0] if fit_n else [])
    for sx, sy in starts:
        r0 = np.maximum(np.hypot(pos[:, 0] - sx, pos[:, 1] - sy), 10.0)
        m0 = kind == 0
        p0 = [sx + 7.0, sy - 5.0, float(np.median(x_obs[m0] + 10.0 * n_exp * np.log10(r0[m0])))] + ([n_exp] if fit_n else [])
        try:
            sol = least_squares(resid, p0, loss="soft_l1", f_scale=1.5, bounds=(lo, hi), max_nfev=200)
        except ValueError:
            continue
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None:
        return None
    sx, sy, pw, n = unpack(best.x)
    r_fin = resid(best.x)
    active = np.abs(r_fin) > 0
    dof = max(int((kind == 0).sum() + active[kind != 0].sum()) - len(best.x), 1)
    s2 = max(float(np.sum(r_fin**2) / dof), 1.0)
    jac = best.jac
    try:
        cov = s2 * np.linalg.inv(jac.T @ jac + 1e-12 * np.eye(jac.shape[1]))
    except np.linalg.LinAlgError:
        cov = np.full((len(best.x), len(best.x)), np.nan)
    c2 = cov[:2, :2]
    if np.all(np.isfinite(c2)):
        vals, vecs = np.linalg.eigh(c2)
        vals = np.clip(vals, 0.0, None)
        semi = np.sqrt(CHI2_95_2DOF * vals)
        theta = float(np.degrees(np.arctan2(vecs[0, 1], vecs[1, 1])))    # bearing of the major axis from north
        ellipse = {"semi_major_m": float(semi[1]), "semi_minor_m": float(semi[0]), "bearing_deg": theta % 180.0}
    else:
        ellipse = None
    return {"e": float(sx), "n": float(sy), "p_db": float(pw), "n_exp": float(n), "cov": c2.tolist(), "ellipse95": ellipse,
            "n_meas": len(meas), "n_sat": len(sat), "n_clean": len(clean), "chi2_red": s2, "method": "cn0_loss_multilateration"}


def inside_ellipse(est: dict, e: float, n: float) -> bool:
    """Is the point inside the 95 % ellipse of an estimate?"""
    cov = np.array(est["cov"], dtype=float)
    if not np.all(np.isfinite(cov)):
        return False
    d = np.array([e - est["e"], n - est["n"]])
    try:
        return bool(d @ np.linalg.solve(cov + 1e-9 * np.eye(2), d) <= CHI2_95_2DOF)
    except np.linalg.LinAlgError:
        return False
