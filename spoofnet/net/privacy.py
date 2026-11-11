"""Contributor privacy primitives (DESIGN.md section 9)."""
from __future__ import annotations

import hashlib
import hmac

from . import cells

TOKEN_REGION_RES = 5      # tokens change when a device moves to another res 5 cell (about 250 km2)
EVENT_RES = 10            # resolution a device reports during an event
STORE_RES = 8             # resolution kept in storage after localisation
COVERAGE_RES = 7          # resolution of hourly coverage pings
PUBLIC_RES = 6            # default resolution of the public map
K_MIN = 3                 # distinct contributors needed before anything is public


def contributor_token(device_secret: bytes, utc_day: int, res5_cell: str) -> str:
    """Unlinkable across days and across res 5 regions; identical to ContributorToken.kt."""
    if not device_secret:
        raise ValueError("empty device secret")
    msg = f"{int(utc_day)}|{res5_cell}".encode("utf-8")
    return hmac.new(device_secret, msg, hashlib.sha256).digest()[:12].hex()


def token_for_position(device_secret: bytes, unix_s: float, lat: float, lon: float) -> str:
    return contributor_token(device_secret, int(unix_s // 86400), cells.latlng_to_cell(lat, lon, TOKEN_REGION_RES))


def coarsen(cell: str, res: int) -> str:
    return cell if cells.resolution(cell) <= res else cells.parent(cell, res)


def k_anonymous(tokens_by_cell: dict, k: int = K_MIN) -> dict:
    """Keep only the cells with at least k distinct contributor tokens."""
    return {c: t for c, t in tokens_by_cell.items() if len(set(t)) >= k}


def quantise_time(unix_s: float, step_s: int = 300) -> int:
    return int(unix_s // step_s) * step_s
