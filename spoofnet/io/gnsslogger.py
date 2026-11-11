"""Reader and writer for GnssLogger-compatible raw logs (DESIGN.md 3.1).

The reader is header-driven: it maps columns by the names in each `# Type,...`
header line, so files from the SpoofNet app, from Google GnssLogger and from
public datasets in the same format all load, whatever their column order.

Pseudoranges are rebuilt from the clock and received-time fields the way
Google's GNSS analysis tools do it, with the first epoch's clock bias held so
the receiver clock stays continuous.

    python -m spoofnet.io.gnsslogger --capability <log>     print the SnCap report
    python -m spoofnet.io.gnsslogger --summary <log>        print what the log contains
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from ..data import LOWER, SUBBANDS, UPPER, MeasurementSet
from ..geo import C, ecef_to_lla, enu_basis, lla_to_ecef

WEEK_NS = 604_800 * 10**9
DAY_NS = 86_400 * 10**9
GPS_UNIX_OFFSET_S = 315_964_800
LEAP_S = 18
# Android GnssStatus constellation codes <-> index into "GERC"
ANDROID_CONST = {1: 0, 6: 1, 3: 2, 5: 3}
CONST_ANDROID = {v: k for k, v in ANDROID_CONST.items()}
SUB_FREQ = {"L1": 1575.42e6, "B1": 1561.098e6, "G1": 1602.0e6, "L5": 1176.45e6}
STATE_TOW_OK = 8 | 16384
STATE_GLO_TOD_OK = 128 | 32768
STATE_GPS_LIKE = 1 | 2 | 4 | 8 | 16384
STATE_GLO = 1 | 2 | 64 | 128 | 32768

HEADERS = {
    "Raw": "utcTimeMillis,TimeNanos,LeapSecond,TimeUncertaintyNanos,FullBiasNanos,BiasNanos,BiasUncertaintyNanos,"
           "DriftNanosPerSecond,DriftUncertaintyNanosPerSecond,HardwareClockDiscontinuityCount,Svid,TimeOffsetNanos,"
           "State,ReceivedSvTimeNanos,ReceivedSvTimeUncertaintyNanos,Cn0DbHz,PseudorangeRateMetersPerSecond,"
           "PseudorangeRateUncertaintyMetersPerSecond,AccumulatedDeltaRangeState,AccumulatedDeltaRangeMeters,"
           "AccumulatedDeltaRangeUncertaintyMeters,CarrierFrequencyHz,CarrierCycles,CarrierPhase,"
           "CarrierPhaseUncertainty,MultipathIndicator,SnrInDb,ConstellationType,AgcDb,BasebandCn0DbHz,"
           "FullInterSignalBiasNanos,FullInterSignalBiasUncertaintyNanos,SatelliteInterSignalBiasNanos,"
           "SatelliteInterSignalBiasUncertaintyNanos,CodeType,ChipsetElapsedRealtimeNanos",
    "Fix": "Provider,LatitudeDegrees,LongitudeDegrees,AltitudeMeters,SpeedMps,AccuracyMeters,BearingDegrees,"
           "UnixTimeMillis,SpeedAccuracyMps,BearingAccuracyDegrees,elapsedRealtimeNanos,VerticalAccuracyMeters",
    "Status": "UnixTimeMillis,SignalCount,SignalIndex,ConstellationType,Svid,CarrierFrequencyHz,Cn0DbHz,"
              "AzimuthDegrees,ElevationDegrees,UsedInFix,HasAlmanacData,HasEphemerisData,BasebandCn0DbHz",
    "Agc": "utcTimeMillis,TimeNanos,LeapSecond,TimeUncertaintyNanos,FullBiasNanos,BiasNanos,BiasUncertaintyNanos,"
           "DriftNanosPerSecond,DriftUncertaintyNanosPerSecond,HardwareClockDiscontinuityCount,AgcDb,"
           "CarrierFrequencyHz,ConstellationType",
    "SnImu": "utcTimeMillis,elapsedRealtimeNanos,VibRmsMps2,AccHMps2,YawRateRadPerSec,TiltDeg,SampleCount",
}


def _sub_of(freq_hz: float) -> int | None:
    for i, name in enumerate(SUBBANDS):
        tol = 6e6 if name == "G1" else 2.5e6
        if abs(freq_hz - SUB_FREQ[name]) < tol:
            return i
    return None


def _num(v: float, fmt: str = "{:.3f}") -> str:
    return "" if v is None or not np.isfinite(v) else fmt.format(v)


# ------------------------------------------------------------------------------------------
# writer
# ------------------------------------------------------------------------------------------

def write_log(ms: MeasurementSet, path, almanac: dict | None = None, week: int = 2400) -> None:
    """Write a MeasurementSet as a GnssLogger-style text file. `almanac` (a
    Constellation.to_dict()) is stored in a comment so simulated logs replay with
    satellite positions; real logs get those from ephemeris instead."""
    n, ns = ms.cn0.shape
    gps0_ns = week * WEEK_NS + int(round(ms.t0_gps * 1e9))
    boot_ns = 10**12
    clock_m = ms.truth.get("clock_bias", np.zeros(n)) if ms.truth else np.zeros(n)
    rx_ns = [gps0_ns + int(round((ms.t[k] + clock_m[k] / C) * 1e9)) for k in range(n)]   # receiver's GPS time
    full_bias = boot_ns - rx_ns[0]
    lines = ["# SpoofNet log, GnssLogger-compatible", "# Version: sim 1"]
    lines += [f"# {k},{v}" for k, v in HEADERS.items()]
    if almanac is not None:
        lines.append("# SnAlm," + json.dumps({"t0_gps": ms.t0_gps, "week": week, "almanac": almanac}))
    lla_fix = ecef_to_lla(np.where(np.isfinite(ms.fix_ecef), ms.fix_ecef, 1.0))
    lla_net = ecef_to_lla(np.where(np.isfinite(ms.net_ecef), ms.net_ecef, 1.0))
    freq = np.array([SUB_FREQ[SUBBANDS[s]] for s in ms.sig_sub])
    prev_net = None
    for k in range(n):
        utc_ms = int(round((gps0_ns / 1e9 + ms.t[k] + GPS_UNIX_OFFSET_S - LEAP_S) * 1000))
        time_ns = rx_ns[k] + full_bias
        clock = f"{utc_ms},{time_ns},{LEAP_S},,{full_bias},0.0,,,,{int(ms.clk_disc[k])}"
        tow_ns = rx_ns[k] % WEEK_NS
        for i in np.flatnonzero(np.isfinite(ms.cn0[k]) & np.isfinite(ms.pr[k])):
            c = int(ms.sig_const[i])
            pr_ns = int(round(ms.pr[k, i] / C * 1e9))
            if c == 2:      # GLONASS: time of day, three hours ahead of UTC
                sv_ns, state = (tow_ns % DAY_NS + (3 * 3600 - LEAP_S) * 10**9) % DAY_NS - pr_ns, STATE_GLO
            elif c == 3:    # BeiDou time is 14 s behind GPS time
                sv_ns, state = tow_ns - 14 * 10**9 - pr_ns, STATE_GPS_LIKE
            else:
                sv_ns, state = tow_ns - pr_ns, STATE_GPS_LIKE
            agc = ms.agc[k, int(ms.sig_band[i])]
            lines.append(
                f"Raw,{clock},{int(ms.sig_svid[i])},0.0,{state},{sv_ns},,{ms.cn0[k, i]:.2f},{ms.prr[k, i]:.4f},,"
                f"0,,,{freq[i]:.1f},,,,0,,{CONST_ANDROID[c]},{_num(agc, '{:.2f}')},,,,,,,")
            lines.append(f"Status,{utc_ms},,,{CONST_ANDROID[c]},{int(ms.sig_svid[i])},{freq[i]:.1f},"
                         f"{ms.cn0[k, i]:.2f},{ms.az[k, i]:.2f},{ms.el[k, i]:.2f},1,1,1,")
        for b, f in ((UPPER, SUB_FREQ["L1"]), (LOWER, SUB_FREQ["L5"])):
            if np.isfinite(ms.agc[k, b]):
                lines.append(f"Agc,{clock},{ms.agc[k, b]:.2f},{f:.1f},1")
        if np.all(np.isfinite(ms.fix_ecef[k])):
            v_enu = enu_basis(lla_fix[0][k], lla_fix[1][k]) @ np.nan_to_num(ms.fix_vel[k])
            speed = float(np.hypot(v_enu[0], v_enu[1]))
            brg = float(np.degrees(np.arctan2(v_enu[0], v_enu[1])) % 360.0)
            lines.append(f"Fix,gps,{lla_fix[0][k]:.8f},{lla_fix[1][k]:.8f},{lla_fix[2][k]:.2f},{speed:.3f},"
                         f"{ms.fix_acc[k]:.2f},{brg:.2f},{utc_ms},,,,")
        if np.all(np.isfinite(ms.net_ecef[k])):
            key = (float(ms.net_ecef[k, 0]), float(ms.net_ecef[k, 1]))
            if key != prev_net:
                lines.append(f"Fix,network,{lla_net[0][k]:.8f},{lla_net[1][k]:.8f},{lla_net[2][k]:.2f},,"
                             f"{ms.net_acc[k]:.2f},,{utc_ms},,,,")
                prev_net = key
        lines.append(f"SnImu,{utc_ms},,{ms.imu_vib[k]:.5f},{ms.imu_acc_h[k]:.5f},{ms.imu_yaw[k]:.6f},"
                     f"{ms.imu_tilt[k]:.3f},50")
    Path(path).write_text("\n".join(lines) + "\n")


# ------------------------------------------------------------------------------------------
# reader
# ------------------------------------------------------------------------------------------

GAL_E1C_2ND_CODE = 2048
NET_HOLD_S = 120
MIN_IMU_HZ = 10
_RAW_INT = ("TimeNanos", "FullBiasNanos", "HardwareClockDiscontinuityCount", "Svid", "State", "ReceivedSvTimeNanos",
            "ConstellationType")
_RAW_FLT = ("utcTimeMillis", "BiasNanos", "TimeOffsetNanos", "Cn0DbHz", "PseudorangeRateMetersPerSecond",
            "CarrierFrequencyHz", "AgcDb")


def _to_int(v: str) -> int:
    """Exact integer parse. Nanosecond counts since 1980 exceed what a float holds
    exactly, and one lost bit there is tens of metres of pseudorange."""
    try:
        return int(v)
    except ValueError:
        try:
            return int(float(v))
        except ValueError:
            return 0


def _to_flt(v: str) -> float:
    try:
        return float(v)
    except ValueError:
        return float("nan")


def parse(path) -> dict:
    """One pass over a log. Numeric columns go straight into typed arrays, so a
    200 MB file with millions of sensor lines stays within a few hundred MB of memory."""
    from array import array
    cols: dict = {}
    raw_i = {k: array("q") for k in _RAW_INT}
    raw_f = {k: array("d") for k in _RAW_FLT}
    status = {k: array("d") for k in ("utc", "const", "svid", "freq", "az", "el")}
    agc = {k: array("d") for k in ("utc", "agc", "freq")}
    snimu = {k: array("d") for k in ("utc", "vib", "acc_h", "yaw", "tilt")}
    imu = {k: array("d") for k in ("UncalAccel", "Accel", "UncalGyro", "Gyro")}     # flat: utc, x, y, z, ...
    fixes: list = []
    extra: dict = {}
    cur_utc = float("nan")
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line[:1] == "#":
                body = line[1:].strip()
                kind, _, rest = body.partition(",")
                kind = kind.strip()
                if kind in ("SnAlm", "SnDuty"):
                    extra.setdefault(kind, []).append(rest)
                elif rest and " " not in kind:
                    cols[kind] = {c.strip(): i for i, c in enumerate(rest.split(","))}
                elif body.startswith("Version:"):
                    extra["header"] = body
                continue
            kind, _, rest = line.rstrip("\r\n").partition(",")
            ci = cols.get(kind)
            if kind == "SnCap":
                extra.setdefault("SnCap", []).append(rest)
                continue
            if ci is None:
                continue
            if kind in imu:
                p = rest.split(",", 5)
                if len(p) >= 5:
                    imu[kind].extend((_to_flt(p[0]), _to_flt(p[2]), _to_flt(p[3]), _to_flt(p[4])))
                continue
            if kind not in ("Raw", "Status", "Fix", "Agc", "SnImu"):
                continue
            p = rest.split(",")
            get = lambda name: p[ci[name]] if name in ci and ci[name] < len(p) else ""
            if kind == "Raw":
                for k in _RAW_INT:
                    raw_i[k].append(_to_int(get(k)))
                for k in _RAW_FLT:
                    raw_f[k].append(_to_flt(get(k)))
                if raw_f["utcTimeMillis"][-1] != raw_f["utcTimeMillis"][-1]:        # older logs: no UTC column
                    raw_f["utcTimeMillis"][-1] = _to_flt(get("ElapsedRealtimeMillis"))
                cur_utc = raw_f["utcTimeMillis"][-1]
            elif kind == "Status":
                t = _to_flt(get("UnixTimeMillis"))
                status["utc"].append(t if t == t else cur_utc)      # GnssLogger leaves this column empty
                for k, name in (("const", "ConstellationType"), ("svid", "Svid"), ("freq", "CarrierFrequencyHz"),
                                ("az", "AzimuthDegrees"), ("el", "ElevationDegrees")):
                    status[k].append(_to_flt(get(name)))
            elif kind == "Fix":
                fixes.append((get("Provider").lower(), _to_flt(get("LatitudeDegrees")), _to_flt(get("LongitudeDegrees")),
                              _to_flt(get("AltitudeMeters")), _to_flt(get("SpeedMps")), _to_flt(get("AccuracyMeters")),
                              _to_flt(get("BearingDegrees")), _to_flt(get("UnixTimeMillis"))))
            elif kind == "Agc":
                agc["utc"].append(_to_flt(get("utcTimeMillis")))
                agc["agc"].append(_to_flt(get("AgcDb")))
                agc["freq"].append(_to_flt(get("CarrierFrequencyHz")))
            else:
                for k, name in (("utc", "utcTimeMillis"), ("vib", "VibRmsMps2"), ("acc_h", "AccHMps2"),
                                ("yaw", "YawRateRadPerSec"), ("tilt", "TiltDeg")):
                    snimu[k].append(_to_flt(get(name)))
    out = {"raw": {**{k: np.frombuffer(v, dtype=np.int64) for k, v in raw_i.items()},
                   **{k: np.frombuffer(v, dtype=np.float64) for k, v in raw_f.items()}},
           "status": {k: np.frombuffer(v, dtype=np.float64) for k, v in status.items()},
           "agc": {k: np.frombuffer(v, dtype=np.float64) for k, v in agc.items()},
           "snimu": {k: np.frombuffer(v, dtype=np.float64) for k, v in snimu.items()},
           "imu": {k: np.frombuffer(v, dtype=np.float64).reshape(-1, 4) for k, v in imu.items()},
           "fixes": fixes, "extra": extra}
    return out


def _sub_index(freq: np.ndarray) -> np.ndarray:
    """Carrier group per measurement; -1 for carriers that are not used. A missing
    frequency means an old single-frequency phone, which is on L1."""
    f = np.where(np.isfinite(freq), freq, SUB_FREQ["L1"])
    out = np.full(f.shape, -1, dtype=int)
    for i, name in enumerate(SUBBANDS):
        tol = 6e6 if name == "G1" else 2.5e6
        out[np.abs(f - SUB_FREQ[name]) < tol] = i
    return out


def _const_index(c: np.ndarray) -> np.ndarray:
    out = np.full(c.shape, -1, dtype=int)
    for android, idx in ANDROID_CONST.items():
        out[c == android] = idx
    return out


def imu_summary(acc: np.ndarray, gyr: np.ndarray, utc0: float, n: int) -> dict:
    """The 1 Hz motion summary of DESIGN.md 5.1 from raw accelerometer and gyroscope
    samples (rows: utc ms, x, y, z). Mirrors ImuSummarizer.kt."""
    out = {k: np.full(n, np.nan) for k in ("vib", "acc_h", "yaw", "tilt")}
    if len(acc) < 10:
        return out
    k = np.rint((acc[:, 0] - utc0) / 1000.0).astype(int)
    ok = (k >= 0) & (k < n) & np.all(np.isfinite(acc[:, 1:]), axis=1)
    k, a = k[ok], acc[ok, 1:]
    cnt = np.bincount(k, minlength=n).astype(float)
    have = cnt > 0
    mean = np.stack([np.bincount(k, weights=a[:, j], minlength=n) for j in range(3)], axis=1) / np.maximum(cnt, 1)[:, None]
    mag = np.linalg.norm(a, axis=1)
    m1 = np.bincount(k, weights=mag, minlength=n) / np.maximum(cnt, 1)
    m2 = np.bincount(k, weights=mag**2, minlength=n) / np.maximum(cnt, 1)
    out["vib"] = np.where(have, np.sqrt(np.clip(m2 - m1**2, 0, None)), 0.0)
    # Gravity: low-pass of the per-second mean with a 2 s time constant.
    grav = np.zeros((n, 3))
    g = None
    alpha = 1.0 - np.exp(-1.0 / 2.0)
    for i in range(n):
        if have[i]:
            g = mean[i].copy() if g is None else g + alpha * (mean[i] - g)
        grav[i] = g if g is not None else (0.0, 0.0, 9.81)
    unit = grav / np.maximum(np.linalg.norm(grav, axis=1, keepdims=True), 1e-6)
    lin = mean - grav
    horiz = lin - np.sum(lin * unit, axis=1, keepdims=True) * unit
    out["acc_h"] = np.where(have, np.linalg.norm(horiz, axis=1), 0.0)
    cosang = np.clip(np.sum(unit[1:] * unit[:-1], axis=1), -1.0, 1.0)
    out["tilt"] = np.zeros(n)
    out["tilt"][1:] = np.degrees(np.arccos(cosang))
    out["yaw"] = np.zeros(n)
    if len(gyr) >= 10:
        kg = np.rint((gyr[:, 0] - utc0) / 1000.0).astype(int)
        okg = (kg >= 0) & (kg < n) & np.all(np.isfinite(gyr[:, 1:]), axis=1)
        kg, w = kg[okg], gyr[okg, 1:]
        cg = np.bincount(kg, minlength=n).astype(float)
        about_g = np.sum(w * unit[kg], axis=1)
        out["yaw"] = np.bincount(kg, weights=about_g, minlength=n) / np.maximum(cg, 1)
    # Vibration within a second needs several samples in it. Logs made with sensors at a low
    # rate would otherwise read as "perfectly still".
    enough = cnt >= MIN_IMU_HZ
    for name in out:
        out[name] = np.where(enough, out[name], np.nan)
    return out


def read_log(path) -> MeasurementSet:
    p = parse(path)
    raw, extra = p["raw"], p["extra"]
    if raw["TimeNanos"].size == 0:
        raise ValueError(f"{path}: no Raw records")
    utc_raw = raw["utcTimeMillis"]
    utc_first = float(utc_raw[0])
    k = np.rint((utc_raw - utc_first) / 1000.0).astype(int)
    k = np.clip(k, 0, None)
    n = int(k.max()) + 1
    const = _const_index(raw["ConstellationType"])
    sub = _sub_index(raw["CarrierFrequencyHz"])
    use = (const >= 0) & (sub >= 0)

    key = const * 100_000 + raw["Svid"] * 10 + sub
    uniq, inv = np.unique(key[use], return_inverse=True)
    ns = uniq.size
    sig_const = (uniq // 100_000).astype(int)
    sig_svid = ((uniq % 100_000) // 10).astype(int)
    sig_sub = (uniq % 10).astype(int)
    sig_band = np.where(sig_sub == SUBBANDS.index("L5"), LOWER, UPPER)

    # Pseudorange from receive and transmit times, with the first epoch's bias held (integer nanoseconds).
    bias0 = int(raw["FullBiasNanos"][0]) + int(round(float(np.nan_to_num(raw["BiasNanos"][0]))))
    rx_ns = raw["TimeNanos"] - bias0 + np.rint(np.nan_to_num(raw["TimeOffsetNanos"])).astype(np.int64)
    tow = rx_ns % WEEK_NS
    sv = raw["ReceivedSvTimeNanos"]
    state = raw["State"]
    d_gps = (tow - sv) % WEEK_NS
    d_bds = (tow - 14 * 10**9 - sv) % WEEK_NS
    d_glo = ((tow % DAY_NS + (3 * 3600 - LEAP_S) * 10**9) % DAY_NS - sv) % DAY_NS
    d_gal_100ms = (tow - sv) % (100 * 10**6)                 # E1C secondary code: range known modulo 100 ms
    tow_ok = (state & STATE_TOW_OK) != 0
    d_ns = np.where(const == 2, d_glo, np.where(const == 3, d_bds, d_gps))
    ok = np.where(const == 2, (state & STATE_GLO_TOD_OK) != 0, tow_ok)
    gal_alt = (const == 1) & ~tow_ok & ((state & GAL_E1C_2ND_CODE) != 0)
    d_ns = np.where(gal_alt, d_gal_100ms, d_ns)
    ok = ok | gal_alt
    rng = d_ns * 1e-9 * C
    ok = ok & use & (rng > 1.0e7) & (rng < 6.0e7) & np.isfinite(raw["Cn0DbHz"])

    cn0 = np.full((n, ns), np.nan)
    pr = np.full((n, ns), np.nan)
    prr = np.full((n, ns), np.nan)
    sig_of_row = np.full(key.shape, -1, dtype=int)
    sig_of_row[use] = inv
    rows = np.flatnonzero(ok)
    cn0[k[rows], sig_of_row[rows]] = raw["Cn0DbHz"][rows]
    pr[k[rows], sig_of_row[rows]] = rng[rows]
    prr[k[rows], sig_of_row[rows]] = raw["PseudorangeRateMetersPerSecond"][rows]

    agc = np.full((n, 2), np.nan)
    band_row = np.where(sub == SUBBANDS.index("L5"), LOWER, UPPER)
    a_ok = use & np.isfinite(raw["AgcDb"])
    for b in (UPPER, LOWER):
        m = a_ok & (band_row == b)
        if m.any():
            cnt = np.bincount(k[m], minlength=n)
            tot = np.bincount(k[m], weights=raw["AgcDb"][m], minlength=n)
            agc[:, b] = np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan)
    ag = p["agc"]
    if ag["utc"].size:                                        # Android 13+ per-band AGC wins when present
        ka = np.rint((ag["utc"] - utc_first) / 1000.0).astype(int)
        sa = _sub_index(ag["freq"])
        m = (ka >= 0) & (ka < n) & (sa >= 0) & np.isfinite(ag["agc"])
        agc[ka[m], np.where(sa[m] == SUBBANDS.index("L5"), LOWER, UPPER)] = ag["agc"][m]

    clk_disc = np.zeros(n, dtype=np.int64)
    np.maximum.at(clk_disc, k, raw["HardwareClockDiscontinuityCount"])
    seen = np.bincount(k, minlength=n) > 0
    clk_disc = np.maximum.accumulate(np.where(seen, clk_disc, 0))

    az = np.full((n, ns), np.nan)
    el = np.full((n, ns), np.nan)
    st = p["status"]
    if st["utc"].size:
        ks = np.rint((st["utc"] - utc_first) / 1000.0)
        cs = _const_index(st["const"])
        ss = _sub_index(st["freq"])
        m = np.isfinite(ks) & (ks >= 0) & (ks < n) & (cs >= 0) & (ss >= 0) & np.isfinite(st["svid"])
        skey = cs[m] * 100_000 + st["svid"][m].astype(np.int64) * 10 + ss[m]
        pos = np.searchsorted(uniq, skey)
        hit = (pos < ns) & (uniq[np.minimum(pos, ns - 1)] == skey)
        kk = ks[m].astype(int)[hit]
        az[kk, pos[hit]] = st["az"][m][hit]
        el[kk, pos[hit]] = st["el"][m][hit]
        # Elevation changes slowly: carry the last known value so every tracked epoch has one.
        for arr in (az, el):
            idx = np.maximum.accumulate(np.where(np.isfinite(arr), np.arange(n)[:, None], -1), axis=0)
            filled = np.take_along_axis(arr, np.maximum(idx, 0), axis=0)
            arr[:] = np.where(idx >= 0, filled, np.nan)

    fix = np.full((n, 3), np.nan)
    fix_vel = np.full((n, 3), np.nan)
    fix_acc = np.full(n, np.nan)
    net = np.full((n, 3), np.nan)
    net_acc = np.full(n, np.nan)
    for prov, lat, lon, alt, speed, acc_m, brg, t_ms in p["fixes"]:
        if not (np.isfinite(lat) and np.isfinite(lon) and np.isfinite(t_ms)):
            continue
        kf = int(round((t_ms - utc_first) / 1000.0))
        if not 0 <= kf < n:
            continue
        xyz = lla_to_ecef(lat, lon, alt if np.isfinite(alt) else 0.0)
        if prov in ("gps", "gnss"):
            fix[kf], fix_acc[kf] = xyz, acc_m
            sp_, br_ = (speed if np.isfinite(speed) else 0.0), np.radians(brg if np.isfinite(brg) else 0.0)
            fix_vel[kf] = np.array([sp_ * np.sin(br_), sp_ * np.cos(br_), 0.0]) @ enu_basis(lat, lon)
        elif prov in ("network", "nlp"):
            # Held until the next update, but not for ever: with the radios off (flight mode,
            # open sea) the last network position says nothing about where the phone is now.
            net[kf:kf + NET_HOLD_S], net_acc[kf:kf + NET_HOLD_S] = xyz, acc_m
            net[kf + NET_HOLD_S:], net_acc[kf + NET_HOLD_S:] = np.nan, np.nan

    sn = p["snimu"]
    if sn["utc"].size:
        imu = {name: np.zeros(n) for name in ("vib", "acc_h", "yaw", "tilt")}
        ki = np.rint((sn["utc"] - utc_first) / 1000.0).astype(int)
        m = (ki >= 0) & (ki < n)
        for name in imu:
            imu[name][ki[m]] = np.nan_to_num(sn[name][m])
        imu_source = "summary"
    else:
        acc = p["imu"]["UncalAccel"] if len(p["imu"]["UncalAccel"]) else p["imu"]["Accel"]
        gyr = p["imu"]["UncalGyro"] if len(p["imu"]["UncalGyro"]) else p["imu"]["Gyro"]
        imu = imu_summary(acc, gyr, utc_first, n)
        share = float(np.isfinite(imu["vib"]).mean())
        imu_source = "raw samples" if share > 0.5 else "none (too few sensor samples)"

    sat_pos = sat_vel = None
    sig_sat = np.zeros(ns, dtype=int)
    t0_gps = float((int(raw["TimeNanos"][0]) - bias0) % WEEK_NS) / 1e9
    usable_agc = bool(np.isfinite(agc[:, UPPER]).mean() > 0.5 and np.nanstd(agc[:, UPPER]) > 0)
    # Receiver time of week per epoch, for ephemeris look-up (gaps are interpolated).
    t_rx = np.full(n, np.nan)
    t_rx[k] = ((raw["TimeNanos"] - bias0) % WEEK_NS) / 1e9
    grid = np.arange(n, dtype=float)
    have = np.isfinite(t_rx)
    t_rx = np.where(have, t_rx, np.interp(grid, grid[have], t_rx[have]))
    meta = {"source": str(path), "has_agc": usable_agc, "dual": bool((sig_band == LOWER).sum() >= 4),
            "evidence": "replay", "imu_source": imu_source, "header": extra.get("header", ""),
            "duty_marks": extra.get("SnDuty", []), "t_rx_tow": t_rx,
            "gps_week": int((int(raw["TimeNanos"][0]) - bias0) // WEEK_NS)}
    if "SnAlm" in extra:
        from ..sim.constellation import Constellation
        alm = json.loads(extra["SnAlm"][0])
        con = Constellation.from_dict(alm["almanac"])
        t0_gps = float(alm["t0_gps"])
        sat_pos, sat_vel = con.states(t0_gps + np.arange(n, dtype=float))
        lookup = {(int(c), int(s)): j for j, (c, s) in enumerate(zip(con.const, con.svid))}
        sig_sat = np.array([lookup[(int(c), int(s))] for c, s in zip(sig_const, sig_svid)])
    if "SnCap" in extra:
        try:
            meta["capability"] = json.loads(extra["SnCap"][-1])
        except json.JSONDecodeError:
            pass
    return MeasurementSet(
        t=np.arange(n, dtype=float), t0_gps=t0_gps, sig_const=sig_const, sig_svid=sig_svid, sig_band=sig_band,
        sig_sub=sig_sub, sig_sat=sig_sat, cn0=cn0, pr=pr, prr=prr, az=az, el=el, agc=agc, clk_disc=clk_disc,
        fix_ecef=fix, fix_vel=fix_vel, fix_acc=fix_acc, net_ecef=net, net_acc=net_acc,
        imu_vib=imu["vib"], imu_acc_h=imu["acc_h"], imu_yaw=imu["yaw"], imu_tilt=imu["tilt"],
        sat_pos=sat_pos, sat_vel=sat_vel, meta=meta, truth={})


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] not in ("--capability", "--summary"):
        print(__doc__)
        return 2
    if argv[0] == "--capability":
        extra = parse(argv[1])["extra"]
        if "SnCap" not in extra:
            print("no SnCap line: the session was not stopped cleanly, or the log is not from the SpoofNet app")
            return 1
        print(json.dumps(json.loads(extra["SnCap"][-1]), indent=1))
        return 0
    ms = read_log(argv[1])
    trk = np.isfinite(ms.cn0)
    print(json.dumps({
        "epochs": ms.n_epochs, "signals": ms.n_signals,
        "constellations": sorted({"GERC"[c] for c in ms.sig_const}),
        "dual_frequency": ms.meta["dual"], "agc_usable": ms.meta["has_agc"],
        "median_tracked": float(np.median(trk.sum(axis=1))), "median_cn0": float(np.nanmedian(ms.cn0)),
        "epochs_with_fix": int(np.all(np.isfinite(ms.fix_ecef), axis=1).sum()),
        "epochs_with_network_position": int(np.all(np.isfinite(ms.net_ecef), axis=1).sum()),
        "clock_discontinuities": int(ms.clk_disc[-1] - ms.clk_disc[0]),
        "epochs_with_elevation": int(np.isfinite(ms.el).any(axis=1).sum()),
        "motion_summary_from": ms.meta["imu_source"], "logger": ms.meta["header"],
        "satellite_positions": ms.sat_pos is not None,
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
