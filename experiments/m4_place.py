"""Milestone 4: what the per-place baseline buys on repeated routes.

A phone drives the same route on six days. Days 0 to 2 teach the place table;
days 3 to 5 measure how many `loss_unknown` reports the table removes, and
confirm that it never removes an alarm.

    python experiments/m4_place.py [--routes 12] [--workers 6]

Writes results/m4_place.json. Replay evidence.
"""
from __future__ import annotations

import argparse
import json
from multiprocessing import Pool
from pathlib import Path

import numpy as np

import spoofnet.replay.harness  # noqa: F401  (limits BLAS threads before workers start)
from spoofnet.detect.detector import DetectorConfig, detect
from spoofnet.detect.features import extract, fit_device_baseline
from spoofnet.detect.place import PlaceTable
from spoofnet.sim import catalog
from spoofnet.sim.inject import JamSpec
from spoofnet.sim.scenario import ORIGINS, ScenarioSpec, simulate

ENVS = ("tunnel_car", "garage", "urban_car", "forest_car")
LEARN_DAYS, EVAL_DAYS, DURATION = 3, 3, 1200


def route_job(args) -> dict:
    env, route_seed, cfg_d = args
    cfg = DetectorConfig.from_dict(cfg_d)
    rng = np.random.default_rng(route_seed)
    origin = ORIGINS[int(rng.integers(len(ORIGINS)))]
    device = catalog.make_device(route_seed)                 # the same phone every day
    base = fit_device_baseline(simulate(catalog.calibration_spec(device, route_seed)))
    table = PlaceTable()
    out = {"env": env, "tier": device.tier, "hours": 0.0, "loss_raw": 0, "loss_kept": 0, "alarms_raw": 0,
           "alarms_kept": 0, "alarms_marked": 0, "jam_detected_raw": 0, "jam_detected_kept": 0, "jam_runs": 0,
           "known_cells": 0}
    for day in range(LEARN_DAYS + EVAL_DAYS):
        spec = ScenarioSpec(seed=route_seed * 100 + day, env=env, duration=DURATION, device=device, origin=origin,
                            route_seed=route_seed)
        ms = simulate(spec)
        x = extract(ms, base, cfg.gates).x
        events = detect(x, cfg)
        if day < LEARN_DAYS:
            table.learn(ms, x, day, events)
            continue
        kept = table.filter_events(ms, events)
        alarm = lambda evs: [e for e in evs if e["type"] != "loss_unknown"]
        out["hours"] += (DURATION - cfg.warmup_s) / 3600.0
        out["loss_raw"] += len(events) - len(alarm(events))
        out["loss_kept"] += len(kept) - len(alarm(kept))
        out["alarms_raw"] += len(alarm(events))
        out["alarms_kept"] += len(alarm(kept))
        out["alarms_marked"] += sum(1 for e in kept if e.get("place_history"))
    # One more day with moderate jamming away from the blackouts: the table must not hide it.
    clean = simulate(ScenarioSpec(seed=route_seed * 100 + 9, env=env, duration=DURATION, device=device, origin=origin,
                                  route_seed=route_seed))
    busy = np.zeros(DURATION, dtype=bool)
    for a, b in clean.truth["blackouts"]:
        busy[max(a - 30, 0):b + 60] = True
    free = [t for t in range(300, DURATION - 260, 20) if not busy[t:t + 200].any()]
    if free:
        t0 = int(free[len(free) // 2])
        spec = ScenarioSpec(seed=route_seed * 100 + 9, env=env, duration=DURATION, device=device, origin=origin,
                            route_seed=route_seed, attacks=[JamSpec(t0, t0 + 180, drop_db=10.0, kind="L1_NARROW")])
        ms = simulate(spec)
        x = extract(ms, base, cfg.gates).x
        events = detect(x, cfg)
        kept = table.filter_events(ms, events)
        hit = lambda evs: any(e["type"] == "jam" and t0 - 5 <= e["start"] < t0 + 190 for e in evs)
        out["jam_runs"] += 1
        out["jam_detected_raw"] += hit(events)
        out["jam_detected_kept"] += hit(kept)
    out["known_cells"] = sum(1 for c in table.losses if table.expected_loss(c))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", type=int, default=12)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    cfg = DetectorConfig.load("config/detector.json")
    jobs = [(env, 40_000 + 100 * k + i, cfg.to_dict()) for k, env in enumerate(ENVS) for i in range(args.routes)]
    with Pool(args.workers) as pool:
        res = pool.map(route_job, jobs, chunksize=1)
    summary = {"evidence": "replay", "routes_per_env": args.routes, "learn_days": LEARN_DAYS, "eval_days": EVAL_DAYS,
               "by_env": {}}
    for env in ENVS + ("all",):
        rows = [r for r in res if env == "all" or r["env"] == env]
        h = sum(r["hours"] for r in rows)
        tot = lambda k: int(sum(r[k] for r in rows))
        summary["by_env"][env] = {
            "eval_hours": round(h, 1), "loss_unknown_per_hour_without_table": tot("loss_raw") / max(h, 1e-9),
            "loss_unknown_per_hour_with_table": tot("loss_kept") / max(h, 1e-9),
            "alarms_without_table": tot("alarms_raw"), "alarms_with_table": tot("alarms_kept"),
            "alarms_marked_place_history": tot("alarms_marked"),
            "jam_runs": tot("jam_runs"), "jam_detected_without_table": tot("jam_detected_raw"),
            "jam_detected_with_table": tot("jam_detected_kept"),
            "routes_with_a_learned_loss_place": int(sum(r["known_cells"] > 0 for r in rows))}
    Path("results/m4_place.json").write_text(json.dumps(summary, indent=1))
    for env, v in summary["by_env"].items():
        print(f"{env:11s} {v['eval_hours']:5.1f} h  loss_unknown/h {v['loss_unknown_per_hour_without_table']:.2f} -> "
              f"{v['loss_unknown_per_hour_with_table']:.2f}   alarms {v['alarms_without_table']} -> {v['alarms_with_table']}   "
              f"jam kept {v['jam_detected_with_table']}/{v['jam_detected_without_table']} of {v['jam_runs']}")


if __name__ == "__main__":
    main()
