"""The complete on-device detector: features in, typed events with reason codes out."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .features import IDX, Gates
from .fusion import EventRule, Logit, evidence, events_from_prob

REASON = {  # evidence term -> reason code (DESIGN.md 5.2, 5.3)
    "drop1": "CN0_DROP", "u1": "CN0_DROP_UNIFORM", "lost1": "SATS_LOST", "agc_u": "AGC_DROP", "drop5": "CN0_DROP_L5",
    "u5": "CN0_DROP_UNIFORM_L5", "lost5": "SATS_LOST_L5", "agc_l": "AGC_DROP_L5", "absu": "CN0_BELOW_DEVICE_NORM",
    "lostlb": "SATS_LOST", "agc_and_loss": "AGC_DROP", "flat": "CN0_UNIFORM", "slope": "CN0_UNIFORM",
    "cm": "CN0_COMMON_MODE", "rise": "CN0_RISE", "clk": "CLOCK_STEP", "drift": "CLOCK_DRIFT", "xpos": "XCONST_DISAGREE",
    "xclk": "XCONST_CLOCK", "xvel": "XCONST_DOPPLER", "grpfail": "RESIDUALS", "nloc": "NETLOC_MISMATCH",
    "jump": "POS_JUMP", "sm": "DOPPLER_IMU", "am": "DOPPLER_IMU", "fm": "DOPPLER_IMU", "alm": "ALMANAC_SKY",
    "elmis": "ALMANAC_SKY", "agc_mismatch": "AGC_CN0_MISMATCH", "flat_cm": "CN0_COMMON_MODE",
    "drop_tight": "CN0_DROP_UNIFORM", "diff_g1": "BAND_SELECTIVE", "diff_b1": "BAND_SELECTIVE",
    "diff_l5": "BAND_SELECTIVE", "sel_g1": "BAND_SELECTIVE", "sel_l5": "BAND_SELECTIVE",
    "flat_t": "CN0_UNIFORM", "flat_tt": "CN0_UNIFORM",
    "zsel_g1": "BAND_SELECTIVE", "zsel_b1": "BAND_SELECTIVE", "zsel_l5": "BAND_SELECTIVE",
    "zsel_tight": "BAND_SELECTIVE", "selloss_g1": "BAND_SELECTIVE_LOSS", "selloss_l5": "BAND_SELECTIVE_LOSS",
    "agc_step": "AGC_DROP", "agc_step_drop": "AGC_DROP",
}
PROFILES = ("agc", "noagc")       # the jamming model is fitted separately for each (DESIGN.md 5.5)


def profile_of(x: np.ndarray) -> str:
    return "agc" if np.nanmax(x[:, IDX["has_agc_u"]]) > 0 else "noagc"


@dataclass
class DetectorConfig:
    gates: Gates
    norm: dict
    jam: dict                      # profile -> Logit
    spoof: Logit
    jam_rule: dict = field(default_factory=lambda: {p: EventRule() for p in PROFILES})
    spoof_rule: EventRule = field(default_factory=EventRule)
    meacon: Logit | None = None
    loss_min_s: int = 10
    warmup_s: int = 90
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"schema": 1, "evidence": "replay", "gates": self.gates.to_dict(),
                "norm": {k: list(v) for k, v in self.norm.items()},
                "jam": {k: v.to_dict() for k, v in self.jam.items()},
                "spoof": self.spoof.to_dict(), "jam_rule": {k: v.to_dict() for k, v in self.jam_rule.items()},
                "spoof_rule": self.spoof_rule.to_dict(),
                "meacon": self.meacon.to_dict() if self.meacon else None,
                "loss_min_s": self.loss_min_s, "warmup_s": self.warmup_s, "provenance": self.provenance}

    def save(self, path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), indent=1))

    @staticmethod
    def from_dict(d: dict) -> "DetectorConfig":
        return DetectorConfig(
            Gates.from_dict(d["gates"]), {k: tuple(v) for k, v in d["norm"].items()},
            {k: Logit.from_dict(v) for k, v in d["jam"].items()}, Logit.from_dict(d["spoof"]),
            {k: EventRule(**v) for k, v in d["jam_rule"].items()}, EventRule(**d["spoof_rule"]),
            Logit.from_dict(d["meacon"]) if d.get("meacon") else None, d.get("loss_min_s", 10), d.get("warmup_s", 90),
            d.get("provenance", {}))

    @staticmethod
    def load(path) -> "DetectorConfig":
        return DetectorConfig.from_dict(json.loads(Path(path).read_text()))


def probabilities(x: np.ndarray, cfg: DetectorConfig):
    e = evidence(x, cfg.norm)
    return cfg.jam[profile_of(x)].prob(e), cfg.spoof.prob(e), e


def _reasons(e: dict, model: Logit, a: int, b: int, top: int = 3) -> list:
    b = min(b, a + 45)
    contrib = {t: float(model.w[i] * np.mean(e[t][a:max(b, a + 1)])) for i, t in enumerate(model.terms) if t in REASON}
    out = []
    for t, v in sorted(contrib.items(), key=lambda kv: -kv[1]):
        if v > 0 and REASON[t] not in out:
            out.append(REASON[t])
    return out[:top]


def event_summary(e: dict, a: int, b: int, terms) -> np.ndarray:
    b = max(min(b, a + 60), a + 1)
    return np.array([float(np.max(e[t][a:b])) for t in terms])


def detect(x: np.ndarray, cfg: DetectorConfig, p=None) -> list:
    """Return events: dicts with type, start, end (epoch indices), score and reasons."""
    pj, ps, e = probabilities(x, cfg) if p is None else p
    prof = profile_of(x)
    spoof = events_from_prob(ps, cfg.spoof_rule, cfg.warmup_s)
    jam = events_from_prob(pj, cfg.jam_rule[prof], cfg.warmup_s)
    out = []
    for a, b, peak in spoof:
        kind = "spoof"
        if cfg.meacon is not None:
            s = event_summary(e, a, b, cfg.meacon.terms)
            kind = "meacon" if float(s @ cfg.meacon.w + cfg.meacon.b) > 0 else "spoof"
        out.append({"type": kind, "start": int(a), "end": int(b), "score": peak, "reasons": _reasons(e, cfg.spoof, a, b)})
    for a, b, peak in jam:
        # Interference that comes with spoofing evidence is reported once, as spoofing.
        if any(min(b, sb) - max(a, sa) > 0.5 * (b - a) or (sa - 15 <= a <= sb) for sa, sb, _ in spoof):
            continue
        drop5 = float(np.nanmean(e["drop5"][a:max(min(b, a + 45), a + 1)]))
        reasons = _reasons(e, cfg.jam[prof], a, b)
        if np.any(x[a:max(b, a + 1), IDX["has_dual"]] > 0):
            reasons.append("BAND_ALL" if drop5 > 1.0 else "BAND_L1_ONLY")
        out.append({"type": "jam", "start": int(a), "end": int(b), "score": peak, "reasons": reasons})
    # Total loss with no evidence of added power is ambiguous on one device (DESIGN.md 5.2 and 6).
    lost = np.nan_to_num(x[:, IDX["lost_l1"]]) >= 0.9
    lost[: cfg.warmup_s] = False
    t, n = 0, len(lost)
    while t < n:
        if not lost[t]:
            t += 1
            continue
        u = t
        while u < n and lost[u]:
            u += 1
        if u - t >= cfg.loss_min_s and not any(ev["start"] - 20 <= u and t <= ev["end"] + 5 for ev in out):
            out.append({"type": "loss_unknown", "start": int(t + cfg.loss_min_s), "end": int(u), "score": 0.2,
                        "reasons": ["SATS_LOST_NO_POWER_EVIDENCE"]})
        t = u
    return sorted(out, key=lambda ev: ev["start"])
