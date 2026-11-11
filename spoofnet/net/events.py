"""The event and coverage records a device uploads (DESIGN.md 3.2, 3.3)."""
from __future__ import annotations

import re

import numpy as np

from ..detect.features import IDX
from ..geo import ecef_to_lla
from . import cells, privacy

TIER_WEIGHT = {"A": 1.0, "B": 0.7, "C": 0.4, "D": 0.15}
EVENT_TYPES = ("jam", "spoof", "meacon", "loss_unknown")
_TOKEN = re.compile(r"^[0-9a-f]{24}$")


def _trusted_position(ms, start: int):
    """Where the device believes it really is when the event opens: the last fix from
    before the event, else the network position. Never the fix taken during the event."""
    for k in range(max(start - 3, 0), max(start - 120, -1), -1):
        if np.all(np.isfinite(ms.fix_ecef[k])):
            return ms.fix_ecef[k], "last_trusted"
    k = min(start, ms.n_epochs - 1)
    if np.all(np.isfinite(ms.net_ecef[k])):
        return ms.net_ecef[k], "network"
    for k in range(min(start, ms.n_epochs - 1), -1, -1):
        if np.all(np.isfinite(ms.fix_ecef[k])):
            return ms.fix_ecef[k], "gnss"
    return None, None


def build_event(ms, x: np.ndarray, ev: dict, device_secret: bytes, unix0: float, event_res: int = privacy.EVENT_RES,
                agc_sigma=(np.nan, np.nan)) -> dict | None:
    """Turn one on-device detection into the record that is uploaded. Returns None when
    the device has no position to attach."""
    a, b = ev["start"], max(ev["end"], ev["start"] + 1)
    pos, src = _trusted_position(ms, a)
    if pos is None:
        return None
    lat, lon, _ = ecef_to_lla(pos)
    w = slice(a, min(b, a + 30))        # short, so a moving phone reports the loss near where it was
    col = lambda name: x[w, IDX[name]].astype(float)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            drop, spread = np.nanmedian(col("drop_l1")), np.nanmedian(col("spread_l1"))
            drop5 = np.nanmedian(col("drop_l5"))
            lost = np.nanmax(col("lost_l1")) if np.isfinite(col("lost_l1")).any() else np.nan
            lb = np.nanmax(col("droplb_l1")) if np.isfinite(col("droplb_l1")).any() else np.nan
            zagc = np.nanmedian(col("zagc_u"))
    before = x[max(a - 15, 0):max(a - 5, 1), IDX["n_l1"]]
    sats_before = float(np.nanmedian(before)) if np.isfinite(before).any() else None
    n_now = x[w, IDX["n_l1"]]
    saturated = bool(np.isfinite(lost) and lost >= 0.9) or not np.isfinite(drop)
    obs = {
        "d_cn0_db": None if saturated or not np.isfinite(drop) else round(float(drop), 1),
        "d_cn0_spread_db": None if not np.isfinite(spread) else round(float(spread), 1),
        "d_cn0_l5_db": None if not np.isfinite(drop5) else round(float(drop5), 1),
        "d_cn0_min_db": None if not np.isfinite(lb) else round(float(lb), 1),
        "saturated": saturated,
        "d_agc_db": None if not np.isfinite(zagc) or not np.isfinite(agc_sigma[0]) else round(float(zagc * agc_sigma[0]), 1),
        "sats_before": sats_before, "sats_min": float(np.nanmin(n_now)) if np.isfinite(n_now).any() else 0.0,
        "bands": [r.replace("BAND_", "") for r in ev["reasons"] if r.startswith("BAND_")],
        "claimed_cell": None,
    }
    if ev["type"] in ("spoof", "meacon"):
        k = min(a + 20, ms.n_epochs - 1)
        if np.all(np.isfinite(ms.fix_ecef[k])):
            la, lo, _ = ecef_to_lla(ms.fix_ecef[k])
            obs["claimed_cell"] = cells.latlng_to_cell(float(la), float(lo), 9)
    return {
        "schema": 1,
        "token": privacy.token_for_position(device_secret, unix0 + a, float(lat), float(lon)),
        "tier": ms.meta.get("tier", "C"),
        "t_start": int(unix0 + a), "t_end": int(unix0 + b),
        "cell": cells.latlng_to_cell(float(lat), float(lon), event_res), "pos_source": src,
        "type": ev["type"], "score": round(float(ev["score"]), 4), "reasons": list(ev["reasons"]),
        "obs": obs, "evidence": ms.meta.get("evidence", "replay"),
    }


