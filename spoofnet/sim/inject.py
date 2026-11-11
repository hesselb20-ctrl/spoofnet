"""Synthetic interference, applied to a MeasurementSet in the measurement domain.

Nothing here models or describes a transmitter. Each function only changes the
numbers a receiver would report (C/N0, AGC, pseudorange, Doppler, tracking) in
the way the corresponding class of interference is known to change them. The
same functions work on simulated sets and on recorded clean logs.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..data import LOWER, SUBBANDS, UPPER, MeasurementSet, code_sigma_m, doppler_sigma_mps
from ..geo import C, az_el, enu_basis
from .environment import ar1

BQ_HZ = 2.046e6     # effective spreading bandwidth assumed for the upper band
_COUPLING_DB = {    # received interference relative to the L1 sub-band; order follows SUBBANDS
    "L1_NARROW": (0.0, -8.0, -25.0, -200.0),
    "L1_WIDE": (0.0, 0.0, -3.0, -200.0),
    "ALL_BANDS": (0.0, 0.0, -2.0, -3.0),
}


@dataclass
class JamSpec:
    t0: int
    t1: int
    drop_db: float = 10.0          # C/N0 loss on the L1 sub-band at the plateau
    kind: str = "L1_NARROW"
    ramp_s: float = 3.0
    profile: np.ndarray | None = None   # optional (T,) C/N0 loss in dB for the whole session
    label: str = "jam"


@dataclass
class SpoofSpec:
    t0: int
    t1: int
    kind: str = "simple"           # simple | multi | drag | time_only | meacon
    consts: str = "G"              # constellations affected
    lower_band: bool = False       # lower band affected too
    offset_enu: tuple = (500.0, 0.0)   # claimed minus true position at t0, m
    follow: bool = False           # claimed position tracks the true motion instead of a fixed point
    drag_mps: tuple = (0.0, 0.0)   # growth of the offset, m/s
    time_off_m: float = 300.0      # step in common pseudorange
    time_drift_mps: float = 0.0    # common pseudorange-rate offset
    power_adv_db: float = 8.0      # received power above the authentic signals
    cn0_mode: str = "flat"         # flat | shaped
    cn0_level: float = 44.0
    fade_sigma: float = 1.0        # common-mode fading, dB
    pre_jam_s: int = 0
    stale_s: float = 0.0           # constellation time error of the false signals, s
    gap_s: int = 2                 # tracking gap at takeover
    label: str = "spoof"


def _dev(ms: MeasurementSet) -> dict:
    d = {"track_thr": 16.0, "acq_margin": 4.0, "acq_delay": 3, "cn0_quant": 0.1, "fe_bw_hz": 4e6,
         "agc_quant": 0.1, "code_s40": 3.0, "cn0_zen": 43.0, "cn0_slope": 12.0, "l5_offset": -2.5, "cn0_noise": 1.0}
    d.update(ms.meta.get("device", {}))
    return d


def _latent(ms: MeasurementSet) -> np.ndarray:
    lat = ms.truth.get("cn0_latent")
    return lat if lat is not None else np.where(np.isfinite(ms.cn0), ms.cn0, -99.0)


def _retrack(ms: MeasurementSet, latent_new, latent_old, extra_off=None, rng=None):
    """Re-run tracking on the changed signal levels and add the measurement noise that goes with them."""
    from .scenario import track_hysteresis
    dev = _dev(ms)
    force = ms.truth.get("force_off")
    tracked = track_hysteresis(latent_new, dev["track_thr"], dev["acq_margin"], dev["acq_delay"], force)
    if extra_off is not None:
        tracked &= ~extra_off
    had = np.isfinite(ms.pr)
    tracked &= had | ms.truth.get("_built", np.zeros_like(had))
    band = ms.sig_band[None, :]
    s_old, s_new = code_sigma_m(latent_old, band, dev["code_s40"]), code_sigma_m(latent_new, band, dev["code_s40"])
    d_old, d_new = doppler_sigma_mps(latent_old), doppler_sigma_mps(latent_new)
    shp = latent_new.shape
    ms.pr = np.where(tracked, ms.pr + rng.normal(0, 1, shp) * np.sqrt(np.clip(s_new**2 - s_old**2, 0, None)), np.nan)
    ms.prr = np.where(tracked, ms.prr + rng.normal(0, 1, shp) * np.sqrt(np.clip(d_new**2 - d_old**2, 0, None)), np.nan)
    q = dev["cn0_quant"]
    ms.cn0 = np.where(tracked, np.round(latent_new / q) * q, np.nan)
    ms.truth["cn0_latent"] = latent_new


def _agc_drop(ms: MeasurementSet, jn_band: dict, rng) -> None:
    """jn_band: front-end band -> (T,) linear interference-to-noise ratio in the spreading bandwidth."""
    dev = _dev(ms)
    for bnd, jn in jn_band.items():
        col = ms.agc[:, bnd]
        if not np.all(np.isfinite(col)) or np.nanstd(col) == 0.0:
            continue                                   # absent or stuck AGC reports nothing
        drop = 10.0 * np.log10(1.0 + jn * BQ_HZ / dev["fe_bw_hz"])
        ms.agc[:, bnd] = np.round((col - drop) / dev["agc_quant"]) * dev["agc_quant"]


def jam_profile(n: int, t0: int, t1: int, drop_db: float, ramp_s: float, rng=None) -> np.ndarray:
    t = np.arange(n, dtype=float)
    up = np.clip((t - t0) / max(ramp_s, 1e-3), 0, 1)
    down = np.clip((t1 - t) / max(ramp_s, 1e-3), 0, 1)
    prof = drop_db * np.minimum(up, down)
    if rng is not None:
        prof = prof * (1.0 + 0.04 * ar1(rng, n, 1, 1.0, 20.0)[:, 0])
    return np.clip(prof, 0, None)


def profile_from_source(ms: MeasurementSet, src_ecef, p1m_db: float, n_exp: float, shadow_db: float = 0.0,
                        t0: int = 0, t1: int | None = None, rng=None) -> np.ndarray:
    """C/N0 loss over time for a source at `src_ecef`. `p1m_db` is the interference-to-noise
    ratio (in the spreading bandwidth) that the device would see at 1 m."""
    n = ms.n_epochs
    dist = np.maximum(np.linalg.norm(ms.truth["pos"] - np.asarray(src_ecef)[None, :], axis=1), 1.0)
    jn_db = p1m_db - 10.0 * n_exp * np.log10(dist) + shadow_db
    if rng is not None:
        jn_db = jn_db + ar1(rng, n, 1, 1.0, 15.0)[:, 0]
    drop = 10.0 * np.log10(1.0 + 10.0 ** (jn_db / 10.0))
    t = np.arange(n)
    return np.where((t >= t0) & (t < (n if t1 is None else t1)), drop, 0.0)


def apply_jam(ms: MeasurementSet, spec: JamSpec, rng) -> None:
    n = ms.n_epochs
    prof = spec.profile if spec.profile is not None else jam_profile(n, spec.t0, spec.t1, spec.drop_db, spec.ramp_s, rng)
    jn = 10.0 ** (prof / 10.0) - 1.0
    coup = 10.0 ** (np.array(_COUPLING_DB[spec.kind])[ms.sig_sub] / 10.0)
    drop = 10.0 * np.log10(1.0 + jn[:, None] * coup[None, :])
    old = _latent(ms)
    new = old - drop - np.where(drop > 0.1, np.abs(rng.normal(0, 0.25, drop.shape)), 0.0)
    _retrack(ms, new, old, rng=rng)
    cb = _COUPLING_DB[spec.kind]
    _agc_drop(ms, {UPPER: jn * 10 ** (cb[0] / 10), LOWER: jn * 10 ** (cb[SUBBANDS.index("L5")] / 10)}, rng)
    active = np.flatnonzero(prof > 0.5)
    ms.truth.setdefault("attacks", []).append({"type": "jam", "kind": spec.kind, "label": spec.label,
                                "t0": int(active[0]) if active.size else spec.t0,
                                "t1": int(active[-1]) + 1 if active.size else spec.t1,
                                "drop_db": float(np.max(prof)), "profile": prof})


def apply_spoof(ms: MeasurementSet, spec: SpoofSpec, rng) -> None:
    from .scenario import constellation
    dev = _dev(ms)
    n, ns = ms.cn0.shape
    t = ms.t
    sel = (t >= spec.t0) & (t < spec.t1)
    pos, vel = ms.truth["pos"], ms.truth["vel"]
    lat0, lon0 = ms.meta["origin"]
    basis = enu_basis(lat0, lon0)
    dt = np.clip(t - spec.t0, 0, None)
    off = (np.array(spec.offset_enu)[None, :] + np.array(spec.drag_mps)[None, :] * dt[:, None]) @ basis[:2]
    doff = np.where(sel[:, None], (np.array(spec.drag_mps) @ basis[:2])[None, :], 0.0)
    i0 = min(int(spec.t0), n - 1)
    if spec.follow:
        p_s, v_s = pos + off, vel + doff
    else:
        p_s, v_s = pos[i0][None, :] + off, doff

    if spec.stale_s:
        sp, sv = constellation().states(ms.t0_gps + t + spec.stale_s)
    else:
        sp, sv = ms.sat_pos, ms.sat_vel
    sp, sv = sp[:, ms.sig_sat], sv[:, ms.sig_sat]
    az_c, el_c = az_el(p_s, sp)
    affected = np.array([("GERC"[c] in spec.consts) and (b == UPPER or spec.lower_band)
                         for c, b in zip(ms.sig_const, ms.sig_band)])
    active = sel[:, None] & affected[None, :] & (el_c > 5.0)

    old = _latent(ms)
    expected = (dev["cn0_zen"] - dev["cn0_slope"] * (1 - np.sin(np.radians(np.clip(ms.el, 0, 90))))
                + np.where(ms.sig_band == LOWER, dev["l5_offset"], 0.0)[None, :])
    deficit = np.where((ms.el > 15) & (old > 0), expected - old, np.nan)
    with np.errstate(all="ignore"):
        placement = np.nanmedian(deficit, axis=1)
    placement = 0.6 * np.clip(np.where(np.isfinite(placement), placement, 0.0), 0.0, 25.0)[:, None]
    fade = ar1(rng, n, 1, spec.fade_sigma, 3.0)
    if spec.cn0_mode == "flat":
        level = spec.cn0_level + rng.normal(0, 0.4, ns)[None, :] + rng.normal(0, 0.35, (n, ns))
    else:
        level = (dev["cn0_zen"] - dev["cn0_slope"] * (1 - np.sin(np.radians(np.clip(el_c, 0, 90))))
                 + np.where(ms.sig_band == LOWER, dev["l5_offset"], 0.0)[None, :]
                 + rng.normal(0, 1.0, ns)[None, :] + ar1(rng, n, ns, 0.7 * dev["cn0_noise"], 4.0)
                 + 0.4 * (spec.power_adv_db - 3.0))
    cn0_s = np.minimum(level + fade - placement, 52.0)

    # Signals that are not replaced still see a higher noise floor on the same carrier.
    rise_db = 10.0 * np.log10(1.0 + 10.0 ** ((spec.power_adv_db - 8.0) / 10.0))
    jn = (10.0 ** (rise_db / 10.0) - 1.0) * sel
    kind = "ALL_BANDS" if spec.lower_band else "L1_NARROW"
    coup = 10.0 ** (np.array(_COUPLING_DB[kind])[ms.sig_sub] / 10.0)
    rise = 10.0 * np.log10(1.0 + jn[:, None] * coup[None, :])
    new = np.where(active, cn0_s, old - rise)

    # Pseudorange and Doppler of the replaced signals follow the claimed position and clock.
    dvec = sp - p_s[:, None, :]
    r_s = np.linalg.norm(dvec, axis=-1)
    u_s = dvec / r_s[..., None]
    t_off = spec.time_off_m + spec.time_drift_mps * dt + spec.stale_s * C
    isb = ms.truth.get("isb_sig", np.zeros(ns))
    b_ref, d_ref = ms.truth["clock_bias"], ms.truth["clock_drift"]
    band = ms.sig_band[None, :]
    pr_s = (r_s + b_ref[:, None] + isb[None, :] + t_off[:, None]
            + rng.normal(0, 1, (n, ns)) * code_sigma_m(cn0_s, band, dev["code_s40"]))
    prr_s = (np.einsum("tni,tni->tn", sv - v_s[:, None, :], u_s) + d_ref[:, None] + spec.time_drift_mps
             + rng.normal(0, 1, (n, ns)) * doppler_sigma_mps(cn0_s))
    ms.pr = np.where(active, pr_s, ms.pr)
    ms.prr = np.where(active, prr_s, ms.prr)
    ms.el = np.where(active, el_c, ms.el)
    ms.az = np.where(active, az_c, ms.az)

    gap = np.zeros((n, ns), dtype=bool)
    if spec.kind != "drag" and spec.gap_s > 0:
        g0 = (t >= spec.t0) & (t < spec.t0 + spec.gap_s)
        g1 = (t >= spec.t1) & (t < spec.t1 + spec.gap_s + 1)
        gap = (g0 | g1)[:, None] & affected[None, :]
    ms.truth["_built"] = active | ms.truth.get("_built", np.zeros((n, ns), dtype=bool))
    # Replaced signals already carry their own noise; only the untouched ones need the extra noise.
    _retrack(ms, new, np.where(active, new, old), extra_off=gap, rng=rng)
    _agc_drop(ms, {UPPER: jn, LOWER: jn * (1.0 if spec.lower_band else 0.0)}, rng)

    if spec.stale_s:
        ms.truth["sat_pos_claimed"], ms.truth["sat_vel_claimed"], ms.truth["claimed_mask"] = sp, sv, active
    ms.truth["attacks"].append({"type": "meacon" if spec.kind == "meacon" else "spoof", "kind": spec.kind,
                                "label": spec.label, "t0": int(spec.t0), "t1": int(min(spec.t1, n)),
                                "claimed_pos": p_s, "consts": spec.consts, "lower_band": spec.lower_band})


def apply_attacks(ms: MeasurementSet, attacks, rng) -> None:
    from .scenario import emulate_fix
    for a in attacks:
        if isinstance(a, JamSpec):
            apply_jam(ms, a, rng)
        else:
            if a.pre_jam_s > 0:
                pre = JamSpec(a.t0 - a.pre_jam_s, a.t0, drop_db=25.0, kind="L1_WIDE", ramp_s=1.0, label="pre_jam")
                apply_jam(ms, pre, rng)
                ms.truth["attacks"].pop()              # part of the spoofing attack, not a separate one
                ms.truth["attacks_pre"] = (a.t0 - a.pre_jam_s, a.t0)
            apply_spoof(ms, a, rng)
    if ms.sat_pos is not None and "pos" in ms.truth:
        emulate_fix(ms)          # recorded logs keep the fix the phone reported
