"""Receiver trajectories and the matching 1 Hz IMU summary (DESIGN.md 5.1)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Motion:
    enu: np.ndarray        # (T, 3) m, east north up from the scenario origin
    vel: np.ndarray        # (T, 3) m/s in ENU
    speed: np.ndarray      # (T,)
    heading: np.ndarray    # (T,) rad, 0 = north, clockwise
    vib: np.ndarray        # (T,) IMU vib_rms, m/s^2
    acc_h: np.ndarray      # (T,) IMU horizontal linear acceleration, m/s^2
    yaw: np.ndarray        # (T,) IMU yaw rate, rad/s
    tilt: np.ndarray       # (T,) IMU tilt change per second, degrees
    handling: np.ndarray   # (T,) bool, the phone was picked up, pocketed or put down
    posture: np.ndarray    # (T,) 0 = in the open, 1 = pocket or bag


# kind: (speed targets m/s, seconds between target changes, max accel, seconds between turns,
#        idle vib, moving vib, vib per m/s, tilt noise deg, handling events per hour)
_KINDS = {
    "static_table": ((0.0,), (9e9, 9e9), 0.0, (9e9, 9e9), 0.006, 0.006, 0.0, 0.05, 0.3),
    "static_hand": ((0.0,), (9e9, 9e9), 0.0, (9e9, 9e9), 0.05, 0.05, 0.0, 0.8, 6.0),
    "walk": ((0.0, 1.3, 1.5, 1.6), (40, 240), 0.8, (25, 120), 0.06, 1.6, 0.0, 3.0, 5.0),
    "car_urban": ((0.0, 0.0, 8.0, 12.0, 14.0), (15, 60), 2.2, (25, 90), 0.09, 0.22, 0.012, 0.6, 1.0),
    "car_highway": ((24.0, 28.0, 31.0, 33.0, 14.0), (60, 300), 1.5, (60, 300), 0.09, 0.25, 0.012, 0.6, 0.5),
    "boat": ((3.0, 5.0, 7.0, 8.0), (120, 600), 0.3, (90, 400), 0.15, 0.25, 0.01, 2.0, 1.0),
    "tractor": ((2.5, 3.0, 3.5, 4.0), (120, 400), 0.6, (60, 130), 0.3, 0.55, 0.02, 1.0, 0.5),
}
_TURN = {  # kind: (yaw rate rad/s, typical turn angle deg choices)
    "walk": (0.5, (45, 90, 90, 180)), "car_urban": (0.28, (90, 90, 45)), "car_highway": (0.03, (10, 20, 35)),
    "boat": (0.05, (15, 30, 60)), "tractor": (0.4, (180,)),
}


def gen_motion(kind: str, n: int, rng: np.random.Generator) -> Motion:
    targets, dwell, a_max, turn_gap, vib_idle, vib_move, vib_per_v, tilt_sd, handling_rate = _KINDS[kind]
    speed = np.zeros(n)
    yaw_true = np.zeros(n)
    v = float(rng.choice(targets))
    target = v
    next_target = rng.uniform(*dwell)
    next_turn = rng.uniform(*turn_gap)
    turn_left = 0.0
    turn_rate = 0.0
    for t in range(n):
        if t >= next_target:
            target = float(rng.choice(targets))
            next_target = t + rng.uniform(*dwell)
        v += float(np.clip(target - v, -a_max, a_max)) if a_max > 0 else 0.0
        speed[t] = max(v, 0.0)
        if kind in _TURN and t >= next_turn and speed[t] > 0.3:
            rate, angles = _TURN[kind]
            turn_left = np.radians(float(rng.choice(angles)))
            turn_rate = rate * (1 if rng.random() < 0.5 else -1) * rng.uniform(0.7, 1.2)
            next_turn = t + rng.uniform(*turn_gap)
        if turn_left > 0 and speed[t] > 0.3:
            step = min(abs(turn_rate), turn_left)
            yaw_true[t] = np.sign(turn_rate) * step
            turn_left -= step
    if kind in ("walk", "boat", "car_highway"):
        yaw_true += rng.normal(0, 0.004 if kind != "walk" else 0.02, n) * (speed > 0.3)
    heading = rng.uniform(0, 2 * np.pi) + np.cumsum(yaw_true)
    vel = np.stack([speed * np.sin(heading), speed * np.cos(heading), np.zeros(n)], axis=1)
    enu = np.cumsum(vel, axis=0) - vel
    if kind == "boat":
        enu[:, 2] += 0.4 * np.sin(2 * np.pi * np.arange(n) / rng.uniform(5, 9))

    moving = speed > 0.3
    vib = np.where(moving, vib_move + vib_per_v * speed, vib_idle) * np.exp(rng.normal(0, 0.25, n))
    acc_long = np.gradient(speed)
    acc_lat = speed * yaw_true
    acc_h = np.abs(np.hypot(acc_long, acc_lat) + rng.normal(0, 0.05, n)) + 0.08 * vib
    yaw = yaw_true + rng.normal(0, 0.003) + rng.normal(0, 0.004, n)
    tilt = np.abs(rng.normal(0, tilt_sd, n)) * np.where(moving | (kind == "static_hand") | (kind == "boat"), 1.0, 0.15)

    handling = np.zeros(n, dtype=bool)
    posture = np.zeros(n, dtype=int)
    n_events = rng.poisson(handling_rate * n / 3600.0)
    state = int(rng.random() < 0.4) if kind in ("walk",) else 0
    times = np.sort(rng.integers(30, max(31, n - 5), size=n_events)) if n_events else np.array([], dtype=int)
    prev = 0
    for te in times:
        posture[prev:te] = state
        handling[te:te + 2] = True
        tilt[te:te + 2] = rng.uniform(25, 130)
        vib[te:te + 2] += rng.uniform(0.8, 3.0)
        acc_h[te:te + 2] += rng.uniform(0.5, 2.5)
        yaw[te:te + 2] += rng.normal(0, 0.8)
        if kind in ("walk", "static_hand"):
            state = 1 - state
        prev = te
    posture[prev:] = state
    return Motion(enu, vel, speed, heading, vib, acc_h, yaw, tilt, handling, posture)