def coverage_pings(ms, device_secret: bytes, unix0: float) -> list:
    """One record per res 7 cell and hour in which the device logged."""
    out: dict = {}
    for k in range(0, ms.n_epochs, 30):
        p = ms.fix_ecef[k] if np.all(np.isfinite(ms.fix_ecef[k])) else ms.net_ecef[k]
        if not np.all(np.isfinite(p)):
            continue
        lat, lon, _ = ecef_to_lla(p)
        cell7 = cells.latlng_to_cell(float(lat), float(lon), privacy.COVERAGE_RES)
        hour = int((unix0 + k) // 3600)
        rec = out.setdefault((cell7, hour), {
            "schema": 1, "token": privacy.token_for_position(device_secret, unix0 + k, float(lat), float(lon)),
            "cell7": cell7, "hour": hour, "tier": ms.meta.get("tier", "C"), "seconds": 0})
        rec["seconds"] += 30
    return list(out.values())


def validate_event(d: dict, now: float | None = None, max_age_s: int = 7 * 86400) -> dict:
    """Check an uploaded event and return a cleaned copy. Raises ValueError on anything odd."""
    if not isinstance(d, dict) or d.get("schema") != 1:
        raise ValueError("unsupported schema")
    if not isinstance(d.get("token"), str) or not _TOKEN.match(d["token"]):
        raise ValueError("bad token")
    if d.get("tier") not in TIER_WEIGHT:
        raise ValueError("bad tier")
    if d.get("type") not in EVENT_TYPES:
        raise ValueError("bad type")
    try:
        t0, t1, score = int(d["t_start"]), int(d["t_end"]), float(d["score"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("bad times or score") from None
    if not (0 < t0 <= t1 <= t0 + 6 * 3600) or not 0.0 <= score <= 1.0:
        raise ValueError("times or score out of range")
    if now is not None and not (now - max_age_s <= t0 <= now + 300):
        raise ValueError("event time outside the accepted window")
    cell = d.get("cell")
    if not cells.is_valid(cell) or not 8 <= cells.resolution(cell) <= 10:
        raise ValueError("bad cell")
    obs_in = d.get("obs") or {}
    obs = {}
    for key, lo, hi in (("d_cn0_db", -30.0, 60.0), ("d_cn0_spread_db", 0.0, 40.0), ("d_cn0_l5_db", -30.0, 60.0),
                        ("d_cn0_min_db", -30.0, 60.0), ("d_agc_db", -80.0, 80.0), ("sats_before", 0.0, 200.0),
                        ("sats_min", 0.0, 200.0)):
        v = obs_in.get(key)
        if v is not None:
            v = float(v)
            if not lo <= v <= hi:
                raise ValueError(f"{key} out of range")
        obs[key] = v
    obs["saturated"] = bool(obs_in.get("saturated", False))
    obs["bands"] = [str(b)[:12] for b in (obs_in.get("bands") or [])][:4]
    claimed = obs_in.get("claimed_cell")
    if claimed is not None and not cells.is_valid(claimed):
        raise ValueError("bad claimed_cell")
    obs["claimed_cell"] = claimed
    reasons = [str(r)[:40] for r in (d.get("reasons") or [])][:6]
    return {"schema": 1, "token": d["token"], "tier": d["tier"], "t_start": t0, "t_end": t1, "cell": cell,
            "pos_source": str(d.get("pos_source", ""))[:16], "type": d["type"], "score": score, "reasons": reasons,
            "obs": obs, "evidence": "real" if d.get("evidence") == "real" else "replay"}


def validate_ping(d: dict) -> dict:
    if not isinstance(d, dict) or d.get("schema") != 1:
        raise ValueError("unsupported schema")
    if not isinstance(d.get("token"), str) or not _TOKEN.match(d["token"]):
        raise ValueError("bad token")
    if d.get("tier") not in TIER_WEIGHT:
        raise ValueError("bad tier")
    cell7 = d.get("cell7")
    if not cells.is_valid(cell7) or cells.resolution(cell7) != privacy.COVERAGE_RES:
        raise ValueError("bad cell7")
    hour, seconds = int(d["hour"]), int(d["seconds"])
    if not 0 < seconds <= 3600 or hour <= 0:
        raise ValueError("bad hour or seconds")
    return {"schema": 1, "token": d["token"], "cell7": cell7, "hour": hour, "tier": d["tier"], "seconds": seconds}
