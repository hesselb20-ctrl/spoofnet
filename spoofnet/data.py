"""The in-memory form of a raw measurement log.

One `MeasurementSet` holds one logging session resampled to 1 Hz. The
simulator produces it, the log reader produces it from recorded files, the
injection code modifies it and the detectors consume it. Arrays are indexed
`[epoch, signal]`. A signal is one (constellation, satellite, band) triple.
Untracked signals are NaN.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

CONSTS = "GERC"                     # GPS, Galileo, GLONASS, BeiDou
SUBBANDS = ("L1", "B1", "G1", "L5")  # carrier groups used for interference coupling
SUB_FREQ = {"L1": 1575.42e6, "B1": 1561.098e6, "G1": 1602.0e6, "L5": 1176.45e6}
UPPER, LOWER = 0, 1                 # front-end band index


@dataclass
class MeasurementSet:
    t: np.ndarray                   # (T,) seconds since the first epoch
    t0_gps: float                   # GPS seconds of the first epoch
    sig_const: np.ndarray           # (N,) index into CONSTS
    sig_svid: np.ndarray            # (N,)
    sig_band: np.ndarray            # (N,) UPPER or LOWER
    sig_sub: np.ndarray             # (N,) index into SUBBANDS
    sig_sat: np.ndarray             # (N,) index into the satellite axis of sat_pos
    cn0: np.ndarray                 # (T, N) dB-Hz
    pr: np.ndarray                  # (T, N) pseudorange, m
    prr: np.ndarray                 # (T, N) pseudorange rate, m/s
    az: np.ndarray                  # (T, N) degrees, as reported by the receiver
    el: np.ndarray                  # (T, N) degrees, as reported by the receiver
    agc: np.ndarray                 # (T, 2) dB per front-end band, NaN if absent
    clk_disc: np.ndarray            # (T,) hardware clock discontinuity counter
    fix_ecef: np.ndarray            # (T, 3) chipset fix, NaN if none
    fix_vel: np.ndarray             # (T, 3) chipset velocity (ECEF), NaN if none
    fix_acc: np.ndarray             # (T,) reported horizontal accuracy, m
    net_ecef: np.ndarray            # (T, 3) network-provider position, NaN if none
    net_acc: np.ndarray             # (T,) its reported accuracy, m
    imu_vib: np.ndarray             # (T,) m/s^2
    imu_acc_h: np.ndarray           # (T,) m/s^2
    imu_yaw: np.ndarray             # (T,) rad/s
    imu_tilt: np.ndarray            # (T,) degrees
    sat_pos: np.ndarray | None = None   # (T, S, 3) from almanac or ephemeris
    sat_vel: np.ndarray | None = None   # (T, S, 3)
    meta: dict = field(default_factory=dict)
    truth: dict = field(default_factory=dict)   # simulator ground truth, never read by detectors

    @property
    def n_epochs(self) -> int:
        return int(self.t.shape[0])

    @property
    def n_signals(self) -> int:
        return int(self.sig_const.shape[0])

    def copy(self) -> "MeasurementSet":
        kw = {}
        for k, v in self.__dict__.items():
            if isinstance(v, np.ndarray):
                kw[k] = v.copy()
            elif isinstance(v, dict):
                kw[k] = {a: (b.copy() if isinstance(b, np.ndarray) else b) for a, b in v.items()}
            else:
                kw[k] = v
        return MeasurementSet(**kw)

    def tracked(self) -> np.ndarray:
        return np.isfinite(self.cn0)


def code_sigma_m(cn0, band=UPPER, s40=3.0):
    """Nominal 1-sigma code noise for phone-grade tracking at 1 Hz."""
    s = s40 * 10.0 ** ((40.0 - np.asarray(cn0, dtype=float)) / 20.0)
    s = np.where(np.asarray(band) == LOWER, s * 0.4, s)
    return np.clip(s, 0.4, 80.0)


def doppler_sigma_mps(cn0):
    s = 0.08 * 10.0 ** ((40.0 - np.asarray(cn0, dtype=float)) / 20.0)
    return np.clip(s, 0.03, 4.0)
