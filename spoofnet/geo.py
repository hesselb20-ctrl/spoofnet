"""WGS-84 geometry helpers. All functions are vectorised over leading axes."""
from __future__ import annotations

import numpy as np

C = 299_792_458.0            # speed of light, m/s
OMEGA_E = 7.2921151467e-5    # Earth rotation rate, rad/s
MU = 3.986004418e14          # Earth gravitational parameter, m^3/s^2
_A = 6378137.0
_F = 1.0 / 298.257223563
_E2 = _F * (2.0 - _F)
_B = _A * (1.0 - _F)
_EP2 = (_A**2 - _B**2) / _B**2


def lla_to_ecef(lat_deg, lon_deg, h=0.0):
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    n = _A / np.sqrt(1.0 - _E2 * np.sin(lat) ** 2)
    x = (n + h) * np.cos(lat) * np.cos(lon)
    y = (n + h) * np.cos(lat) * np.sin(lon)
    z = (n * (1.0 - _E2) + h) * np.sin(lat)
    return np.stack(np.broadcast_arrays(x, y, z), axis=-1)


def ecef_to_lla(xyz):
    """Bowring's closed form; error is far below a millimetre near the surface."""
    xyz = np.asarray(xyz, dtype=float)
    x, y, z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
    p = np.hypot(x, y)
    th = np.arctan2(z * _A, p * _B)
    lat = np.arctan2(z + _EP2 * _B * np.sin(th) ** 3, p - _E2 * _A * np.cos(th) ** 3)
    lon = np.arctan2(y, x)
    n = _A / np.sqrt(1.0 - _E2 * np.sin(lat) ** 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        h = np.where(np.abs(np.cos(lat)) > 1e-6, p / np.cos(lat) - n, np.abs(z) - _B)
    return np.degrees(lat), np.degrees(lon), h


def enu_basis(lat_deg, lon_deg):
    """Rows are the east, north and up unit vectors in ECEF. Shape (..., 3, 3)."""
    lat = np.radians(np.asarray(lat_deg, dtype=float))
    lon = np.radians(np.asarray(lon_deg, dtype=float))
    sl, cl, so, co = np.sin(lat), np.cos(lat), np.sin(lon), np.cos(lon)
    z = np.zeros_like(sl)
    e = np.stack([-so, co, z], axis=-1)
    n = np.stack([-sl * co, -sl * so, cl], axis=-1)
    u = np.stack([cl * co, cl * so, sl], axis=-1)
    return np.stack([e, n, u], axis=-2)


def enu_to_ecef(enu, ref_lat, ref_lon, ref_h=0.0):
    r = enu_basis(ref_lat, ref_lon)
    return lla_to_ecef(ref_lat, ref_lon, ref_h) + np.asarray(enu) @ r


def ecef_to_enu(xyz, ref_lat, ref_lon, ref_h=0.0):
    r = enu_basis(ref_lat, ref_lon)
    return (np.asarray(xyz) - lla_to_ecef(ref_lat, ref_lon, ref_h)) @ r.T


def az_el(rx_ecef, sat_ecef):
    """Azimuth and elevation in degrees of satellites seen from receivers.

    rx_ecef: (T, 3); sat_ecef: (T, N, 3). Returns two (T, N) arrays.
    """
    rx_ecef = np.asarray(rx_ecef, dtype=float)
    lat, lon, _ = ecef_to_lla(rx_ecef)
    basis = enu_basis(lat, lon)                       # (T, 3, 3)
    d = sat_ecef - rx_ecef[:, None, :]
    enu = np.einsum("tij,tnj->tni", basis, d)
    rng = np.linalg.norm(enu, axis=-1)
    el = np.degrees(np.arcsin(np.clip(enu[..., 2] / rng, -1.0, 1.0)))
    az = np.degrees(np.arctan2(enu[..., 0], enu[..., 1])) % 360.0
    return az, el


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2.0 * 6371008.8 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
