"""Storage and aggregation service behind the API.

SQLite here so the whole system runs locally with no account anywhere. The
tables map one to one onto `schema.sql` for Postgres + PostGIS + h3-pg.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
import time
from pathlib import Path

from ..net import adsb, cells, privacy
from ..net.events import TIER_WEIGHT, validate_event, validate_ping
from ..net.incidents import build_incidents
from . import publication

MIN_COVERAGE_S = 600          # device-seconds per cell and hour below which coverage is "none"
GOOD_COVERAGE_TOKENS = 5
EVENT_DETAIL_S = 3600         # after this, stored event cells are coarsened to res 8
INCIDENT_WINDOW_S = 6 * 3600  # events newer than this are re-clustered on each rebuild

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, token TEXT, tier TEXT, t_start INTEGER, t_end INTEGER, cell TEXT, type TEXT,
  score REAL, reasons TEXT, obs TEXT, evidence TEXT, pos_source TEXT, t_received REAL,
  UNIQUE(token, t_start, type));
CREATE INDEX IF NOT EXISTS events_t ON events(t_start);
CREATE TABLE IF NOT EXISTS pings (
  token TEXT, cell7 TEXT, hour INTEGER, tier TEXT, seconds INTEGER, PRIMARY KEY(token, cell7, hour));
CREATE INDEX IF NOT EXISTS pings_hour ON pings(hour);
CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY, type TEXT, confidence REAL, t_start INTEGER, t_end INTEGER, t_created REAL,
  n_devices INTEGER, weight REAL, body TEXT, updated REAL);
CREATE INDEX IF NOT EXISTS incidents_t ON incidents(t_start);
CREATE TABLE IF NOT EXISTS api_keys (key_hash TEXT PRIMARY KEY, tier TEXT, name TEXT);
CREATE TABLE IF NOT EXISTS geofences (
  id INTEGER PRIMARY KEY, key_hash TEXT, name TEXT, cells7 TEXT, min_confidence REAL, types TEXT,
  webhook TEXT, secret TEXT);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY, geofence_id INTEGER, incident_id TEXT, t REAL, body TEXT, delivered INTEGER DEFAULT 0,
  UNIQUE(geofence_id, incident_id));
"""


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class Service:
    def __init__(self, db_path=":memory:", rules: publication.Rules | None = None, adsb_table: dict | None = None):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.lock = threading.Lock()
        self.rules = rules or publication.Rules()
        self.adsb_table = adsb_table or {}

    # ---- ingest ------------------------------------------------------------------------------
    def ingest_events(self, items: list, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        ok, rejected = 0, []
        with self.lock:
            for i, raw in enumerate(items):
                try:
                    e = validate_event(raw, now)
                    if not self.rules.collection_allowed(e["cell"]):
                        raise ValueError("collection disabled in this region")
                except (ValueError, KeyError, TypeError) as exc:
                    rejected.append({"index": i, "error": str(exc)})
                    continue
                received = float(raw.get("t_received", now)) if isinstance(raw, dict) else now
                cur = self.db.execute(
                    "INSERT OR IGNORE INTO events(token,tier,t_start,t_end,cell,type,score,reasons,obs,evidence,"
                    "pos_source,t_received) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (e["token"], e["tier"], e["t_start"], e["t_end"], e["cell"], e["type"], e["score"],
                     json.dumps(e["reasons"]), json.dumps(e["obs"]), e["evidence"], e["pos_source"], received))
                ok += cur.rowcount
            self.db.commit()
        return {"accepted": ok, "rejected": rejected}

    def ingest_pings(self, items: list) -> dict:
        ok, rejected = 0, []
        with self.lock:
            for i, raw in enumerate(items):
                try:
                    p = validate_ping(raw)
                    if not self.rules.collection_allowed(p["cell7"]):
                        raise ValueError("collection disabled in this region")
                except (ValueError, KeyError, TypeError) as exc:
                    rejected.append({"index": i, "error": str(exc)})
                    continue
                self.db.execute(
                    "INSERT INTO pings(token,cell7,hour,tier,seconds) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(token,cell7,hour) DO UPDATE SET seconds=MIN(3600, MAX(seconds, excluded.seconds))",
                    (p["token"], p["cell7"], p["hour"], p["tier"], p["seconds"]))
                ok += 1
            self.db.commit()
        return {"accepted": ok, "rejected": rejected}

    # ---- incidents ---------------------------------------------------------------------------
    def _events_since(self, t: float) -> list:
        rows = self.db.execute("SELECT * FROM events WHERE t_end >= ? ORDER BY t_start", (t,)).fetchall()
        return [{"schema": 1, "token": r["token"], "tier": r["tier"], "t_start": r["t_start"], "t_end": r["t_end"],
                 "cell": r["cell"], "type": r["type"], "score": r["score"], "reasons": json.loads(r["reasons"]),
                 "obs": json.loads(r["obs"]), "evidence": r["evidence"], "pos_source": r["pos_source"],
                 "t_received": r["t_received"]} for r in rows]

    def rebuild(self, now: float | None = None) -> list:
        """Re-cluster recent events, store the incidents, raise geofence alerts. Returns the new alerts."""
        now = time.time() if now is None else now
        with self.lock:
            since = now - INCIDENT_WINDOW_S
            events = self._events_since(since)
            hours = (int(since // 3600), int(now // 3600))
            pings = [dict(r) for r in self.db.execute("SELECT * FROM pings WHERE hour BETWEEN ? AND ?", hours)]
            for inc in build_incidents(events, pings):
                d = inc.to_dict()
                d["adsb"] = adsb.cross_check(d["affected7"], d["t_start"], d["t_end"], self.adsb_table)["status"]
                self.db.execute(
                    "INSERT INTO incidents(id,type,confidence,t_start,t_end,t_created,n_devices,weight,body,updated) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET type=excluded.type,"
                    "confidence=excluded.confidence,t_end=excluded.t_end,n_devices=excluded.n_devices,"
                    "weight=excluded.weight,body=excluded.body,updated=excluded.updated,"
                    "t_created=MIN(t_created, excluded.t_created)",
                    (d["id"], d["type"], d["confidence"], d["t_start"], d["t_end"], d["t_created"], d["n_devices"],
                     d["weight"], json.dumps(d), now))
            # Precise event cells have served their purpose once the incident is located.
            old = self.db.execute("SELECT id, cell FROM events WHERE t_received < ?", (now - EVENT_DETAIL_S,)).fetchall()
            for r in old:
                if cells.resolution(r["cell"]) > privacy.STORE_RES:
                    self.db.execute("UPDATE events SET cell=? WHERE id=?", (cells.parent(r["cell"], privacy.STORE_RES), r["id"]))
            self.db.commit()
            return self._raise_alerts(now)

    def incidents(self, t0: float, t1: float) -> list:
        rows = self.db.execute("SELECT body FROM incidents WHERE t_end >= ? AND t_start <= ? ORDER BY t_start", (t0, t1))
        return [json.loads(r["body"]) for r in rows]

    def incidents_for(self, tier: str, t0: float, t1: float, now: float | None = None) -> list:
        now = time.time() if now is None else now
        out = []
        for inc in self.incidents(t0, t1):
            v = publication.view(inc, tier, self.rules, now)
            if v is not None:
                if tier == "public":
                    v["coverage"] = self.coverage_level(v["cells"], inc["t_start"], inc["t_end"])
                out.append(v)
        return out

    # ---- coverage ----------------------------------------------------------------------------
    def coverage(self, t0: float, t1: float, res: int = privacy.PUBLIC_RES) -> dict:
        """Per public cell: device-hours, distinct contributors and a level. Cells that
        are absent from the result have no data."""
        rows = self.db.execute("SELECT token, cell7, tier, seconds FROM pings WHERE hour BETWEEN ? AND ?",
                               (int(t0 // 3600), int(t1 // 3600))).fetchall()
        if not rows:
            return {}
        distinct = sorted({r["cell7"] for r in rows})
        par = dict(zip(distinct, cells.parents(distinct, res)))
        acc: dict = {}
        for r in rows:
            a = acc.setdefault(par[r["cell7"]], {"seconds": 0, "tokens": set(), "weight": 0.0})
            a["seconds"] += r["seconds"]
            a["tokens"].add(r["token"])
            a["weight"] += TIER_WEIGHT[r["tier"]] * r["seconds"] / 3600.0
        out = {}
        for c, a in acc.items():
            n = len(a["tokens"])
            # Below K contributors a cell is not shown as covered: it would expose individuals.
            if n < privacy.K_MIN or a["seconds"] < MIN_COVERAGE_S:
                continue
            out[c] = {"device_hours": round(a["seconds"] / 3600.0, 1), "contributors": publication.device_band(n),
                      "level": "good" if n >= GOOD_COVERAGE_TOKENS else "some"}
        return out

    def coverage_level(self, public_cells: list, t0: float, t1: float) -> str:
        if not public_cells:
            return "none"
        cov = self.coverage(t0 - 3600, t1 + 3600, cells.resolution(public_cells[0]))
        levels = [cov.get(c, {}).get("level", "none") for c in public_cells]
        return "good" if all(v == "good" for v in levels) else "none" if all(v == "none" for v in levels) else "some"

    # ---- keys, geofences, alerts -------------------------------------------------------------
    def add_key(self, key: str, tier: str, name: str = "") -> None:
        if tier not in ("customer", "vetted"):
            raise ValueError("tier must be customer or vetted")
        self.db.execute("INSERT OR REPLACE INTO api_keys(key_hash,tier,name) VALUES(?,?,?)", (hash_key(key), tier, name))
        self.db.commit()

    def tier_of(self, key: str | None) -> str:
        if not key:
            return "public"
        r = self.db.execute("SELECT tier FROM api_keys WHERE key_hash=?", (hash_key(key),)).fetchone()
        return r["tier"] if r else "public"

    def add_geofence(self, key: str, name: str, lat: float, lon: float, radius_km: float, min_confidence: float = 0.5,
                     types=("jam", "spoof", "meacon"), webhook: str | None = None, secret: str | None = None) -> int:
        if not 0.5 <= radius_km <= 200:
            raise ValueError("radius must be between 0.5 and 200 km")
        centre = cells.latlng_to_cell(lat, lon, 7)
        rings = max(1, int(round(radius_km / 2.4)))
        area = cells.grid_disks([centre], rings)[0]
        cur = self.db.execute(
            "INSERT INTO geofences(key_hash,name,cells7,min_confidence,types,webhook,secret) VALUES(?,?,?,?,?,?,?)",
            (hash_key(key), name[:80], json.dumps(sorted(area)), float(min_confidence), json.dumps(list(types)),
             webhook, secret))
        self.db.commit()
        return int(cur.lastrowid)

    def _raise_alerts(self, now: float) -> list:
        fences = self.db.execute("SELECT * FROM geofences").fetchall()
        if not fences:
            return []
        recent = self.incidents(now - INCIDENT_WINDOW_S, now + 60)
        new = []
        for f in fences:
            area, types = set(json.loads(f["cells7"])), set(json.loads(f["types"]))
            for inc in recent:
                if inc["type"] not in types or inc["confidence"] < f["min_confidence"] or not area & set(inc["affected7"]):
                    continue
                cov = self.coverage(inc["t_start"] - 3600, inc["t_end"] + 3600, 7)
                share = sum(1 for c in area if c in cov) / max(len(area), 1)
                body = {"geofence": f["name"], "incident": publication.view(inc, "customer", self.rules, now),
                        # An alert always says how much of the fence anyone was watching.
                        "geofence_coverage_share": round(share, 2),
                        "note": "No alert never means safe: check geofence_coverage_share."}
                cur = self.db.execute("INSERT OR IGNORE INTO alerts(geofence_id,incident_id,t,body) VALUES(?,?,?,?)",
                                      (f["id"], inc["id"], now, json.dumps(body)))
                if cur.rowcount:
                    new.append({"id": int(cur.lastrowid), "geofence_id": f["id"], "webhook": f["webhook"],
                                "secret": f["secret"], "body": body})
        self.db.commit()
        return new

    def alerts(self, key: str, since: float = 0.0) -> list:
        rows = self.db.execute(
            "SELECT a.id, a.t, a.body FROM alerts a JOIN geofences g ON g.id=a.geofence_id "
            "WHERE g.key_hash=? AND a.t>=? ORDER BY a.t", (hash_key(key), since)).fetchall()
        return [{"id": r["id"], "t": r["t"], **json.loads(r["body"])} for r in rows]

    # ---- exports and risk --------------------------------------------------------------------
    def export_csv(self, tier: str, t0: float, t1: float, now: float | None = None) -> str:
        rows = self.incidents_for(tier, t0, t1, now)
        head = ["id", "type", "confidence", "evidence", "t_start", "t_end", "devices", "cell_res", "cells", "adsb"]
        lines = [",".join(head)]
        for r in rows:
            lines.append(",".join(str(r.get(h, "")) if h != "cells" else " ".join(r["cells"]) for h in head))
        return "\n".join(lines) + "\n"

    def risk_heatmap(self, day: int, res: int = privacy.PUBLIC_RES, tier: str = "customer") -> dict:
        """Daily risk per cell: confidence-weighted incident minutes, next to the coverage
        that the number rests on. A cell with no coverage is absent, not zero."""
        t0, t1 = day * 86400, (day + 1) * 86400
        cov = self.coverage(t0, t1 - 1, res)
        risk = {c: 0.0 for c in cov}
        for inc in self.incidents(t0, t1):
            mins = (min(inc["t_end"], t1) - max(inc["t_start"], t0)) / 60.0
            for c in set(cells.parents(inc["affected7"], res)):
                risk[c] = risk.get(c, 0.0) + max(mins, 0.0) * inc["confidence"]
        return {c: {"incident_minutes_weighted": round(v, 1), "coverage": cov.get(c, {"level": "none"})["level"],
                    "device_hours": cov.get(c, {}).get("device_hours", 0.0)} for c, v in risk.items()}


def sign_webhook(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def cells_geojson(by_cell: dict) -> dict:
    """FeatureCollection of hexagons from {cell: properties}."""
    ids = list(by_cell)
    feats = []
    for c, ring in zip(ids, cells.cell_boundaries(ids)):
        coords = [[p[1], p[0]] for p in ring]
        coords.append(coords[0])
        feats.append({"type": "Feature", "properties": {"cell": c, **by_cell[c]},
                      "geometry": {"type": "Polygon", "coordinates": [coords]}})
    return {"type": "FeatureCollection", "features": feats}


def save_snapshot(svc: Service, out_dir, t0: float, t1: float, now: float, step_s: int = 3600) -> dict:
    """Write the public map data as static files, for hosting without a server."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    incs = svc.incidents_for("public", t0, t1, now)
    features = []
    for inc in incs:
        fc = cells_geojson({c: {k: v for k, v in inc.items() if k != "cells"} for c in inc["cells"]})
        features += fc["features"]
    (out / "incidents.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    slots = []
    for t in range(int(t0 // step_s * step_s), int(t1), step_s):
        cov = svc.coverage(t, t + step_s - 1)
        name = f"coverage_{t}.geojson"
        (out / name).write_text(json.dumps(cells_geojson(cov)))
        slots.append({"t": t, "coverage": name})
    meta = {"generated": now, "t0": t0, "t1": t1, "step_s": step_s, "slots": slots,
            "evidence_note": "Everything shown comes from software replay. No real-world detections yet."
            if all(i["evidence"] == "replay" for i in incs) else "Contains real-world detections; see each incident.",
            "public_res": svc.rules.default["public_res"], "k": svc.rules.default["k"]}
    (out / "meta.json").write_text(json.dumps(meta))
    return meta
