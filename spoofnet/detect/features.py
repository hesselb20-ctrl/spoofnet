"""Per-epoch detector features (DESIGN.md 5.1).

`extract` reads only what a phone can observe: the measurement arrays, the
almanac-derived satellite positions and the capability flags in `meta`. It
never touches `ms.truth`.

Two stages:
  1. stateless features, vectorised over the whole session;
  2. a causal per-epoch loop for everything that depends on the adaptive
     per-signal C/N0 baseline and the AGC baseline, which freeze while the
     signal looks suspicious so that interference is not learned as normal.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field, asdict

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .. import pvt
from ..data import LOWER, SUBBANDS, UPPER, MeasurementSet
from ..geo import az_el

NAMES = (
    "drop_l1", "spread_l1", "lost_l1", "n_l1", "droplb_l1",
    "drop_l5", "spread_l5", "lost_l5", "n_l5",
    "drop_b1", "drop_g1", "drop_g", "drop_e",
    "zagc_u", "zagc_l", "absdef_l1", "absspread_l1", "handling",
    "flat_min", "slope_min", "cm_max",
    "clk_step", "drift_step", "xpos", "xclk", "xvel", "grp_fail",
    "nloc", "jump", "imu_sm", "imu_am", "imu_fm", "alm_below", "alm_elmis",
    "has_agc_u", "has_agc_l", "has_dual", "has_net", "has_fix", "frozen",
    "spread_g1", "n_g1", "lost_g1", "spread_b1", "n_b1", "drop_hi", "drop_lo", "settling",
    "flat_t", "flat_tt",
)
IDX = {n: i for i, n in enumerate(NAMES)}
FEATURE_VERSION = 5              # bump when extraction changes, so cached frames are rebuilt
MS_STEP_M = 299_792.458          # one millisecond of clock, in metres


@dataclass
class DeviceBaseline:
    """What the phone has learned about itself from its own clean history."""
    zen: tuple = (43.0, 40.5)        # expected C/N0 at zenith per band
    slope: tuple = (12.0, 12.0)      # dB between zenith and horizon per band
    agc_sigma: tuple = (np.nan, np.nan)   # short-term AGC noise per band; NaN = no usable AGC

    def expected(self, el_deg, band):
        s = 1.0 - np.sin(np.radians(np.clip(el_deg, 0.0, 90.0)))
        return np.where(band == LOWER, self.zen[1] - self.slope[1] * s, self.zen[0] - self.slope[0] * s)

    def to_dict(self):
        return asdict(self)


def fit_device_baseline(ms: MeasurementSet) -> DeviceBaseline:
    """Fit from a clean open-sky session. The upper envelope is used so that
    partial obstruction during calibration cannot pull the expectation down."""
    zen, slope = [43.0, 40.5], [12.0, 12.0]
    for b in (UPPER, LOWER):
        m = ms.sig_band == b
        if not m.any():
            continue
        c, e = ms.cn0[:, m], ms.el[:, m]
        ok = np.isfinite(c) & (e > 8.0)
        if ok.sum() < 200:
            continue
        x = 1.0 - np.sin(np.radians(e[ok]))
        y = c[ok]
        a = np.polyfit(x, y, 1)
        for _ in range(3):                      # asymmetric refit: keep points near or above the line
            r = y - np.polyval(a, x)
            keep = r > -1.5 * np.std(r)
            a = np.polyfit(x[keep], y[keep], 1)
        zen[b], slope[b] = float(a[1]), float(-a[0])
    sig = [np.nan, np.nan]
    for b in (UPPER, LOWER):
        col = ms.agc[:, b]
        fin = np.isfinite(col)
        if fin.mean() > 0.8 and np.nanstd(col) > 0:
            # Spread of AGC around the same slow baseline the detector keeps (time constant
            # tau_agc), so slow wander within a session counts as normal for this phone.
            v = col[fin]
            ref = np.empty_like(v)
            acc = v[0]
            for i, x in enumerate(v):
                ref[i] = acc
                acc += (x - acc) / 300.0
            d = (v - ref)[min(120, len(v) // 4):]
            sig[b] = float(max(1.4826 * np.median(np.abs(d - np.median(d))), np.std(d) * 0.7, 0.12))
    return DeviceBaseline(tuple(zen), tuple(slope), tuple(sig))


@dataclass
class Gates:
    """Raw levels above which baselines stop adapting. Set from clean training data
    by experiments/calibrate.py; the defaults disable freezing."""
    u: float = np.inf          # uniform-drop statistic drop / (spread + 1)
    spread: float = np.inf     # the drop only counts as uniform below this spread, dB
    lost: float = 0.7          # share of baseline signals lost
    agc: float = np.inf        # AGC fall in sigmas
    flat: float = -np.inf      # C/N0 flatness (low is suspicious)
    clk: float = np.inf
    xpos: float = np.inf
    nloc: float = np.inf
    jump: float = np.inf
    max_freeze_s: int = 1800
    tau_off: float = 90.0
    tau_agc: float = 300.0
    warmup_s: int = 90
    handling_adapt_s: int = 60   # after the phone is moved, baselines re-settle for this long
    tau_fast: float = 20.0       # and adapt with this time constant while they do

    def to_dict(self):
        return {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in asdict(self).items()}

    @staticmethod
    def from_dict(d):
        g = Gates()
        for k, v in d.items():
            if v is not None:
                setattr(g, k, v)
        return g


@dataclass
class Frame:
    x: np.ndarray                     # (T, len(NAMES))
    aux: dict = field(default_factory=dict)

    def col(self, name):
        return self.x[:, IDX[name]]


def _rolling_median(x, w):
    pad = np.concatenate([np.full(w - 1, x[0]), x])
    return np.median(sliding_window_view(pad, w), axis=1)


def _rolling(x, w, fn):
    """Causal rolling reduction; NaN-aware; the first w-1 outputs use the available prefix."""
    pad = np.concatenate([np.full(w - 1, np.nan), x])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return fn(sliding_window_view(pad, w), axis=1)


def latch(x, decay_s: float):
    """Peak hold with exponential decay, so a one-epoch impulse stays visible to the fusion stage."""
    lam = float(np.exp(-1.0 / decay_s))
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(np.where(np.isfinite(x), x, 0.0)):
        acc = max(v, acc * lam)
        y[i] = acc
    return y


def _ffill_rows(a):
    ok = np.all(np.isfinite(a), axis=1)
    idx = np.where(ok, np.arange(len(a)), -1)
    idx = np.maximum.accumulate(idx)
    first = np.argmax(ok) if ok.any() else 0
    idx = np.where(idx < 0, first, idx)
    out = a[idx]
    return out if ok.any() else np.full_like(a, np.nan)


def _prev_valid(ok, max_gap: int = 15):
    """For each epoch: index of the last earlier epoch with ok, the gap in seconds, and
    whether the pair is usable. A takeover usually comes with a few seconds of lost
    tracking, so steps have to be measured across that gap, not between neighbours."""
    n = len(ok)
    last = np.maximum.accumulate(np.where(ok, np.arange(n), -1))
    prev = np.concatenate([[-1], last[:-1]])
    gap = np.arange(n) - prev
    valid = ok & (prev >= 0) & (gap <= max_gap)
    return np.maximum(prev, 0), gap.astype(float), valid


def _nanmax(stack):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmax(np.stack(stack, axis=0), axis=0) if stack else None


def _stateless(ms: MeasurementSet, base: DeviceBaseline) -> dict:
    n, ns = ms.cn0.shape
    nan = np.full(n, np.nan)
    f: dict = {}
    trk = np.isfinite(ms.cn0)

    # --- position, velocity and clock per constellation and band -------------------------
    x0 = _ffill_rows(ms.fix_ecef)
    if not np.all(np.isfinite(x0)):
        x0 = _ffill_rows(ms.net_ecef)
    sols = pvt.solve_groups(ms, x0) if ms.sat_pos is not None and np.all(np.isfinite(x0)) else {}
    masks = pvt.group_masks(ms) if sols else {}
    same_clk = np.concatenate([[False], ms.clk_disc[1:] == ms.clk_disc[:-1]])
    zb, zd, zj, zn, fails, eligible = [], [], [], [], np.zeros(n), np.zeros(n)
    info = {}
    net_ok = np.all(np.isfinite(ms.net_ecef), axis=1)
    net_new = net_ok & np.concatenate([[True], np.any(ms.net_ecef[1:] != ms.net_ecef[:-1], axis=1)])
    for g, s in sols.items():
        ok = s.ok & (s.n >= 5)
        sb = s.sig_b * np.maximum(s.rms, 1.0)
        sp = s.sig_pos * np.maximum(s.rms, 1.0)
        info[g] = (ok, s, sb, sp)
        prev, gap, pair = _prev_valid(ok)
        pair_clk = pair & (ms.clk_disc == ms.clk_disc[prev])
        e_b = s.b - s.b[prev] - s.d[prev] * gap
        k = np.round(e_b / MS_STEP_M)
        steer = (k != 0) & (np.abs(e_b - k * MS_STEP_M) < 30.0)       # whole-millisecond clock steering
        z = np.abs(e_b) / np.sqrt(sb**2 + sb[prev] ** 2 + (s.sig_d[prev] * gap) ** 2 + (0.05 * gap**1.5) ** 2 + 0.3**2)
        zb.append(np.where(pair_clk & ~steer, z, np.nan))
        zd.append(np.where(pair_clk, np.abs(s.d - s.d[prev])
                           / np.sqrt(s.sig_d**2 + s.sig_d[prev] ** 2 + 0.08**2 * gap + 0.08**2), np.nan))
        disp = np.linalg.norm(s.x - s.x[prev], axis=1)
        speed = 0.5 * (np.linalg.norm(s.v, axis=1) + np.linalg.norm(s.v[prev], axis=1))
        allow = speed * gap + gap**2 + 3.0 + 2.0 * (sp + sp[prev])       # gap^2: room for 2 m/s^2 unseen
        zj.append(np.where(pair, np.clip(disp - allow, 0, None) / (sp + sp[prev] + 1.0), np.nan))
        zn.append(np.where(ok & net_new, np.linalg.norm(s.x - ms.net_ecef, axis=1) / np.sqrt(sp**2 + ms.net_acc**2), np.nan))
        has_pos = np.all(np.isfinite(ms.sat_pos[:, ms.sig_sat[masks[g]]]), axis=-1)
        cnt = (trk[:, masks[g]] & has_pos).sum(axis=1)
        eligible += cnt >= 6
        fails += (cnt >= 6) & (~s.ok | (s.rms > 8.0))
    f["clk_step"] = _nanmax(zb) if zb else nan
    f["drift_step"] = _nanmax(zd) if zd else nan
    f["grp_fail"] = np.where(eligible > 0, fails / np.maximum(eligible, 1), np.nan)

    xpos, xclk, xvel = [], [], []
    names = list(info)
    lag = 30
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            oi, si, sbi, spi = info[names[i]]
            oj, sj, sbj, spj = info[names[j]]
            both = oi & oj
            dpos = np.linalg.norm(si.x - sj.x, axis=1)
            xpos.append(np.where(both, dpos / np.sqrt(spi**2 + spj**2 + 25.0), np.nan))
            xvel.append(np.where(both, np.linalg.norm(si.v - sj.v, axis=1), np.nan))
            q = si.b - sj.b
            sq = np.sqrt(sbi**2 + sbj**2)
            z = np.abs(q - np.roll(q, lag)) / np.sqrt(sq**2 + np.roll(sq, lag) ** 2 + 1.0)
            z = np.where(both & np.roll(both, lag), z, np.nan)
            z[:lag] = np.nan
            xclk.append(z)
    f["xpos"] = _nanmax(xpos) if xpos else nan
    f["xclk"] = _nanmax(xclk) if xclk else nan
    f["xvel"] = _nanmax(xvel) if xvel else nan

    # --- chipset fix against the network position, and fix jumps ------------------------
    fix_ok = np.all(np.isfinite(ms.fix_ecef), axis=1)
    z_fix = np.where(fix_ok & net_new,
                     np.linalg.norm(ms.fix_ecef - ms.net_ecef, axis=1) / np.sqrt(ms.fix_acc**2 + ms.net_acc**2), np.nan)
    nloc = _nanmax(zn + [z_fix])
    idx = np.maximum.accumulate(np.where(np.isfinite(nloc), np.arange(n), -1))
    f["nloc"] = np.where(idx >= 0, nloc[np.maximum(idx, 0)], np.nan)     # hold between network updates
    f["nloc"] = np.where(net_ok, f["nloc"], np.nan)

    v_fix = np.linalg.norm(ms.fix_vel, axis=1)
    prev, gap, pair = _prev_valid(fix_ok)
    disp = np.linalg.norm(ms.fix_ecef - ms.fix_ecef[prev], axis=1)
    acc2 = ms.fix_acc + ms.fix_acc[prev]
    zf = np.clip(disp - 0.5 * (v_fix + v_fix[prev]) * gap - gap**2 - 3.0 - 2.0 * acc2, 0, None) / (acc2 + 1.0)
    f["jump"] = _nanmax(zj + [np.where(pair, zf, np.nan)])

    # --- Doppler against the IMU -------------------------------------------------------
    still = (ms.imu_vib < 0.03) & (ms.imu_acc_h < 0.15) & (np.abs(ms.imu_yaw) < 0.03)
    still5 = _rolling(still.astype(float), 5, np.min) > 0.5
    v_any = _nanmax([v_fix] + [np.where(o, np.linalg.norm(s.v, axis=1), np.nan) for o, s, _, _ in info.values()])
    f["imu_sm"] = _rolling(np.where(still5, np.where(np.isfinite(v_any), v_any, 0.0), 0.0), 5, np.min)
    dv = np.linalg.norm(ms.fix_vel - np.roll(ms.fix_vel, 1, axis=0), axis=1)
    am = np.clip(dv - ms.imu_acc_h - np.roll(ms.imu_acc_h, 1) - 0.6, 0, None)
    am = np.where((ms.fix_acc < 20.0) & (np.roll(ms.fix_acc, 1) < 20.0), am, np.nan)   # only with a solid fix
    am[0] = np.nan
    f["imu_am"] = am
    yaw30 = _rolling(np.abs(ms.imu_yaw), 30, np.nansum)
    vib30 = _rolling(ms.imu_vib, 30, np.nanmedian)
    vmax30 = _rolling(np.where(np.isfinite(v_fix), v_fix, np.nan), 30, np.nanmax)
    f["imu_fm"] = np.where(np.isfinite(vmax30), yaw30 * (vib30 > 0.12) * (vmax30 < 0.4), np.nan)

    # --- sky against the almanac ---------------------------------------------------------
    if ms.sat_pos is not None:
        p_tr = np.where(net_ok[:, None], ms.net_ecef, x0)
        if np.all(np.isfinite(p_tr)):
            _, el_alm = az_el(p_tr, ms.sat_pos[:, ms.sig_sat])
            cnt = trk.sum(axis=1)
            f["alm_below"] = np.where(cnt >= 4, (trk & (el_alm < -3.0)).sum(axis=1) / np.maximum(cnt, 1), np.nan)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                f["alm_elmis"] = np.nanmedian(np.where(trk, np.abs(ms.el - el_alm), np.nan), axis=1)
    f.setdefault("alm_below", nan)
    f.setdefault("alm_elmis", nan)

    # --- C/N0 shape per constellation ----------------------------------------------------
    flat, slope, cm, flat_t, flat_tt = [], [], [], [], []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for c in range(4):
            m = (ms.sig_const == c) & (ms.sig_band == UPPER)
            if m.sum() < 5:
                continue
            x = ms.cn0[:, m]
            cnt = np.isfinite(x).sum(axis=1)
            # Robust on purpose: one authentic straggler near the horizon must not hide a flat set.
            med = np.nanmedian(x, axis=1, keepdims=True)
            mad = 1.4826 * np.nanmedian(np.abs(x - med), axis=1, keepdims=True)
            flat.append(np.where(cnt >= 5, mad[:, 0], np.nan))
            keep = np.abs(x - med) <= np.maximum(3.0 * mad, 2.0)
            xk = np.where(keep, x, np.nan)
            s = np.where(keep, np.sin(np.radians(np.clip(ms.el[:, m], 0, 90))), np.nan)
            sc, xc = s - np.nanmean(s, axis=1, keepdims=True), xk - np.nanmean(xk, axis=1, keepdims=True)
            var = np.nanmean(sc**2, axis=1)
            nk = keep.sum(axis=1)
            sl = np.nanmean(sc * xc, axis=1) / np.maximum(var, 1e-6)
            slope.append(np.where((nk >= 5) & (var > 0.02), sl / base.slope[UPPER], np.nan))
            # Is the missing elevation trend significant? t statistic of "slope equals the
            # device's own slope", then weighted by how tightly the C/N0 values sit together.
            resid = xc - sl[:, None] * sc
            se = np.sqrt(np.nansum(resid**2, axis=1) / np.maximum(nk - 2, 1) / np.maximum(nk * var, 1e-6))
            tstat = np.where((nk >= 5) & (var > 0.01), (base.slope[UPPER] - sl) / np.sqrt(se**2 + 1.0), np.nan)
            flat_t.append(tstat)
            flat_tt.append(tstat * np.clip(1.0 - mad[:, 0] / 1.5, 0.0, 1.0))
            d = np.diff(x, axis=0, prepend=np.nan)
            nd = np.isfinite(d).sum(axis=1)
            md = np.where(nd >= 4, np.nanmean(d, axis=1), np.nan)
            num = _rolling(md**2, 20, np.nanmean)
            den = _rolling(np.where(nd >= 4, np.nanmean(d**2, axis=1), np.nan), 20, np.nanmean)
            cm.append(np.where(den > 1e-3, num / np.maximum(den, 1e-3), np.nan))
    f["flat_min"] = np.nanmin(np.stack(flat), axis=0) if flat else nan
    f["slope_min"] = np.nanmin(np.stack(slope), axis=0) if slope else nan
    f["cm_max"] = _nanmax(cm) if cm else nan
    f["flat_t"] = _nanmax(flat_t) if flat_t else nan
    f["flat_tt"] = _nanmax(flat_tt) if flat_tt else nan
    f["has_net"] = net_ok.astype(float)
    f["has_fix"] = fix_ok.astype(float)
    return f


def extract(ms: MeasurementSet, base: DeviceBaseline, gates: Gates | None = None) -> Frame:
    g = gates or Gates()
    n, ns = ms.cn0.shape
    f = _stateless(ms, base)
    out = np.full((n, len(NAMES)), np.nan)
    for k, v in f.items():
        out[:, IDX[k]] = v

    # Raw spoofing suspicion from stateless features, held for a minute.
    def lv(name, decay=None):
        v = np.where(np.isfinite(f[name]), f[name], 0.0)
        return latch(v, decay) if decay else v
    spoof_raw = ((np.where(np.isfinite(f["flat_min"]), f["flat_min"], np.inf) < g.flat)
                 | (lv("clk_step", 30.0) > g.clk) | (lv("xpos") > g.xpos) | (lv("nloc") > g.nloc)
                 | (lv("jump", 30.0) > g.jump) | (lv("grp_fail") > 0.34) | (lv("alm_below") > 0.15))

    # Logs without GnssStatus records have no elevation. A fixed mid-sky value keeps the
    # expectation constant per signal, and the per-signal baseline absorbs the rest.
    el_use = np.where(np.isfinite(ms.el), ms.el, 45.0)
    res = ms.cn0 - base.expected(el_use, ms.sig_band[None, :])
    sub = {name: np.flatnonzero(ms.sig_sub == SUBBANDS.index(name)) for name in SUBBANDS}
    con_up = {c: np.flatnonzero((ms.sig_const == i) & (ms.sig_band == UPPER)) for i, c in ((0, "g"), (1, "e"))}
    expected_floor = base.expected(el_use, ms.sig_band[None, :])
    agc_ok = [bool(np.isfinite(base.agc_sigma[b])) and bool(np.isfinite(ms.agc[:, b]).mean() > 0.8) for b in (UPPER, LOWER)]
    has_dual = float(sub["L5"].size >= 4)

    off = np.zeros(ns)
    cnt = np.zeros(ns)
    pres = np.zeros(ns)
    agc_base = np.array([ms.agc[np.argmax(np.isfinite(ms.agc[:, b])), b] for b in (UPPER, LOWER)], dtype=float)
    a_off, a_agc, a_p = 1.0 / g.tau_off, 1.0 / g.tau_agc, 1.0 / 45.0
    last_tilt = -1e9
    adapt_until = -1
    a_fast = 1.0 / g.tau_fast
    freeze_run = 0
    track_thr = 15.0
    col = IDX

    def stats(idx, dev, m_in):
        sel = idx[m_in[idx]]
        if sel.size < 3:
            return np.nan, np.nan, sel.size
        d = dev[sel]
        med = np.median(d)
        return -med, 1.4826 * np.median(np.abs(d - med)), sel.size

    for t in range(n):
        r = res[t]
        trk = np.isfinite(r)
        inset = (pres > 0.6) & (cnt >= 20)
        dev = r - off
        m_in = inset & trk
        row = out[t]

        d1, s1, n1 = stats(sub["L1"], dev, m_in)
        base_n1 = int(inset[sub["L1"]].sum())
        lost1 = 1.0 - n1 / base_n1 if base_n1 >= 4 else np.nan
        row[col["drop_l1"]], row[col["spread_l1"]], row[col["n_l1"]], row[col["lost_l1"]] = d1, s1, n1, lost1
        if base_n1 >= 4:
            lost_idx = sub["L1"][inset[sub["L1"]] & ~trk[sub["L1"]]]
            if lost_idx.size:
                # A lost signal fell at least from its baseline level to the tracking threshold.
                row[col["droplb_l1"]] = float(np.median(expected_floor[t, lost_idx] + off[lost_idx] - track_thr))
            else:
                row[col["droplb_l1"]] = 0.0
        d5, s5, n5 = stats(sub["L5"], dev, m_in)
        base_n5 = int(inset[sub["L5"]].sum())
        lost5 = 1.0 - n5 / base_n5 if base_n5 >= 4 else np.nan
        row[col["drop_l5"]], row[col["spread_l5"]], row[col["n_l5"]], row[col["lost_l5"]] = d5, s5, n5, lost5
        row[col["drop_b1"]], row[col["spread_b1"]], row[col["n_b1"]] = stats(sub["B1"], dev, m_in)
        dg, sg, ng = stats(sub["G1"], dev, m_in)
        base_ng = int(inset[sub["G1"]].sum())
        row[col["drop_g1"]], row[col["spread_g1"]], row[col["n_g1"]] = dg, sg, ng
        row[col["lost_g1"]] = 1.0 - ng / base_ng if base_ng >= 4 else np.nan
        # The same drop overhead and near the horizon: a roof does not do that, added noise does.
        el_t = el_use[t]
        row[col["drop_hi"]] = stats(sub["L1"][el_t[sub["L1"]] >= 45.0], dev, m_in)[0]
        row[col["drop_lo"]] = stats(sub["L1"][el_t[sub["L1"]] < 30.0], dev, m_in)[0]
        row[col["drop_g"]] = stats(con_up["g"], dev, m_in)[0]
        row[col["drop_e"]] = stats(con_up["e"], dev, m_in)[0]

        sel = sub["L1"][trk[sub["L1"]]]
        if sel.size >= 4:
            a = r[sel]
            med = np.median(a)
            row[col["absdef_l1"]], row[col["absspread_l1"]] = -med, 1.4826 * np.median(np.abs(a - med))

        z = [np.nan, np.nan]
        for b in (UPPER, LOWER):
            if agc_ok[b]:
                z[b] = (ms.agc[t, b] - agc_base[b]) / base.agc_sigma[b]
        row[col["zagc_u"]], row[col["zagc_l"]] = z
        if ms.imu_tilt[t] > 20.0:
            last_tilt = t
            adapt_until = t + g.handling_adapt_s
        row[col["handling"]] = float(np.exp(-(t - last_tilt) / 20.0))

        u1 = d1 / (s1 + 1.0) if np.isfinite(d1) else 0.0
        u5 = d5 / (s5 + 1.0) if np.isfinite(d5) else 0.0
        # An AGC excursion only counts together with a C/N0 effect. On its own it would freeze the
        # AGC baseline, the baseline would stop following thermal drift, and the freeze would feed itself.
        cn0_hit = ((np.isfinite(d1) and d1 > 1.5) or (np.isfinite(d5) and d5 > 1.5)
                   or (np.isfinite(lost1) and lost1 > 0.3))
        agc_hit = (np.isfinite(z[0]) and -z[0] > g.agc) or (np.isfinite(z[1]) and -z[1] > g.agc)
        sus = ((u1 > g.u and s1 < g.spread) or (u5 > g.u and s5 < g.spread) or (np.isfinite(lost1) and lost1 > g.lost)
               or (agc_hit and cn0_hit) or bool(spoof_raw[t]))
        # Handling gate: the phone was just pocketed, mounted or carried into a vehicle. Its
        # placement changed, so the baselines re-settle quickly instead of freezing.
        settling = t < adapt_until
        row[col["settling"]] = float(settling)
        frozen = sus and not settling and freeze_run < g.max_freeze_s and t >= g.warmup_s
        freeze_run = freeze_run + 1 if frozen else 0
        row[col["frozen"]] = float(frozen)
        if not frozen:
            cnt = np.where(trk, np.minimum(cnt + 1, 1e6), cnt)
            alpha = np.maximum(1.0 / np.maximum(cnt, 1.0), a_fast if settling else a_off)
            off = np.where(trk, off + alpha * (r - off), off)
            pres = pres + a_p * (trk - pres) if t >= 45 else np.where(trk, np.maximum(pres, (t + 1) / 45.0), pres * 0.9)
            for b in (UPPER, LOWER):
                if agc_ok[b] and np.isfinite(ms.agc[t, b]):
                    agc_base[b] += (a_fast if settling else a_agc) * (ms.agc[t, b] - agc_base[b])

    out[:, IDX["has_agc_u"]] = float(agc_ok[UPPER])
    out[:, IDX["has_agc_l"]] = float(agc_ok[LOWER])
    out[:, IDX["has_dual"]] = has_dual
    out[: g.warmup_s, IDX["frozen"]] = 0.0
    return Frame(out, {"warmup_s": g.warmup_s})
