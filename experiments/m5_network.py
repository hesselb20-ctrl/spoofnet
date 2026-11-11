"""Milestone 5: network aggregation measured on simulated multi-device scenarios
with known source positions.

    python experiments/m5_network.py [--per-condition 20] [--workers 6]

Writes results/m5_network.json. Everything here is replay evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pickle
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

import spoofnet.replay.harness  # noqa: F401  (limits BLAS threads before workers start)
from spoofnet.detect.detector import DetectorConfig
from spoofnet.geo import ecef_to_enu, haversine_m, lla_to_ecef
from spoofnet.net import cells, netsim
from spoofnet.net.incidents import build_incidents
from spoofnet.net.localize import inside_ellipse

PROPAGATION = ((2.0, 0.0), (2.0, 4.0), (2.7, 6.0), (3.5, 8.0))     # (path-loss exponent, shadow sigma dB)
DEVICE_COUNTS = (10, 20, 40)


def scenarios(per_condition: int) -> list:
    out, sid = [], 1000
    for n_dev in DEVICE_COUNTS:
        for n_exp, shadow in PROPAGATION:
            for _ in range(per_condition):
                sid += 1
                rng = np.random.default_rng(sid)
                r10 = float(np.exp(rng.uniform(np.log(300.0), np.log(2000.0))))
                jam_kind = str(rng.choice(["L1_NARROW", "L1_WIDE", "ALL_BANDS"]))
                out.append(netsim.NetScenario(seed=sid, n_devices=n_dev, kind="jam", n_exp=n_exp, shadow_db=shadow,
                                              r10_m=r10, jam_kind=jam_kind))
    for kind in ("spoof", "meacon"):
        for _ in range(max(per_condition, 20)):
            sid += 1
            out.append(netsim.NetScenario(seed=sid, n_devices=15, kind=kind, n_exp=2.0, shadow_db=3.0, r10_m=1200.0))
    return out


def coarsen(events: list, res: int) -> list:
    out = copy.deepcopy(events)
    for e, p in zip(out, cells.parents([e["cell"] for e in out], res)):
        e["cell"] = p
    return out


def evaluate(run: dict, res: int = 10, n_exp: float = 2.0, fit_n: bool = False) -> dict:
    scn = run["scenario"]
    events = run["events"] if res == 10 else coarsen(run["events"], res)
    incs = build_incidents(events, run["pings"], n_exp=n_exp, fit_n=fit_n)
    onset = netsim.UNIX0 + scn.t0
    live = [i for i in incs if i.t_end >= onset]
    false_before = len(incs) - len(live)
    if not live:
        return {"incident": False, "false_before": false_before}
    inc = max(live, key=lambda i: i.n_devices)
    out = {"incident": True, "false_before": false_before, "type": inc.type, "confidence": inc.confidence,
           "n_devices": inc.n_devices, "ttd_s": inc.t_created - onset, "extra_incidents": len(live) - 1}
    src = inc.source
    if src is not None:
        lat, lon = run["source_latlon"]
        out["err_m"] = float(haversine_m(lat, lon, src["lat"], src["lon"]))
        out["method"] = src.get("method")
        if "frame" in src and src.get("cov") is not None:
            t_enu = ecef_to_enu(lla_to_ecef(lat, lon, 0.0), src["frame"][0], src["frame"][1], 0.0)
            out["inside95"] = inside_ellipse(src, float(t_enu[0]), float(t_enu[1]))
            if src.get("ellipse95"):
                out["semi_major_m"] = src["ellipse95"]["semi_major_m"]
        out["n_meas"], out["n_sat"] = src.get("n_meas"), src.get("n_sat")
    return out


def stats(rows: list, key: str = "err_m") -> dict:
    v = np.array([r[key] for r in rows if r.get(key) is not None and np.isfinite(r[key])])
    if v.size == 0:
        return {"n": 0}
    return {"n": int(v.size), "median": float(np.median(v)), "p75": float(np.percentile(v, 75)),
            "p90": float(np.percentile(v, 90))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-condition", type=int, default=10)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    cfg = DetectorConfig.load("config/detector.json")
    scns = scenarios(args.per_condition)
    cache = Path("results/cache_net")
    cache.mkdir(parents=True, exist_ok=True)
    key = f"{args.per_condition}_" + hashlib.sha1(json.dumps(cfg.to_dict(), sort_keys=True, default=float).encode()).hexdigest()[:10]
    t0 = time.time()
    path = cache / f"runs_{key}.pkl"
    if path.exists():
        runs = pickle.loads(path.read_bytes())
    else:
        jobs = [j for s in scns for j in netsim.device_jobs(s, cfg)]
        print(f"{len(scns)} scenarios, {len(jobs)} device simulations", flush=True)
        with Pool(args.workers) as pool:
            res = pool.map(netsim._device_job, jobs, chunksize=2)
        runs, k = [], 0
        for s in scns:
            runs.append(netsim.collect(s, res[k:k + s.n_total]))
            k += s.n_total
        path.write_bytes(pickle.dumps(runs))
    sim_s = time.time() - t0

    out = {"evidence": "replay", "h3_backend": cells.backend(), "scenarios": len(runs), "sim_seconds": sim_s,
           "per_condition": args.per_condition, "jam": {}, "spoof": {}, "meacon": {}}
    jam = [r for r in runs if r["scenario"].kind == "jam"]

    # Headline configuration: the server assumes free-space loss (n = 2) and devices report res 10 cells.
    base_rows = [(r["scenario"], evaluate(r)) for r in jam]
    made = [e for _, e in base_rows if e["incident"]]
    out["jam"]["all"] = {
        "scenarios": len(jam), "incident_rate": len(made) / len(jam),
        "type_correct": float(np.mean([e["type"] == "jam" for e in made])) if made else None,
        "error_m": stats(made), "ttd_s": stats(made, "ttd_s"),
        "ellipse95_coverage": float(np.mean([e["inside95"] for e in made if "inside95" in e])),
        "methods": {m: sum(1 for e in made if e.get("method") == m) for m in {e.get("method") for e in made}},
        "false_incidents_before_onset": int(sum(e["false_before"] for _, e in base_rows)),
        "extra_incidents_during": int(sum(e.get("extra_incidents", 0) for _, e in base_rows)),
    }
    table = []
    for n_dev in DEVICE_COUNTS:
        for n_exp, shadow in PROPAGATION:
            rows = [e for s, e in base_rows if s.n_devices == n_dev and s.n_exp == n_exp and s.shadow_db == shadow]
            ok = [e for e in rows if e["incident"]]
            table.append({"devices": n_dev, "n_exp_true": n_exp, "shadow_db": shadow, "scenarios": len(rows),
                          "incident_rate": len(ok) / max(len(rows), 1), "error_m": stats(ok),
                          "ttd_s": stats(ok, "ttd_s"),
                          "ellipse95_coverage": float(np.mean([e["inside95"] for e in ok if "inside95" in e])) if ok else None})
    out["jam"]["by_condition"] = table

    # What precision costs in privacy: the same uploads coarsened before localisation.
    out["jam"]["by_upload_resolution"] = {}
    for res in (10, 9, 8):
        rows = [evaluate(r, res=res) for r in jam]
        ok = [e for e in rows if e["incident"]]
        out["jam"]["by_upload_resolution"][str(res)] = {
            "cell_area_km2": cells.AREA_KM2[res], "error_m": stats(ok),
            "ellipse95_coverage": float(np.mean([e["inside95"] for e in ok if "inside95" in e])) if ok else None}
    # Does estimating the exponent help when the true one is not 2?
    rows = [(r["scenario"], evaluate(r, fit_n=True)) for r in jam]
    out["jam"]["fit_exponent"] = {
        str(n_exp): stats([e for s, e in rows if s.n_exp == n_exp and e["incident"]]) for n_exp, _ in PROPAGATION}
    out["jam"]["fixed_exponent_2"] = {
        str(n_exp): stats([e for s, e in base_rows if s.n_exp == n_exp and e["incident"]]) for n_exp, _ in PROPAGATION}

    for kind in ("spoof", "meacon"):
        rs = [r for r in runs if r["scenario"].kind == kind]
        rows = [evaluate(r) for r in rs]
        ok = [e for e in rows if e["incident"]]
        out[kind] = {"scenarios": len(rs), "incident_rate": len(ok) / max(len(rs), 1),
                     "type_exact": float(np.mean([e["type"] == kind for e in ok])) if ok else None,
                     "type_spoof_or_meacon": float(np.mean([e["type"] in ("spoof", "meacon") for e in ok])) if ok else None,
                     "error_m": stats(ok), "ttd_s": stats(ok, "ttd_s"),
                     "methods": {str(m): sum(1 for e in ok if e.get("method") == m) for m in {e.get("method") for e in ok}}}

    Path("results/m5_network.json").write_text(json.dumps(out, indent=1, default=float))
    a = out["jam"]["all"]
    print(f"jam: {a['scenarios']} scenarios, incident in {a['incident_rate']*100:.0f}%, type ok {a['type_correct']}, "
          f"error median {a['error_m'].get('median', float('nan')):.0f} m p90 {a['error_m'].get('p90', float('nan')):.0f} m, "
          f"ellipse coverage {a['ellipse95_coverage']*100:.0f}%, TTD median {a['ttd_s'].get('median', float('nan')):.1f} s "
          f"p90 {a['ttd_s'].get('p90', float('nan')):.1f} s")
    for row in table:
        e = row["error_m"]
        print(f"  dev={row['devices']:2d} n={row['n_exp_true']} shadow={row['shadow_db']:.0f} dB: incident {row['incident_rate']*100:3.0f}% "
              f"median {e.get('median', float('nan')):6.0f} m  p90 {e.get('p90', float('nan')):6.0f} m  cover {row['ellipse95_coverage']}")
    for res, v in out["jam"]["by_upload_resolution"].items():
        print(f"  upload res {res}: median {v['error_m'].get('median', float('nan')):.0f} m, coverage {v['ellipse95_coverage']}")
    for kind in ("spoof", "meacon"):
        v = out[kind]
        print(f"{kind}: incident {v['incident_rate']*100:.0f}%, exact type {v['type_exact']}, spoof-or-meacon {v['type_spoof_or_meacon']}, "
              f"error {v['error_m']}, methods {v['methods']}")


if __name__ == "__main__":
    main()
