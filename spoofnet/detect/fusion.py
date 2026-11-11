"""Evidence terms, logistic fusion and the event state machine (DESIGN.md 5.5, 5.6).

The form of each evidence term comes from the physics in DESIGN.md section 5.
Every number (normalisation levels, weights, thresholds) is fitted on replay
data by experiments/calibrate.py and stored in config/detector.json.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from .features import IDX, _rolling, latch

# (evidence name, feature, direction). +1: high is suspicious; -1: low is suspicious.
_NORMED = (
    ("drop1", "drop_l1", 1), ("u1", "_u1", 1), ("lost1", "lost_l1", 1), ("agc_u", "_nagc_u", 1),
    ("drop5", "drop_l5", 1), ("u5", "_u5", 1), ("lost5", "lost_l5", 1), ("agc_l", "_nagc_l", 1),
    ("absu", "_absu", 1), ("lostlb", "_lostlb", 1),
    ("diff_g1", "_diff_g1", 1), ("diff_b1", "_diff_b1", 1), ("diff_l5", "_diff_l5", 1),
    ("zsel_g1", "_zsel_g1", 1), ("zsel_b1", "_zsel_b1", 1), ("zsel_l5", "_zsel_l5", 1), ("eldiff", "_eldiff", 1),
    ("selloss_g1", "_selloss_g1", 1), ("selloss_l5", "_selloss_l5", 1), ("agc_step", "_agc_step", 1),
    ("flat", "flat_min", -1), ("slope", "slope_min", -1), ("cm", "cm_max", 1), ("rise", "_rise", 1),
    ("flat_t", "flat_t", 1), ("flat_tt", "flat_tt", 1),
    ("clk", "_clk", 1), ("drift", "_drift", 1), ("xpos", "xpos", 1), ("xclk", "xclk", 1), ("xvel", "xvel", 1),
    ("grpfail", "grp_fail", 1), ("nloc", "nloc", 1), ("jump", "_jump", 1),
    ("sm", "imu_sm", 1), ("am", "_am", 1), ("fm", "imu_fm", 1), ("alm", "alm_below", 1), ("elmis", "alm_elmis", 1),
)
JAM_TERMS = {
    # Phones with working AGC: added power shows directly.
    "agc": ("drop1", "u1", "drop_tight", "lost1", "agc_u", "drop5", "u5", "lost5", "agc_l", "lostlb", "drop_noagc",
            "agc_and_loss", "handling", "handling_drop", "zsel_g1", "zsel_b1", "zsel_l5", "selloss_g1", "selloss_l5",
            "agc_step", "agc_step_drop", "eldiff_drop", "has_dual", "rise"),
    # Phones without: only what obstruction cannot imitate. Total loss is left out on purpose,
    # it is reported as loss_unknown (DESIGN.md 5.2).
    "noagc": ("drop1", "u1", "drop_tight", "drop5", "u5", "handling", "handling_drop", "settling_drop",
              "zsel_g1", "zsel_b1", "zsel_l5", "zsel_tight", "selloss_g1", "selloss_l5", "eldiff_drop", "has_dual",
              "rise"),
}
# The three Doppler-against-IMU terms (sm, am, fm) are computed and logged but are not part of
# the score. On the two real logs with usable sensor data they sat at 9 to 12 times the
# simulated 99th percentile with no interference present: a phone resting in a vehicle is
# "still" to an accelerometer, and sustained acceleration leaks into the gravity estimate.
SPOOF_TERMS = ("flat", "slope", "flat_t", "flat_tt", "cm", "rise", "clk", "drift", "xpos", "xclk", "xvel", "grpfail", "nloc", "jump",
               "alm", "elmis", "agc_mismatch", "flat_cm", "handling", "has_net", "has_dual",
               "u1", "lost1")


def derived(x: np.ndarray) -> dict:
    """Raw quantities that are functions of several features, before normalisation."""
    c = lambda n: x[:, IDX[n]]
    with np.errstate(invalid="ignore"):
        d = {
            "_u1": c("drop_l1") / (c("spread_l1") + 1.0),
            "_u5": c("drop_l5") / (c("spread_l5") + 1.0),
            "_nagc_u": -c("zagc_u"), "_nagc_l": -c("zagc_l"),
            "_absu": c("absdef_l1") / (c("absspread_l1") + 1.5),
            "_lostlb": c("droplb_l1") * np.nan_to_num(c("lost_l1")),
            # Obstruction is flat across neighbouring carriers; a band-limited source is not.
            "_diff_g1": c("drop_l1") - c("drop_g1"), "_diff_b1": c("drop_l1") - c("drop_b1"),
            "_diff_l5": c("drop_l1") - c("drop_l5"),
            "_eldiff": np.abs(c("drop_hi") - c("drop_lo")),
            "_rise": np.fmax(-c("drop_g"), -c("drop_e")),
            "_clk": latch(c("clk_step"), 45.0), "_drift": latch(c("drift_step"), 45.0),
            "_jump": latch(c("jump"), 45.0), "_am": latch(c("imu_am"), 30.0),
        }
    # Band selectivity as a two-sample statistic: difference of medians over its standard error.
    def zsel(spread_b, n_b, drop_b):
        se1 = 1.2533 * c("spread_l1") / np.sqrt(np.maximum(c("n_l1"), 1.0))
        se2 = 1.2533 * spread_b / np.sqrt(np.maximum(n_b, 1.0))
        with np.errstate(invalid="ignore"):
            return (c("drop_l1") - drop_b) / np.sqrt(se1**2 + se2**2 + 0.3**2)
    # Share of GPS and Galileo L1 signals lost, beyond the share lost on another carrier.
    d["_selloss_g1"] = c("lost_l1") - c("lost_g1")
    d["_selloss_l5"] = c("lost_l1") - c("lost_l5")
    # AGC step: the fall against its own level 15 to 60 s earlier, held for half a minute. A slow
    # baseline cannot see a 3 dB step inside a phone's normal AGC wander; this can.
    steps = []
    for name in ("zagc_u", "zagc_l"):
        z = c(name)
        ref = np.roll(_rolling(z, 45, np.nanmedian), 15)
        ref[:15] = np.nan
        steps.append(ref - z)
    with np.errstate(invalid="ignore"):
        d["_agc_step"] = latch(np.fmax(steps[0], steps[1]), 30.0)
    d["_zsel_g1"] = zsel(c("spread_g1"), c("n_g1"), c("drop_g1"))
    d["_zsel_b1"] = zsel(c("spread_b1"), c("n_b1"), c("drop_b1"))
    d["_zsel_l5"] = zsel(c("spread_l5"), c("n_l5"), c("drop_l5"))
    return d


_SCALE_FLOOR = {"selloss_g1": 0.15, "selloss_l5": 0.15, "agc_step": 1.0}


def raw_tails(x: np.ndarray, norm: dict, mask: np.ndarray) -> dict:
    """99th-percentile deviation of each quantity from the simulated clean median, in raw
    units, over the masked epochs of one log. Used to compare real clean logs with the simulator."""
    d = derived(x)
    out = {}
    for name, feat, sign in _NORMED:
        v = (d[feat] if feat.startswith("_") else x[:, IDX[feat]])[mask]
        v = v[np.isfinite(v)]
        if v.size >= 100:
            out[name] = float(np.percentile(sign * (v - norm[name][0]), 99.0))
    return out


def fit_norm(frames: list, real_tails: dict | None = None) -> dict:
    """Median and tail level of each quantity over clean data. `frames` are (x, mask) pairs.
    `real_tails` (term -> raw tail measured on real clean logs) can only widen a tail: what
    counts as unusual has to cover real phones as well as simulated ones."""
    real_tails = real_tails or {}
    cols: dict = {name: [] for name, _, _ in _NORMED}
    for x, mask in frames:
        d = derived(x)
        for name, feat, _ in _NORMED:
            v = d[feat] if feat.startswith("_") else x[:, IDX[feat]]
            cols[name].append(v[mask])
    norm = {}
    for name, feat, sign in _NORMED:
        v = np.concatenate(cols[name])
        v = v[np.isfinite(v)]
        if v.size < 100:
            norm[name] = (0.0, 1.0)
            continue
        med = float(np.median(v))
        tail = float(np.percentile(v, 99.0 if sign > 0 else 1.0))
        norm[name] = (med, float(max(abs(tail - med), _SCALE_FLOOR.get(name, 1e-3), real_tails.get(name, 0.0))))
    spread = np.concatenate([x[:, IDX["spread_l1"]][mask] for x, mask in frames])
    spread = spread[np.isfinite(spread)]
    norm["_spread_ref"] = (float(np.percentile(spread, 75.0)) if spread.size else 2.5, 1.0)
    return norm


def evidence(x: np.ndarray, norm: dict) -> dict:
    """Normalised, clipped evidence terms. 1.0 is the 99th percentile of clean data."""
    d = derived(x)
    e = {}
    for name, feat, sign in _NORMED:
        v = d[feat] if feat.startswith("_") else x[:, IDX[feat]]
        med, scale = norm[name]
        e[name] = np.clip(np.nan_to_num(sign * (v - med) / scale, nan=0.0), -1.0, 12.0)
    c = lambda n: np.nan_to_num(x[:, IDX[n]])
    has_agc = c("has_agc_u")
    e["has_agc_u"], e["has_dual"], e["has_net"] = has_agc, c("has_dual"), c("has_net")
    e["handling"] = c("handling")
    pos = lambda v: np.clip(v, 0.0, None)
    # A C/N0 drop with working AGC that did not move: obstruction, not added power.
    e["drop_noagc"] = pos(e["drop1"]) * has_agc * (e["agc_u"] < 0.5)
    # A drop that is the same on every satellite, in absolute terms and not only relative to its size.
    tight = np.clip(1.0 - np.nan_to_num(x[:, IDX["spread_l1"]], nan=1e9) / norm["_spread_ref"][0], 0.0, 1.0)
    e["drop_tight"] = pos(e["drop1"]) * tight
    e["sel_g1"] = pos(e["diff_g1"]) * pos(e["u1"])
    e["sel_l5"] = pos(e["diff_l5"]) * pos(e["u1"])
    e["zsel_tight"] = np.maximum(pos(e["zsel_g1"]), pos(e["zsel_l5"])) * tight
    e["agc_step_drop"] = pos(e["agc_step"]) * pos(e["drop1"])
    e["eldiff_drop"] = pos(e["eldiff"]) * (e["drop1"] > 1.0)
    e["settling"] = c("settling")
    e["settling_drop"] = e["settling"] * pos(e["drop1"])
    e["agc_and_loss"] = pos(e["agc_u"]) * ((e["drop1"] > 1.0) | (e["lost1"] > 1.0))
    e["handling_drop"] = e["handling"] * pos(e["drop1"])
    # More power in band while some constellation's C/N0 did not fall.
    with np.errstate(invalid="ignore"):
        not_down = (np.fmin(x[:, IDX["drop_g"]], x[:, IDX["drop_e"]]) < 2.0)
    e["agc_mismatch"] = pos(e["agc_u"]) * np.nan_to_num(not_down)
    e["flat_cm"] = pos(e["flat"]) * pos(e["cm"])
    return e


def design(e: dict, terms) -> np.ndarray:
    return np.stack([e[t] for t in terms], axis=1)


@dataclass
class Logit:
    terms: tuple
    w: np.ndarray
    b: float

    def prob(self, e: dict) -> np.ndarray:
        z = design(e, self.terms) @ self.w + self.b
        return 1.0 / (1.0 + np.exp(-np.clip(z, -40, 40)))

    def to_dict(self):
        return {"terms": list(self.terms), "w": [float(v) for v in self.w], "b": float(self.b)}

    @staticmethod
    def from_dict(d):
        return Logit(tuple(d["terms"]), np.array(d["w"]), float(d["b"]))


def fit_logit(xm: np.ndarray, y: np.ndarray, terms, l2: float = 1e-2, sample_w=None) -> Logit:
    """L2-regularised logistic regression with balanced classes."""
    y = y.astype(float)
    sw = np.ones_like(y) if sample_w is None else sample_w.astype(float)
    sw = sw * np.where(y > 0.5, 0.5 / max(sw[y > 0.5].sum(), 1e-9), 0.5 / max(sw[y <= 0.5].sum(), 1e-9))

    def loss(p):
        z = xm @ p[:-1] + p[-1]
        ll = np.logaddexp(0.0, z) - y * z
        g = 1.0 / (1.0 + np.exp(-z)) - y
        return (sw * ll).sum() + 0.5 * l2 * (p[:-1] ** 2).sum(), np.concatenate([xm.T @ (sw * g) + l2 * p[:-1], [(sw * g).sum()]])

    r = minimize(loss, np.zeros(xm.shape[1] + 1), jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return Logit(tuple(terms), r.x[:-1], float(r.x[-1]))


@dataclass
class EventRule:
    p_on: float = 0.9
    k_on: int = 4
    m_on: int = 6
    p_off: float = 0.5
    t_off: int = 10
    merge_s: int = 30

    def to_dict(self):
        return dict(self.__dict__)


def events_from_prob(p: np.ndarray, rule: EventRule, warmup: int = 90) -> list:
    """Return [(start, end, peak)] with `start` the epoch at which the event opened."""
    n = p.shape[0]
    above = (p >= rule.p_on).astype(int)
    above[:warmup] = 0
    csum = np.concatenate([[0], np.cumsum(above)])
    win = csum[1:] - csum[np.maximum(np.arange(1, n + 1) - rule.m_on, 0)]
    trigger = (win >= rule.k_on) & (above == 1)     # opens on a sample that is itself above the threshold
    below = p < rule.p_off
    out, t = [], 0
    while t < n:
        if not trigger[t]:
            t += 1
            continue
        start, run, end = t, 0, n
        u = t
        while u < n:
            run = run + 1 if below[u] else 0
            if run >= rule.t_off:
                end = u - rule.t_off + 1
                break
            u += 1
        out.append([start, end, float(np.max(p[start:max(end, start + 1)]))])
        t = u + 1 if u < n else n                    # resume after the quiet period that closed the event
    merged = []
    for ev in out:
        if merged and ev[0] - merged[-1][1] <= rule.merge_s:
            merged[-1][1] = ev[1]
            merged[-1][2] = max(merged[-1][2], ev[2])
        else:
            merged.append(ev)
    return [tuple(m) for m in merged]
