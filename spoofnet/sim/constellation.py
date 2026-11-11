"""Nominal GNSS constellations as circular Kepler orbits.

This is an almanac-grade model: geometry, visibility, elevation and Doppler
statistics are right; metre-level orbit accuracy is not attempted and nothing
here needs it, because the simulator and the solver share the same model.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..geo import MU, OMEGA_E

# name: (semi-major axis m, inclination deg, planes, satellites per plane, phasing F, L5 share)
_WALKER = {
    "G": (26_559_700.0, 55.0, 6, (6, 5, 5, 5, 5, 5), 1, 0.6),
    "E": (29_600_318.0, 56.0, 3, (8, 8, 8), 1, 1.0),
    "R": (25_508_000.0, 64.8, 3, (8, 8, 8), 1, 0.0),
    "C": (27_906_100.0, 55.0, 3, (8, 8, 8), 1, 1.0),
}


@dataclass(frozen=True)
class Constellation:
    const: np.ndarray     # (S,) index into "GERC"
    svid: np.ndarray      # (S,)
    a: np.ndarray         # (S,) m
    inc: np.ndarray       # (S,) rad
    raan0: np.ndarray     # (S,) rad, ECEF-referenced at t = 0
    u0: np.ndarray        # (S,) rad, argument of latitude at t = 0
    has_l5: np.ndarray    # (S,) bool

    def to_dict(self) -> dict:
        return {k: getattr(self, k).tolist() for k in ("const", "svid", "a", "inc", "raan0", "u0", "has_l5")}

    @staticmethod
    def from_dict(d: dict) -> "Constellation":
        return Constellation(
            np.array(d["const"], dtype=int), np.array(d["svid"], dtype=int), np.array(d["a"], dtype=float),
            np.array(d["inc"], dtype=float), np.array(d["raan0"], dtype=float), np.array(d["u0"], dtype=float),
            np.array(d["has_l5"], dtype=bool))

    def states(self, t_gps):
        """ECEF position and velocity at GPS times `t_gps` (T,). Returns (T, S, 3) twice."""
        t = np.asarray(t_gps, dtype=float)[:, None]
        n = np.sqrt(MU / self.a**3)[None, :]
        u = self.u0[None, :] + n * t
        om = self.raan0[None, :] - OMEGA_E * t           # node in the rotating frame
        ci, si = np.cos(self.inc)[None, :], np.sin(self.inc)[None, :]
        a = self.a[None, :]
        xp, yp = a * np.cos(u), a * np.sin(u)
        vxp, vyp = -a * n * np.sin(u), a * n * np.cos(u)
        co, so = np.cos(om), np.sin(om)
        x = xp * co - yp * ci * so
        y = xp * so + yp * ci * co
        z = yp * si
        vx = vxp * co - vyp * ci * so + OMEGA_E * y
        vy = vxp * so + vyp * ci * co - OMEGA_E * x
        vz = vyp * si
        return np.stack([x, y, z], -1), np.stack([vx, vy, vz], -1)


def build_constellation(seed: int = 7) -> Constellation:
    """All four constellations. `seed` only perturbs slot phases so planes are not perfectly regular."""
    rng = np.random.default_rng(seed)
    const, svid, a, inc, raan, u0, l5 = [], [], [], [], [], [], []
    for ci, name in enumerate("GERC"):
        sma, incd, planes, per_plane, f, l5_share = _WALKER[name]
        total = sum(per_plane)
        k = 0
        base = rng.uniform(0, 2 * np.pi)
        for p in range(planes):
            for s in range(per_plane[p]):
                k += 1
                const.append(ci)
                svid.append(k)
                a.append(sma)
                inc.append(np.radians(incd))
                raan.append(base + 2 * np.pi * p / planes)
                u0.append(2 * np.pi * s / per_plane[p] + 2 * np.pi * f * p / total + rng.normal(0, 0.05))
                l5.append(rng.random() < l5_share)
    return Constellation(np.array(const), np.array(svid), np.array(a), np.array(inc),
                         np.array(raan), np.array(u0), np.array(l5))
