"""Milestone 7: load simulated multi-device incidents into the service and write the
static map snapshot.

    python experiments/m7_demo.py                 # needs results/cache_net from m5_network.py
    uvicorn spoofnet.server.app:app --port 8787   # then open http://localhost:8787/

Everything loaded here is replay data and is labelled as such on the map.
Writes results/demo.sqlite, web/data/ and results/m7_demo.json.
"""
from __future__ import annotations

import copy
import hashlib
import json
import pickle
import time
from pathlib import Path

import numpy as np

from spoofnet.geo import ecef_to_lla, enu_to_ecef
from spoofnet.net import cells, netsim, privacy
from spoofnet.server import publication
from spoofnet.server.service import Service, save_snapshot

HOURS = 24


def shifted(run: dict, t_onset: float) -> tuple:
    """Copy a simulated run so its interference starts at wall-clock time `t_onset`."""
    scn = run["scenario"]
    dt = t_onset - (netsim.UNIX0 + scn.t0)
    events = copy.deepcopy(run["events"])
    for e in events:
        e["t_start"] = int(e["t_start"] + dt)
        e["t_end"] = int(e["t_end"] + dt)
        e["t_received"] = e["t_received"] + dt
        e.pop("_device", None)
    pings = copy.deepcopy(run["pings"])
    for p in pings:
        p["hour"] = int((p["hour"] * 3600 + dt) // 3600)
    return events, pings


def background_coverage(now: float, rng) -> list:
    """Simulated contributors that saw nothing, so the coverage layer has shape: a few
    towns and a ferry lane with many phones, and thin countryside in between."""
    towns = [(0.0, 0.0, 3500.0, 420), (-14000.0, 9000.0, 2500.0, 260), (17000.0, -6000.0, 3000.0, 300),
             (6000.0, 21000.0, 2000.0, 180), (-20000.0, -15000.0, 2500.0, 200)]
    points = []
    for cx, cy, sigma, count in towns:
        points += [(cx + dx, cy + dy) for dx, dy in rng.normal(0, sigma, (count, 2))]
    lane = np.linspace(0.0, 1.0, 160)                      # a shipping lane heading north-east out of the port
    points += [(3000.0 + 26000.0 * u + rng.normal(0, 700), 2000.0 + 30000.0 * u + rng.normal(0, 700)) for u in lane]
    points += [tuple(v) for v in rng.uniform(-30000, 30000, (220, 2))]
    pings = []
    for k, (e, n) in enumerate(points):
        lat, lon, _ = ecef_to_lla(enu_to_ecef(np.array([e, n, 0.0]), 54.52, 18.80, 0.0))
        cell7 = cells.latlng_to_cell(float(lat), float(lon), privacy.COVERAGE_RES)
        secret = hashlib.sha256(f"bg-{k}".encode()).digest()
        first = int(rng.integers(0, HOURS - 4))
        for h in range(first, min(first + int(rng.integers(4, 14)), HOURS)):
            t = now - (HOURS - h) * 3600
            pings.append({"schema": 1, "token": privacy.token_for_position(secret, t, float(lat), float(lon)),
                          "cell7": cell7, "hour": int(t // 3600), "tier": "ABBC"[k % 4], "seconds": 3000})
    return pings


def main() -> None:
    files = sorted(Path("results/cache_net").glob("runs_*.pkl"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit("run experiments/m5_network.py first")
    runs = pickle.loads(files[-1].read_bytes())
    pick = {}
    for kind, want in (("jam", 40), ("spoof", 15), ("meacon", 15)):
        cands = [r for r in runs if r["scenario"].kind == kind and r["scenario"].n_devices == want and len(r["events"]) >= 6]
        pick[kind] = cands[0]
    now = float(int(time.time() // 3600) * 3600)
    db = Path("results/demo.sqlite")
    db.unlink(missing_ok=True)
    svc = Service(str(db), publication.Rules.load())
    svc.add_key("demo-customer-key", "customer", "demo customer")
    svc.add_key("demo-vetted-key", "vetted", "demo authority")
    fence = svc.add_geofence("demo-customer-key", "Port approach (demo)", 54.52, 18.80, radius_km=12, min_confidence=0.6)
    log = {"evidence": "replay", "generated": now, "loaded": {}, "alerts": []}
    rng = np.random.default_rng(5)
    svc.ingest_pings(background_coverage(now, rng))
    for kind, hours_ago in (("jam", 20.5), ("spoof", 9.4), ("meacon", 2.6)):
        events, pings = shifted(pick[kind], now - hours_ago * 3600)
        t_in = max(e["t_received"] for e in events) + 1
        res = svc.ingest_events(events, t_in)
        svc.ingest_pings(pings)
        alerts = svc.rebuild(t_in)
        log["loaded"][kind] = {"events": res["accepted"], "rejected": len(res["rejected"]), "pings": len(pings),
                               "reject_reasons": sorted({r["error"] for r in res["rejected"]})}
        log["alerts"] += [{"geofence_id": a["geofence_id"], "type": a["body"]["incident"]["type"],
                           "confidence": a["body"]["incident"]["confidence"],
                           "geofence_coverage_share": a["body"]["geofence_coverage_share"]} for a in alerts]
    svc.rebuild(now)
    meta = save_snapshot(svc, "web/data", now - HOURS * 3600, now, now)
    t0 = now - HOURS * 3600
    log["incidents"] = {tier: len(svc.incidents_for(tier, t0, now, now)) for tier in publication.TIERS}
    log["public_example"] = svc.incidents_for("public", t0, now, now)[:1]
    log["coverage_cells_last_hour"] = len(svc.coverage(now - 3600, now))
    log["geofence_id"], log["snapshot_slots"] = fence, len(meta["slots"])
    Path("results/m7_demo.json").write_text(json.dumps(log, indent=1, default=float))
    print(json.dumps({k: v for k, v in log.items() if k != "public_example"}, indent=1, default=float))


if __name__ == "__main__":
    main()
