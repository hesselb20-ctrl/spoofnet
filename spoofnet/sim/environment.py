"""Propagation environments: attenuation per satellite as a function of
azimuth, elevation and time, plus excess pseudorange error for reflections.

These are engineering models built from general knowledge of how each setting
behaves. They are not fitted to field data yet; baseline logs from real phones
(milestone 1) are what will replace or confirm the numbers.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

from .motion import Motion

# env kind -> (motion kinds to choose from, network position classes to choose from)
ENV_KINDS = {
    "open_static": (("static_table", "static_hand"), ("wifi", "cell")),
    "open_walk": (("walk",), ("wifi", "cell")),
    "open_car": (("car_highway",), ("cell", "rural")),
    "urban_walk": (("walk",), ("wifi",)),
    "urban_car": (("car_urban",), ("wifi", "cell")),
    "tunnel_car": (("car_highway",), ("cell",)),
    "garage": (("car_urban",), ("wifi", "cell")),
    "forest_walk": (("walk",), ("cell", "rural")),
    "forest_car": (("car_highway", "car_urban"), ("cell", "rural")),
    "boat_deck": (("boat",), ("none", "none", "rural")),
    "boat_cabin": (("boat",), ("none", "none", "rural")),
    "tractor": (("tractor",), ("rural", "cell")),
    "indoor_window": (("static_hand", "static_table"), ("wifi",)),
    "metal_car": (("car_urban",), ("wifi", "cell")),
}
# Never used for fitting or threshold selection; they only appear in the test split.
HELD_OUT_ENVS = ("indoor_window", "metal_car")
TRAIN_ENVS = tuple(k for k in ENV_KINDS if k not in HELD_OUT_ENVS)


def ar1(rng, n, m, sigma, tau):
    """Stationary AR(1) Gaussian process, shape (n, m)."""
    rho = float(np.exp(-1.0 / max(tau, 1e-3)))
    burn = int(min(5 * tau, 200)) + 1
    x = lfilter([np.sqrt(1 - rho * rho)], [1.0, -rho], rng.normal(size=(n + burn, m)), axis=0)
    return sigma * x[burn:]


def _piecewise(rng, n, gap, draw):
    """Piecewise-constant series: a new value from `draw()` every U(gap) seconds."""
    out = np.empty(n)
    t = 0
    while t < n:
        d = int(rng.uniform(*gap)) + 1
        out[t:t + d] = draw()
        t += d
    return out


def _canyon(rng, rs, az, el, motion, k):
    n, s = az.shape
    static = float(np.max(motion.speed)) < 0.3
    street = np.degrees(motion.heading) if not static else np.full(n, rs.uniform(0, 360))
    street = np.round(street / 15.0) * 15.0
    gap = (9e9, 9e9) if static else (12, 60)
    draw = lambda: 0.08 if rs.random() < 0.12 else rs.uniform(0.5, 3.5 * k)   # 0.08 = open intersection
    left, right = _piecewise(rs, n, gap, draw), _piecewise(rs, n, gap, draw)
    phi = np.radians(az - street[:, None])
    ratio = np.where(np.sin(phi) > 0, right[:, None], left[:, None])
    mask = np.degrees(np.arctan(ratio * np.abs(np.sin(phi))))
    blocked = el < mask
    att_b = np.clip(16.0 + ar1(rng, n, s, 6.0, 8.0), 5.0, 40.0)
    att_l = np.abs(ar1(rng, n, s, 1.3, 5.0))
    bias = np.where(blocked, np.clip(35.0 + ar1(rng, n, s, 30.0, 12.0), 3.0, 150.0), np.abs(ar1(rng, n, s, 1.5, 6.0)))
    return np.where(blocked, att_b, att_l), bias


def _foliage(rng, rs, az, el, motion, k, intermittent):
    n, s = az.shape
    depth = rs.uniform(3.0, 8.0 * k)
    path = (1.0 / np.sin(np.radians(np.clip(el, 12.0, 90.0)))) ** 0.7
    tau = 5.0 if float(np.max(motion.speed)) > 0.3 else 45.0
    g = np.exp(ar1(rng, n, s, 0.5, tau))
    att = depth * path * g
    if intermittent:
        on = _piecewise(rs, n, (8, 60), lambda: float(rs.random() < 0.55))
        att *= on[:, None]
    return att


def _roof(rng, rs, az, el, motion, k, a_roof, el_roof, sector_max):
    n, s = az.shape
    sectors = rs.uniform(0.0, sector_max, 8)
    rel = (az - np.degrees(motion.heading)[:, None]) % 360.0
    side = sectors[(rel // 45.0).astype(int) % 8]
    att = np.where(el > el_roof, a_roof, side) + np.abs(ar1(rng, n, s, 2.0 * k, 10.0))
    return att


def _pocket(rng, az, el, motion, k):
    n, s = az.shape
    rel = np.radians(az - np.degrees(motion.heading)[:, None] - rng.uniform(0, 360))
    body = np.where(np.cos(rel) > 0, rng.uniform(4.0, 10.0 * k), 0.0)
    att = rng.uniform(3.0, 7.0) + body + ar1(rng, n, s, 2.5, 15.0)
    return np.clip(att, 0.0, None) * (motion.posture[:, None] == 1)


def _events(rng, n, rate_per_h, dur, lead=60):
    """Random (start, end) second pairs, non-overlapping, away from the edges."""
    out, t = [], lead
    count = rng.poisson(rate_per_h * n / 3600.0)
    for _ in range(count):
        d = int(rng.uniform(*dur))
        if n - d - 30 <= t:
            break
        a = int(rng.uniform(t, max(t + 1, n - d - 30)))
        out.append((a, a + d))
        t = a + d + 20
    return out


def attenuation(kind: str, az, el, motion: Motion, rng: np.random.Generator, wide: bool = False, rs=None):
    """Return (att_dB (T,S), excess_range_m (T,S), info) for satellites seen at az/el (degrees).

    `rs` draws the structure of the place (where the tunnels are, how tall the buildings
    are); `rng` draws everything that differs from one visit to the next. They are the
    same generator unless a scenario asks for a repeated route."""
    rs = rng if rs is None else rs
    n, s = az.shape
    k = 1.3 if wide else 1.0
    att = np.abs(ar1(rng, n, s, 0.4, 20.0))          # benign slow multipath everywhere
    bias = np.abs(ar1(rng, n, s, 0.8, 8.0))
    info: dict = {"blackouts": []}

    if kind in ("urban_walk", "urban_car"):
        a, b = _canyon(rng, rs, az, el, motion, k)
        att, bias = att + a, bias + b
    if kind in ("forest_walk", "forest_car", "tractor"):
        att += _foliage(rng, rs, az, el, motion, k, intermittent=kind != "forest_walk")
    if kind in ("open_car", "urban_car", "tunnel_car", "garage", "forest_car"):
        att += _roof(rng, rs, az, el, motion, k, rs.uniform(2.0, 7.0), rs.uniform(50.0, 70.0), 3.0)
    if kind == "tractor":
        att += _roof(rng, rs, az, el, motion, k, rs.uniform(8.0, 16.0), rs.uniform(45.0, 65.0), 4.0)
    if kind == "boat_cabin":
        roll = 3.0 * np.sin(2 * np.pi * np.arange(n) / rs.uniform(5, 9))[:, None]
        att += _roof(rng, rs, az, el + roll, motion, k, rs.uniform(15.0, 30.0 * k), rs.uniform(20.0, 35.0), 12.0)
    if kind == "boat_deck":
        att += _roof(rng, rs, az, el, motion, k, 0.0, 91.0, 5.0)     # mast and superstructure shadows only
    if kind in ("open_walk", "urban_walk", "forest_walk", "open_static", "indoor_window"):
        att += _pocket(rng, az, el, motion, k)
    if kind == "indoor_window":
        facing = np.cos(np.radians(az - rng.uniform(0, 360))) > 0.2
        att += np.where(facing, rng.uniform(2.0, 8.0), rng.uniform(18.0, 32.0)) + np.abs(ar1(rng, n, s, 4.0, 30.0))
        bias += np.where(facing, 3.0, 25.0) * np.abs(ar1(rng, n, s, 1.0, 20.0))
    if kind == "metal_car":
        # Coated windscreen and metal roof: nearly the same loss on every satellite, starting the
        # moment the phone is carried into the car. The hardest confuser for phones without AGC.
        start = int(rng.uniform(60, max(61, n * 0.5)))
        level = rng.uniform(6.0, 14.0 * k)
        per_sat = np.abs(ar1(rng, n, s, rng.uniform(1.8, 3.2), 25.0))
        att[start:] += level + per_sat[start:]
        motion.handling[start:start + 2] = True
        motion.tilt[start:start + 2] = rng.uniform(30, 120)
        info["enter_car"] = start

    if kind in ("tunnel_car", "urban_car", "forest_car", "open_car"):
        rate = 6.0 if kind != "tunnel_car" else 10.0
        for a, b in _events(rs, n, rate, (2, 6)):                # bridges and underpasses
            att[a:b] += rs.uniform(10.0, 25.0) + np.abs(rng.normal(0, 5.0, s))
    if kind == "tunnel_car":
        for a, b in _events(rs, n, 5.0, (12, 150 * k)):
            att[a:b] += 70.0
            att[max(a - 1, 0)] += 20.0
            info["blackouts"].append((a, b))
    if kind == "garage":
        for a, b in _events(rs, n, 2.5, (120, 700 * k)):
            ramp = int(rs.uniform(4, 10))
            deep = rs.uniform(28.0, 45.0) + rng.normal(0, 6.0, s)
            prof = np.ones(b - a)
            prof[:ramp] = np.linspace(0.2, 1.0, ramp)[: b - a]
            prof[-ramp:] = np.minimum(prof[-ramp:], np.linspace(1.0, 0.2, ramp)[-(b - a):])
            att[a:b] += prof[:, None] * np.clip(deep, 12.0, None)[None, :]
            info["blackouts"].append((a, b))
    return att, bias, info
