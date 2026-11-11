"""Builds one simulated logging session as a MeasurementSet."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .. import pvt
from ..data import CONSTS, LOWER, SUBBANDS, UPPER, MeasurementSet, code_sigma_m, doppler_sigma_mps
from ..geo import az_el, ecef_to_lla, enu_basis, enu_to_ecef
from .constellation import Constellation, build_constellation
from .devices import DeviceModel, sample_device
from .environment import ENV_KINDS, ar1, attenuation
from .motion import gen_motion

# Places with documented interference history, plus quiet ones, for sky-geometry variety only.
ORIGINS = ((54.52, 18.80), (59.45, 24.80), (44.10, 28.70), (32.80, 34.95), (51.95, 4.10),
           (35.10, 33.40), (60.15, 24.95), (52.10, 5.20), (40.60, 22.95), (25.20, 55.30))
_NET = {"wifi": (25.0, 10), "cell": (400.0, 30), "rural": (1500.0, 60)}
_CONSTELLATION: Constellation | None = None


def constellation() -> Constellation:
    global _CONSTELLATION
    if _CONSTELLATION is None:
        _CONSTELLATION = build_constellation()
    return _CONSTELLATION


@dataclass
class ScenarioSpec:
    seed: int
    env: str
    duration: int = 1200
    wide: bool = False
    archetype: str | None = None
    attacks: list = field(default_factory=list)   # JamSpec / SpoofSpec, applied in order
    origin: tuple | None = None
    t0_gps: float | None = None
    device: DeviceModel | None = None
    route_seed: int | None = None     # same route and surroundings on every visit; noise still varies


def track_hysteresis(cn0_latent, thr, acq_margin, acq_delay, force_off=None):
    """A signal is acquired after `acq_delay` s above thr + margin and dropped below thr."""
    t_n, n = cn0_latent.shape
    out = np.zeros((t_n, n), dtype=bool)
    state = cn0_latent[0] >= thr + acq_margin
    cnt = np.zeros(n, dtype=int)
    for t in range(t_n):
        x = cn0_latent[t]
        cnt = np.where(x >= thr + acq_margin, cnt + 1, 0)
        state = np.where(state, x >= thr, cnt >= acq_delay)
        if force_off is not None and force_off[t]:
            state = np.zeros(n, dtype=bool)
            cnt[:] = 0
        out[t] = state
    return out


def emulate_fix(ms: MeasurementSet, x0=None) -> None:
    """Fill the chipset fix fields from the measurements, the way a receiver that
    trusts the majority-consistent set of signals would."""
    isb = ms.truth.get("isb_sig", 0.0)   # the receiver knows its own inter-system biases
    sp, sv = ms.sat_pos[:, ms.sig_sat], ms.sat_vel[:, ms.sig_sat]
    if "sat_pos_claimed" in ms.truth:          # false signals carry their own orbit data
        m = ms.truth["claimed_mask"]
        sp = np.where(m[..., None], ms.truth["sat_pos_claimed"], sp)
        sv = np.where(m[..., None], ms.truth["sat_vel_claimed"], sv)
    if x0 is None:
        x0 = ms.truth["pos"]
    sol = pvt.consensus_solve(ms, x0, isb, sp, sv)
    ok = sol.ok & (sol.n >= 4)
    ms.fix_ecef = np.where(ok[:, None], sol.x, np.nan)
    ms.fix_vel = np.where(ok[:, None], sol.v, np.nan)
    ms.fix_acc = np.where(ok, np.clip(1.5 * sol.sig_pos * np.maximum(sol.rms, 1.0), 2.0, 2000.0), np.nan)
    ms.truth["fix_clock"] = sol.b


def simulate(spec: ScenarioSpec) -> MeasurementSet:
    rng = np.random.default_rng(spec.seed)
    dev = spec.device or sample_device(rng, spec.archetype, spec.wide)
    n = int(spec.duration)
    t = np.arange(n, dtype=float)
    lat0, lon0 = ORIGINS[rng.integers(len(ORIGINS))]
    lat0 += rng.uniform(-0.3, 0.3)
    lon0 += rng.uniform(-0.3, 0.3)
    if spec.origin is not None:               # exact start point, used by multi-device scenarios
        lat0, lon0 = spec.origin
    t0 = spec.t0_gps if spec.t0_gps is not None else float(rng.uniform(0, 7 * 86400))
    motion_kinds, net_kinds = ENV_KINDS[spec.env]
    rr = np.random.default_rng(spec.route_seed) if spec.route_seed is not None else rng
    motion = gen_motion(str(rr.choice(motion_kinds)), n, rr)
    net_kind = str(rng.choice(net_kinds))

    pos = enu_to_ecef(motion.enu, lat0, lon0, 30.0)
    vel = motion.vel @ enu_basis(lat0, lon0)

    con = constellation()
    sat_pos, sat_vel = con.states(t0 + t)
    az_s, el_s = az_el(pos, sat_pos)
    att_s, bias_s, env_info = attenuation(spec.env, az_s, el_s, motion, rng, spec.wide, rr)

    # Signal table: every supported satellite on the upper band, plus the lower band where it exists.
    sup = np.array([CONSTS[c] in dev.consts for c in con.const])
    up = np.flatnonzero(sup)
    lo = np.flatnonzero(sup & con.has_l5 & (con.const != 2)) if dev.dual else np.array([], dtype=int)
    sig_sat = np.concatenate([up, lo])
    sig_band = np.concatenate([np.full(up.size, UPPER), np.full(lo.size, LOWER)])
    sig_const = con.const[sig_sat]
    sub_up = np.array([SUBBANDS.index(x) for x in ("L1", "L1", "G1", "B1")])
    sig_sub = np.where(sig_band == LOWER, SUBBANDS.index("L5"), sub_up[sig_const])
    ns = sig_sat.size

    el, az = el_s[:, sig_sat], az_s[:, sig_sat]
    sat_off = rng.normal(0, 1.0, ns)
    cn0 = (dev.cn0_zen - dev.cn0_slope * (1.0 - np.sin(np.radians(np.clip(el, 0, 90))))
           + np.where(sig_band == LOWER, dev.l5_offset, 0.0)[None, :] + sat_off[None, :]
           + ar1(rng, n, ns, dev.cn0_noise, 4.0)
           # Fading: uncorrelated from second to second, strongest when the phone moves.
           + rng.normal(0, 1.0, (n, ns)) * (dev.cn0_fast * np.where(motion.speed > 0.3, 1.0, 0.45))[:, None]
           - att_s[:, sig_sat] - np.where(sig_band == LOWER, 0.7, 0.0)[None, :] * rng.normal(0, 1.0, (n, ns)))
    cn0 = cn0 - np.clip(6.0 - el, 0, None) * 1.5          # extra loss close to the horizon
    cn0 = np.where(el > 0.0, cn0, -99.0)

    # Clock: two-state model, with hardware resets on duty-cycling receivers.
    drift = rng.uniform(-300, 300) + np.cumsum(rng.normal(0, dev.tcxo_sigma, n))
    drift += np.cumsum(ar1(rng, n, 1, 0.002, 600.0)[:, 0])
    bias = np.cumsum(drift) - drift + np.cumsum(rng.normal(0, 0.02, n))
    clk_disc = np.zeros(n, dtype=int)
    force_off = np.zeros(n, dtype=bool)
    if dev.duty_cycle:
        for te in np.sort(rng.integers(40, max(41, n - 20), size=rng.poisson(2.5 * n / 3600.0))):
            gap = int(rng.integers(2, 10))
            force_off[te:te + gap] = True
            clk_disc[te + gap:] += 1
            bias[te + gap:] += rng.uniform(-1e5, 1e5)
            if rng.random() < 0.3:                      # some receivers also steer by whole milliseconds
                bias[te + gap:] += 299792.458 * rng.integers(-3, 4)

    tracked = track_hysteresis(cn0, dev.track_thr, dev.acq_margin, dev.acq_delay, force_off)

    isb_c = np.array([0.0, rng.normal(0, 3.0), rng.normal(0, 30.0), rng.normal(0, 10.0)])
    isb_sig = isb_c[sig_const] + np.where(sig_band == LOWER, rng.normal(0, 5.0), 0.0)
    dvec = sat_pos[:, sig_sat] - pos[:, None, :]
    rng_m = np.linalg.norm(dvec, axis=-1)
    u = dvec / rng_m[..., None]
    atm = rng.normal(0, 1.5, ns)[None, :] / np.sin(np.radians(np.clip(el, 8, 90)))
    sig_pr = code_sigma_m(cn0, sig_band[None, :], dev.code_s40)
    pr = rng_m + bias[:, None] + isb_sig[None, :] + atm + bias_s[:, sig_sat] + rng.normal(0, 1, (n, ns)) * sig_pr
    prr = (np.einsum("tni,tni->tn", sat_vel[:, sig_sat] - vel[:, None, :], u) + drift[:, None]
           + rng.normal(0, 1, (n, ns)) * doppler_sigma_mps(cn0) * (1.0 + bias_s[:, sig_sat] / 20.0))

    agc = np.full((n, 2), np.nan)
    if dev.has_agc:
        for bnd in ((UPPER, LOWER) if dev.dual else (UPPER,)):
            base = rng.uniform(35, 55)
            if dev.agc_stuck:
                agc[:, bnd] = base
            else:
                raw = (base + dev.agc_drift * t / 3600.0 + ar1(rng, n, 1, dev.agc_noise, 3.0)[:, 0]
                       + ar1(rng, n, 1, dev.agc_slow, 120.0)[:, 0])
                agc[:, bnd] = np.round(raw / dev.agc_quant) * dev.agc_quant

    net = np.full((n, 3), np.nan)
    net_acc = np.full(n, np.nan)
    if net_kind != "none":
        sigma, period = _NET[net_kind]
        sigma *= rng.uniform(0.6, 1.6)
        basis = enu_basis(lat0, lon0)
        for a in range(int(rng.integers(0, period)), n, period):
            if rng.random() < 0.1:
                continue                                  # missed update keeps the previous value
            off = rng.normal(0, sigma / np.sqrt(2), 2)
            net[a:a + period] = pos[a] + off[0] * basis[0] + off[1] * basis[1]
            net_acc[a:a + period] = sigma * rng.uniform(0.9, 1.6)
        first = np.flatnonzero(np.isfinite(net_acc))
        if first.size:
            net[: first[0]] = net[first[0]]
            net_acc[: first[0]] = net_acc[first[0]]

    q = dev.cn0_quant
    ms = MeasurementSet(
        t=t, t0_gps=t0, sig_const=sig_const, sig_svid=con.svid[sig_sat], sig_band=sig_band, sig_sub=sig_sub,
        sig_sat=sig_sat,
        cn0=np.where(tracked, np.round(cn0 / q) * q, np.nan),
        pr=np.where(tracked, pr, np.nan), prr=np.where(tracked, prr, np.nan),
        az=az, el=el, agc=agc, clk_disc=clk_disc,
        fix_ecef=np.full((n, 3), np.nan), fix_vel=np.full((n, 3), np.nan), fix_acc=np.full(n, np.nan),
        net_ecef=net, net_acc=net_acc,
        imu_vib=motion.vib, imu_acc_h=motion.acc_h, imu_yaw=motion.yaw, imu_tilt=motion.tilt,
        sat_pos=sat_pos, sat_vel=sat_vel,
        meta={"env": spec.env, "seed": spec.seed, "device": dev.to_dict(), "tier": dev.tier,
              "has_agc": dev.agc_works, "dual": dev.dual, "net_kind": net_kind, "origin": (lat0, lon0),
              "evidence": "replay"},
        truth={"pos": pos, "vel": vel, "clock_bias": bias, "clock_drift": drift, "cn0_latent": cn0,
               "blackouts": env_info["blackouts"], "attacks": [], "handling": motion.handling,
               "speed": motion.speed, "isb_sig": isb_sig, "force_off": force_off},
    )
    emulate_fix(ms)
    if spec.attacks:
        from .inject import apply_attacks
        apply_attacks(ms, spec.attacks, rng)
    return ms
