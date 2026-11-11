"""Replay harness: turn scenarios (or recorded logs) into cached feature frames.

Feature extraction does not depend on the fusion model or on event thresholds,
so a scenario is simulated and processed once and every later fitting or
scoring step runs on the cache.
"""
from __future__ import annotations

import hashlib
import json
import os

# One BLAS thread per worker process: the work is many small solves, and letting every
# worker start a full thread pool makes the whole run several times slower.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

from multiprocessing import Pool
from pathlib import Path

import numpy as np

from ..data import MeasurementSet
from ..detect.features import FEATURE_VERSION, DeviceBaseline, Gates, extract, fit_device_baseline
from ..sim import catalog
from ..sim.scenario import ScenarioSpec, simulate

LABELS = {"nominal": 0, "jam": 1, "spoof": 2, "meacon": 3}


def labels_from_truth(ms: MeasurementSet) -> np.ndarray:
    y = np.zeros(ms.n_epochs, dtype=np.int8)
    for a in ms.truth.get("attacks", []):
        y[a["t0"]:a["t1"]] = LABELS[a["type"]]
        if "attacks_pre" in ms.truth and a["type"] != "jam":
            p0, p1 = ms.truth["attacks_pre"]
            y[max(p0, 0):p1] = LABELS[a["type"]]
    return y


def process(ms: MeasurementSet, base: DeviceBaseline, gates: Gates) -> dict:
    """Features plus the bookkeeping the scorer needs. Works for simulated and recorded sets."""
    frame = extract(ms, base, gates)
    atk = [{k: v for k, v in a.items() if k not in ("profile", "claimed_pos")} for a in ms.truth.get("attacks", [])]
    return {"x": frame.x.astype(np.float32), "y": labels_from_truth(ms),
            "meta": {"env": ms.meta.get("env"), "tier": ms.meta.get("tier"), "has_agc": bool(ms.meta.get("has_agc")),
                     "dual": bool(ms.meta.get("dual")), "net_kind": ms.meta.get("net_kind"), "attacks": atk,
                     "blackouts": [list(map(int, b)) for b in ms.truth.get("blackouts", [])],
                     "evidence": ms.meta.get("evidence", "replay")}}


def run_spec(spec: ScenarioSpec, gates: Gates) -> dict:
    base = fit_device_baseline(simulate(catalog.calibration_spec(spec.device, spec.seed)))
    out = process(simulate(spec), base, gates)
    out["meta"].update(seed=spec.seed, wide=spec.wide, duration=spec.duration, baseline=base.to_dict())
    return out


def _load_or_run(args):
    split, cls, index, duration, gates_d, cache_dir = args[:6]
    gates = Gates.from_dict(gates_d)
    key = hashlib.sha1(json.dumps([FEATURE_VERSION, split, cls, index, duration, gates_d], sort_keys=True).encode()).hexdigest()[:16]
    path = Path(cache_dir) / f"{split}_{cls}_{index}_{key}.npz" if cache_dir else None
    if path is not None and path.exists():
        z = np.load(path, allow_pickle=False)
        return {"x": z["x"], "y": z["y"], "meta": json.loads(str(z["meta"]))}
    spec = (catalog.nominal_spec(split, index, duration) if cls == "nominal"
            else catalog.attack_spec(split, cls, index, duration))
    out = run_spec(spec, gates)
    out["meta"].update(split=split, cls=cls, index=index)
    if path is not None:
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, x=out["x"], y=out["y"], meta=json.dumps(out["meta"]))
        os.replace(tmp, path)
    return out


def _job(args):
    out = _load_or_run(args)
    reduce = args[6]
    return reduce(out) if reduce is not None else out


def run_many(jobs, gates: Gates, cache_dir: str | None = "results/cache", workers: int | None = None,
             reduce=None) -> list:
    """jobs: iterable of (split, class, index, duration). `reduce` is an optional picklable
    callable applied to each result inside the worker, to keep large runs out of memory."""
    if cache_dir:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
    gd = gates.to_dict()
    args = [(s, c, i, d, gd, cache_dir, reduce) for s, c, i, d in jobs]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    if workers == 1 or len(args) < 4:
        return [_job(a) for a in args]
    with Pool(workers) as pool:
        return pool.map(_job, args, chunksize=1)
