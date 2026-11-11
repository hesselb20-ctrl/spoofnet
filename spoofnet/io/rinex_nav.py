"""Broadcast ephemeris for recorded logs (RINEX 3 navigation files).

Recorded phone logs carry no satellite positions. This module reads a
broadcast-ephemeris file for the day of the log and gives every tracked signal
a satellite position, so the ephemeris-assisted checks can run on real data.

GPS, Galileo and BeiDou MEO/IGSO use the standard Kepler model of their interface
documents. GLONASS (state vectors) and BeiDou GEO are not implemented: their
signals keep working in every check that needs no satellite position.

`attach(ms, nav)` puts the measurements into the simple model the solver uses
(`pr = |sat - x| + b`): satellite position at transmit time, rotated for the
Earth's turn during signal flight, satellite clock removed, and a simple
troposphere term removed where elevation is known. The ionosphere is not
corrected; on L1 that leaves metres of elevation-dependent error.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..geo import C

WEEK_S = 604_800.0
_MU = {"G": 3.986005e14, "E": 3.986004418e14, "C": 3.986004418e14}
_OMEGA_E = {"G": 7.2921151467e-5, "E": 7.2921151467e-5, "C": 7.292115e-5}
_REL_F = -4.442807633e-10
_LINES = {"G": 7, "E": 7, "C": 7, "J": 7, "I": 7, "R": 3, "S": 3}
_SYS_INDEX = {"G": 0, "E": 1, "C": 3}           # index into "GERC"
BDT_OFFSET_S = 14.0


@dataclass
class Eph:
    sys: str
    prn: int
    toc: float        # seconds of week, in the system's own time scale
    af: tuple
    toe: float
    sqrt_a: float
    e: float
    m0: float
    dn: float
    omega: float
    omega0: float
    omega_dot: float
    i0: float
    idot: float
    cuc: float
    cus: float
    crc: float
    crs: float
    cic: float
    cis: float
    tgd: float
    health: float


def _num(s: str) -> float:
    s = s.strip().replace("D", "E").replace("d", "e")
    return float(s) if s else 0.0


def _tow(y, mo, d, h, mi, sec) -> float:
    """Seconds of GPS week for a calendar time (no leap seconds involved: system time)."""
    import datetime as dt
    t = dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec))
    return float((t - dt.datetime(1980, 1, 6)).total_seconds() % WEEK_S)


def read_nav(path) -> dict:
    """Return {(system letter, prn): [Eph, ...]} for GPS, Galileo and BeiDou."""
    out: dict = {}
    with open(path, "r", encoding="ascii", errors="replace") as fh:
        for line in fh:
            if "END OF HEADER" in line:
                break
        lines = fh.read().splitlines()
    i = 0
    while i < len(lines):
        head = lines[i]
        sys = head[:1]
        if sys not in _LINES or not head[1:3].strip().isdigit():
            i += 1
            continue
        body = lines[i + 1:i + 1 + _LINES[sys]]
        i += 1 + _LINES[sys]
        if sys not in _MU or len(body) < 6:
            continue
        try:
            prn = int(head[1:3])
            epoch = head[3:23].split()
            v = [[_num(b[4 + 19 * k:23 + 19 * k]) for k in range(4)] for b in body]
            af = (_num(head[23:42]), _num(head[42:61]), _num(head[61:80]))
        except (ValueError, IndexError):
            continue
        if sys == "C" and (prn <= 5 or prn >= 59):
            continue                                    # BeiDou GEO needs a different orbit rotation
        e = Eph(sys=sys, prn=prn, toc=_tow(*epoch), af=af, toe=v[2][0], sqrt_a=v[1][3], e=v[1][1], m0=v[0][3],
                dn=v[0][2], omega=v[3][2], omega0=v[2][2], omega_dot=v[3][3], i0=v[3][0], idot=v[4][0],
                cuc=v[1][0], cus=v[1][2], crc=v[3][1], crs=v[0][1], cic=v[2][1], cis=v[2][3],
                tgd=v[5][2], health=v[5][1])
        if e.sqrt_a < 1000.0:
            continue
        out.setdefault((sys, prn), []).append(e)
    return out


def _wrap(t):
    return (np.asarray(t, dtype=float) + WEEK_S / 2) % WEEK_S - WEEK_S / 2


def sat_state(e: Eph, t):
    """ECEF position (m) and clock offset (s) at system times `t` (seconds of week)."""
    t = np.asarray(t, dtype=float)
    mu, om_e = _MU[e.sys], _OMEGA_E[e.sys]
    a = e.sqrt_a**2
    tk = _wrap(t - e.toe)
    m = e.m0 + (np.sqrt(mu / a**3) + e.dn) * tk
    ecc = m.copy()
    for _ in range(10):
        ecc = m + e.e * np.sin(ecc)
    nu = np.arctan2(np.sqrt(1 - e.e**2) * np.sin(ecc), np.cos(ecc) - e.e)
    phi = nu + e.omega
    s2, c2 = np.sin(2 * phi), np.cos(2 * phi)
    u = phi + e.cus * s2 + e.cuc * c2
    r = a * (1 - e.e * np.cos(ecc)) + e.crs * s2 + e.crc * c2
    inc = e.i0 + e.idot * tk + e.cis * s2 + e.cic * c2
    om = e.omega0 + (e.omega_dot - om_e) * tk - om_e * e.toe
    xp, yp = r * np.cos(u), r * np.sin(u)
    pos = np.stack([xp * np.cos(om) - yp * np.cos(inc) * np.sin(om),
                    xp * np.sin(om) + yp * np.cos(inc) * np.cos(om), yp * np.sin(inc)], axis=-1)
    dtc = _wrap(t - e.toc)
    clk = e.af[0] + e.af[1] * dtc + e.af[2] * dtc**2 + _REL_F * e.e * e.sqrt_a * np.sin(ecc) - e.tgd
    return pos, clk


def _pick(ephs: list, t_mid: float) -> Eph:
    """The healthy record closest in time; any record if none is flagged healthy."""
    healthy = [e for e in ephs if e.health == 0.0] or ephs
    return min(healthy, key=lambda e: abs(float(_wrap(t_mid - e.toe))))


def attach(ms, nav: dict) -> dict:
    """Give `ms` satellite positions and velocities, and correct its pseudoranges in
    place for the satellite clock and (where elevation is known) the troposphere.
    Returns a small report. Signals without ephemeris keep NaN positions."""
    n, ns = ms.cn0.shape
    t_rx = np.asarray(ms.meta["t_rx_tow"], dtype=float)
    sats = sorted({(int(c), int(s)) for c, s in zip(ms.sig_const, ms.sig_svid)})
    index = {k: j for j, k in enumerate(sats)}
    ms.sig_sat = np.array([index[(int(c), int(s))] for c, s in zip(ms.sig_const, ms.sig_svid)])
    pos = np.full((n, len(sats), 3), np.nan)
    vel = np.full((n, len(sats), 3), np.nan)
    clk = np.full((n, len(sats)), np.nan)
    letters = {v: k for k, v in _SYS_INDEX.items()}
    used = 0
    for (c, prn), j in index.items():
        sys = letters.get(c)
        ephs = nav.get((sys, prn)) if sys else None
        if not ephs:
            continue
        cols = np.flatnonzero(ms.sig_sat == j)
        with np.errstate(all="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                tau = np.nanmedian(ms.pr[:, cols], axis=1) / C
        tau = np.where(np.isfinite(tau), tau, 0.075)
        offset = BDT_OFFSET_S if sys == "C" else 0.0
        t_tx = t_rx - tau - offset
        e = _pick(ephs, float(np.nanmedian(t_tx)))
        if abs(float(_wrap(np.nanmedian(t_tx) - e.toe))) > 4 * 3600:
            continue                                    # no ephemeris close enough in time
        # The raw pseudorange contains the satellite clock offset (up to a millisecond), which
        # would misplace the transmit time. Remove it and recompute once.
        _, dts0 = sat_state(e, t_tx)
        tau = tau + dts0
        t_tx = t_rx - tau - offset
        p, dts = sat_state(e, t_tx)
        p2, _ = sat_state(e, t_tx + 0.5)
        p1, _ = sat_state(e, t_tx - 0.5)

        def rotate(xyz):                                # Earth turned by omega * tau during flight
            th = _OMEGA_E[sys] * tau
            co, si = np.cos(th), np.sin(th)
            return np.stack([co * xyz[:, 0] + si * xyz[:, 1], -si * xyz[:, 0] + co * xyz[:, 1], xyz[:, 2]], axis=1)

        pos[:, j], vel[:, j], clk[:, j] = rotate(p), rotate(p2) - rotate(p1), dts
        used += 1
    ms.sat_pos, ms.sat_vel = pos, vel
    corr = np.nan_to_num(C * clk[:, ms.sig_sat])        # no ephemeris: left as measured, unused by the solver
    el = np.where(np.isfinite(ms.el), ms.el, 30.0)
    tropo = 2.3 / np.sin(np.radians(np.clip(el, 5.0, 90.0)))
    ms.pr = ms.pr + corr - tropo
    # A satellite clock drifts too slowly to matter for Doppler: no pseudorange-rate correction.
    return {"satellites": len(sats), "with_ephemeris": used,
            "signals_with_position": int(np.isfinite(pos[0][ms.sig_sat][:, 0]).sum())}
