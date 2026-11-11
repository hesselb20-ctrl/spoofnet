"""Scenario generators and the train / val / test split (DESIGN.md section 7).

Every scenario is reproducible from (split, class, index). The test split draws
devices, environments and attacks from wider ranges than the other two, and it
alone contains the held-out environments.
"""
from __future__ import annotations

import numpy as np

from .devices import DeviceModel, sample_device
from .environment import HELD_OUT_ENVS, TRAIN_ENVS
from .inject import JamSpec, SpoofSpec
from .scenario import ScenarioSpec

SPLIT_BASE = {"train": 1_000_000, "val": 2_000_000, "test": 3_000_000}
ATTACK_CLASSES = ("jam_weak", "jam_moderate", "jam_strong",
                  "spoof_simple", "spoof_multi", "spoof_drag", "spoof_time", "meacon")
_CLASS_ID = {c: i for i, c in enumerate(("nominal",) + ATTACK_CLASSES)}
# An attack that starts inside a tunnel or a garage cannot be seen by anyone.
ATTACK_ENVS = tuple(e for e in TRAIN_ENVS if e not in ("tunnel_car", "garage"))
JAM_RANGES = {"jam_weak": (3.0, 6.0), "jam_moderate": (6.0, 15.0), "jam_strong": (15.0, 35.0)}


def scenario_seed(split: str, cls: str, index: int) -> int:
    return SPLIT_BASE[split] + 50_000 * _CLASS_ID[cls] + index


def make_device(seed: int, wide: bool = False, archetype: str | None = None) -> DeviceModel:
    return sample_device(np.random.default_rng(seed + 777_777_777), archetype, wide)


def calibration_spec(dev: DeviceModel, seed: int) -> ScenarioSpec:
    """A clean open-sky session of the same phone, standing in for its stored history."""
    return ScenarioSpec(seed=seed + 555_555_555, env="open_static", duration=600, device=dev)


def nominal_spec(split: str, index: int, duration: int = 3600) -> ScenarioSpec:
    seed = scenario_seed(split, "nominal", index)
    rng = np.random.default_rng(seed)
    wide = split == "test" and index % 2 == 1
    envs = TRAIN_ENVS + (HELD_OUT_ENVS if split == "test" else ())
    env = envs[index % len(envs)]
    rng.random()
    return ScenarioSpec(seed=seed, env=env, duration=duration, wide=wide, device=make_device(seed, wide))


def _loguniform(rng, lo, hi):
    return float(np.exp(rng.uniform(np.log(lo), np.log(hi))))


def _direction(rng, dist):
    a = rng.uniform(0, 2 * np.pi)
    return (dist * np.sin(a), dist * np.cos(a))


def make_attack(cls: str, rng: np.random.Generator, dev: DeviceModel, duration: int, wide: bool, moving: bool):
    k = 1.25 if wide else 1.0
    t0 = int(rng.uniform(240, 420))
    t1 = int(min(t0 + rng.uniform(90, 420), duration - 60))
    if cls in JAM_RANGES:
        lo, hi = JAM_RANGES[cls]
        kind = str(rng.choice(["L1_NARROW", "L1_NARROW", "L1_WIDE", "ALL_BANDS"]))
        return JamSpec(t0, t1, drop_db=float(rng.uniform(lo, hi)), kind=kind,
                       ramp_s=_loguniform(rng, 1.0, 20.0 * k), label=cls)
    fade = float(rng.uniform(1.0, 2.5)) if moving else float(rng.uniform(0.25, 0.8))
    all_c = dev.consts
    common = dict(t0=t0, t1=t1, fade_sigma=fade, label=cls)
    if cls in ("spoof_simple", "spoof_multi"):
        consts = ("G" if rng.random() < 0.75 else "GE") if cls == "spoof_simple" else all_c
        consts = "".join(c for c in consts if c in all_c) or "G"
        return SpoofSpec(kind=cls.split("_")[1], consts=consts,
                         lower_band=bool(cls == "spoof_multi" and rng.random() < 0.2),
                         offset_enu=_direction(rng, _loguniform(rng, 150.0 / k, 50_000.0)),
                         time_off_m=_loguniform(rng, 30.0, 3000.0) * (1 if rng.random() < 0.5 else -1),
                         time_drift_mps=float(rng.uniform(-3, 3)),
                         power_adv_db=float(rng.uniform(5.0 / k, 15.0 * k)), cn0_mode="flat",
                         cn0_level=float(rng.uniform(38, 48)),
                         pre_jam_s=int(rng.integers(2, 9)) if rng.random() < 0.4 else 0,
                         stale_s=float(rng.uniform(600, 86_400)) if rng.random() < 0.1 else 0.0,
                         gap_s=int(rng.integers(1, 4)), **common)
    if cls == "spoof_drag":
        return SpoofSpec(kind="drag", consts=all_c, lower_band=bool(rng.random() < 0.5), offset_enu=(0.0, 0.0),
                         follow=True, drag_mps=_direction(rng, float(rng.uniform(0.5 / k, 5.0))), time_off_m=0.0,
                         time_drift_mps=float(rng.uniform(-0.3, 0.3)), power_adv_db=float(rng.uniform(2, 4)),
                         cn0_mode="shaped", gap_s=0, **common)
    if cls == "spoof_time":
        step = rng.random() < 0.7
        return SpoofSpec(kind="time_only", consts=all_c, lower_band=bool(rng.random() < 0.7), offset_enu=(0.0, 0.0),
                         follow=True, time_off_m=_loguniform(rng, 30.0, 3000.0) if step else 0.0,
                         time_drift_mps=0.0 if step else float(rng.uniform(0.5, 5.0)) * (1 if rng.random() < 0.5 else -1),
                         power_adv_db=float(rng.uniform(3, 10)),
                         cn0_mode="shaped" if rng.random() < 0.6 else "flat", cn0_level=float(rng.uniform(38, 48)),
                         gap_s=int(rng.integers(0, 3)), **common)
    if cls == "meacon":
        dist = _loguniform(rng, 50.0, 5000.0)
        return SpoofSpec(kind="meacon", consts=all_c, lower_band=True, offset_enu=_direction(rng, dist),
                         time_off_m=dist + _loguniform(rng, 30.0, 3000.0), power_adv_db=float(rng.uniform(4, 10)),
                         cn0_mode="shaped", gap_s=int(rng.integers(1, 4)), **common)
    raise ValueError(cls)


def attack_spec(split: str, cls: str, index: int, duration: int = 900) -> ScenarioSpec:
    seed = scenario_seed(split, cls, index)
    rng = np.random.default_rng(seed)
    wide = split == "test" and index % 2 == 1
    env = ATTACK_ENVS[index % len(ATTACK_ENVS)]
    dev = make_device(seed, wide)
    moving = env not in ("open_static",)
    return ScenarioSpec(seed=seed, env=env, duration=duration, wide=wide, device=dev,
                        attacks=[make_attack(cls, rng, dev, duration, wide, moving)])
