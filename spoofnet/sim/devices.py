"""Receiver models. Archetypes are generic on purpose: the public device matrix
only lists phones for which a real capability report exists.

Signal levels, the elevation trend, second-to-second C/N0 jitter and slow AGC
wander are set from five public real-phone logs (Zenodo 14712684: four phone
models on foot, bike, bus, ferry and in flight). Measured there: zenith C/N0 of
33 to 40 dB-Hz, 2.5 to 8 dB between zenith and horizon, 1.7 to 2.9 dB standard
deviation of the one-second C/N0 change while moving, and AGC wandering by 1.4
to 7 dB within a session. The first version of this file assumed a much cleaner
phone (see REPORT.md)."""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np


@dataclass
class DeviceModel:
    name: str
    cn0_zen: float          # dB-Hz at zenith, upper band
    cn0_slope: float        # dB lost between zenith and horizon
    l5_offset: float        # dB added for lower-band signals
    cn0_noise: float        # dB, per-signal AR(1) sigma (slow part)
    cn0_fast: float         # dB, per-signal white jitter while moving (fading)
    agc_slow: float         # dB, slow AGC wander within a session
    cn0_quant: float        # dB reporting step
    has_agc: bool
    agc_stuck: bool         # AGC field present but constant
    agc_noise: float        # dB
    agc_quant: float        # dB
    agc_drift: float        # dB per hour, slow thermal wander
    fe_bw_hz: float         # front-end noise bandwidth
    dual: bool
    consts: str
    tcxo_sigma: float       # clock drift random walk, m/s per sqrt(s)
    duty_cycle: bool        # receiver power-cycles and resets its hardware clock
    track_thr: float        # dB-Hz
    acq_margin: float       # dB above track_thr needed to (re)acquire
    acq_delay: int          # s
    code_s40: float         # m, code noise at 40 dB-Hz

    @property
    def agc_works(self) -> bool:
        return self.has_agc and not self.agc_stuck

    @property
    def tier(self) -> str:
        if self.agc_works and self.dual:
            return "A"
        if self.agc_works or self.dual:
            return "B"
        return "C"

    def to_dict(self) -> dict:
        return asdict(self)


_ARCHETYPES = {
    # name: (weight, base parameters)
    "flagship_dual_agc": (0.25, dict(cn0_zen=40.5, cn0_slope=6.5, has_agc=True, dual=True, consts="GERC",
                                      cn0_quant=0.1, agc_noise=0.35, agc_quant=0.1, fe_bw_hz=8e6, tcxo_sigma=0.02)),
    "mid_dual_noagc": (0.20, dict(cn0_zen=39.0, cn0_slope=6.0, has_agc=False, dual=True, consts="GERC",
                                   cn0_quant=0.1, agc_noise=0.0, agc_quant=0.1, fe_bw_hz=6e6, tcxo_sigma=0.03)),
    "mid_single_agc": (0.25, dict(cn0_zen=38.5, cn0_slope=6.0, has_agc=True, dual=False, consts="GERC",
                                   cn0_quant=0.1, agc_noise=0.8, agc_quant=0.5, fe_bw_hz=4e6, tcxo_sigma=0.04)),
    "budget_single": (0.30, dict(cn0_zen=37.0, cn0_slope=5.5, has_agc=False, dual=False, consts="GRC",
                                  cn0_quant=1.0, agc_noise=0.0, agc_quant=1.0, fe_bw_hz=3e6, tcxo_sigma=0.05)),
}


def sample_device(rng: np.random.Generator, archetype: str | None = None, wide: bool = False) -> DeviceModel:
    """Draw one device unit. `wide` stretches unit-to-unit spread for held-out tests."""
    names = list(_ARCHETYPES)
    if archetype is None:
        w = np.array([_ARCHETYPES[n][0] for n in names])
        archetype = names[rng.choice(len(names), p=w / w.sum())]
    base = dict(_ARCHETYPES[archetype][1])
    k = 1.6 if wide else 1.0
    stuck = base["has_agc"] and rng.random() < (0.15 if not wide else 0.2)
    return DeviceModel(
        name=archetype,
        cn0_zen=base["cn0_zen"] + rng.normal(0, 1.2 * k),
        cn0_slope=float(np.clip(base["cn0_slope"] + rng.normal(0, 1.5 * k), 1.5, 12.0)),
        l5_offset=rng.normal(-2.5, 1.0 * k),
        cn0_noise=float(np.clip(rng.normal(1.0, 0.2 * k), 0.5, 2.0)),
        cn0_fast=float(rng.uniform(1.3, 2.1 * (1.15 if wide else 1.0))),
        agc_slow=float(rng.uniform(0.2, 1.5 * k)),
        cn0_quant=base["cn0_quant"],
        has_agc=base["has_agc"],
        agc_stuck=bool(stuck),
        agc_noise=float(base["agc_noise"] * np.clip(rng.normal(1.0, 0.25 * k), 0.5, 2.5)),
        agc_quant=base["agc_quant"],
        agc_drift=float(rng.normal(0, 0.6 * k)),
        fe_bw_hz=float(base["fe_bw_hz"] * rng.uniform(0.7, 1.4)),
        dual=base["dual"],
        consts=base["consts"],
        tcxo_sigma=float(base["tcxo_sigma"] * rng.uniform(0.6, 1.6 * k)),
        duty_cycle=bool(rng.random() < (0.15 if not wide else 0.25)),
        track_thr=float(rng.uniform(10.0, 21.0)),      # real logs: lowest reported C/N0 is 10 to 22 dB-Hz by chipset
        acq_margin=float(rng.uniform(2.0, 5.0)),
        acq_delay=int(rng.integers(2, 6)),
        code_s40=float(rng.uniform(2.0, 4.5)),
    )
