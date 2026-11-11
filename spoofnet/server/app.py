"""HTTP API (DESIGN.md sections 3, 9 and 10).

    uvicorn spoofnet.server.app:app --port 8787          # local run, SQLite file ./spoofnet.sqlite

Public, no key:
    GET  /v1/public/incidents?hours=24        coarse incidents, K-anonymous, delayed
    GET  /v1/public/coverage?t=<unix>         coverage per public cell; absent cells have no data
    GET  /v1/public/meta
Device uploads:
    POST /v1/events                           list of event records
    POST /v1/coverage                         list of coverage pings
Customers and vetted users, header X-API-Key:
    GET  /v1/incidents?t0=&t1=                tier-dependent detail
    GET  /v1/export.csv?t0=&t1=               historical export
    GET  /v1/risk/heatmap?day=<days since epoch>
    POST /v1/geofences                        {name, lat, lon, radius_km, min_confidence, types, webhook}
    GET  /v1/alerts?since=<unix>
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from ..net import privacy
from . import publication
from .service import Service, cells_geojson, sign_webhook

MAX_BATCH = 500
RATE_PER_MIN = 120            # upload requests per client address per minute


def _send_webhooks(alerts: list) -> None:
    """Best effort, signed, off the request thread. Disabled unless SPOOFNET_WEBHOOKS=1."""
    if os.environ.get("SPOOFNET_WEBHOOKS") != "1":
        return
    for a in alerts:
        if not a.get("webhook"):
            continue
        body = json.dumps(a["body"]).encode()
        req = urllib.request.Request(a["webhook"], data=body, method="POST", headers={
            "Content-Type": "application/json", "X-SpoofNet-Signature": sign_webhook(a.get("secret") or "", body)})
        try:
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:
            pass


def create_app(svc: Service | None = None, web_dir: str | None = "web", clock=time.time) -> FastAPI:
    svc = svc or Service(os.environ.get("SPOOFNET_DB", "spoofnet.sqlite"), publication.Rules.load())
    app = FastAPI(title="SpoofNet", version="0.1.0", docs_url="/v1/docs", redoc_url=None)
    app.state.svc = svc
    hits: dict = {}
    lock = threading.Lock()

    def limit(request: Request) -> None:
        # Address is used for rate limiting only and is never stored (THREAT_MODEL.md B2.3).
        who = request.client.host if request.client else "?"
        minute = int(clock() // 60)
        with lock:
            for k in [k for k in hits if k[1] < minute - 1]:
                del hits[k]
            hits[(who, minute)] = hits.get((who, minute), 0) + 1
            if hits[(who, minute)] > RATE_PER_MIN:
                raise HTTPException(429, "rate limit")

    def need(key: str | None, *tiers: str) -> str:
        tier = svc.tier_of(key)
        if tier not in tiers:
            raise HTTPException(403, "this endpoint needs an API key with access: " + ", ".join(tiers))
        return tier

    @app.get("/v1/public/meta")
    def meta():
        d = svc.rules.default
        return {"public_res": d["public_res"], "k": d["k"], "delay_s": d["delay_s"], "quantise_s": d["quantise_s"],
                "now": clock(), "note": "Absent cells have no data. No incident never means safe."}

    @app.get("/v1/public/incidents")
    def public_incidents(hours: float = Query(24, gt=0, le=24 * 30), until: float | None = None):
        now = clock()
        t1 = until or now
        incs = svc.incidents_for("public", t1 - hours * 3600, t1, now)
        feats = []
        for inc in incs:
            fc = cells_geojson({c: {k: v for k, v in inc.items() if k != "cells"} for c in inc["cells"]})
            feats += fc["features"]
        return {"type": "FeatureCollection", "features": feats, "count": len(incs)}

    @app.get("/v1/public/coverage")
    def public_coverage(t: float | None = None, hours: float = Query(1, gt=0, le=24)):
        t1 = t or clock()
        return cells_geojson(svc.coverage(t1 - hours * 3600, t1))

    @app.post("/v1/events")
    async def post_events(request: Request):
        limit(request)
        items = await request.json()
        if not isinstance(items, list) or len(items) > MAX_BATCH:
            raise HTTPException(400, f"expected a list of at most {MAX_BATCH} events")
        for it in items:
            if isinstance(it, dict):
                it.pop("t_received", None)        # receipt time is the server's, never the client's
        res = svc.ingest_events(items, clock())
        _send_webhooks(svc.rebuild(clock()))
        return res

    @app.post("/v1/coverage")
    async def post_coverage(request: Request):
        limit(request)
        items = await request.json()
        if not isinstance(items, list) or len(items) > MAX_BATCH:
            raise HTTPException(400, f"expected a list of at most {MAX_BATCH} pings")
        return svc.ingest_pings(items)

    @app.get("/v1/incidents")
    def incidents(t0: float, t1: float, x_api_key: str | None = Header(None)):
        tier = need(x_api_key, "customer", "vetted")
        return {"tier": tier, "incidents": svc.incidents_for(tier, t0, t1, clock())}

    @app.get("/v1/export.csv", response_class=PlainTextResponse)
    def export(t0: float, t1: float, x_api_key: str | None = Header(None)):
        tier = need(x_api_key, "customer", "vetted")
        return svc.export_csv(tier, t0, t1, clock())

    @app.get("/v1/risk/heatmap")
    def risk(day: int, x_api_key: str | None = Header(None)):
        need(x_api_key, "customer", "vetted")
        return cells_geojson(svc.risk_heatmap(day))

    @app.post("/v1/geofences")
    async def add_geofence(request: Request, x_api_key: str | None = Header(None)):
        need(x_api_key, "customer", "vetted")
        b = await request.json()
        try:
            gid = svc.add_geofence(x_api_key, str(b["name"]), float(b["lat"]), float(b["lon"]), float(b["radius_km"]),
                                   float(b.get("min_confidence", 0.5)), tuple(b.get("types", ("jam", "spoof", "meacon"))),
                                   b.get("webhook"), b.get("secret"))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from None
        return {"id": gid}

    @app.get("/v1/alerts")
    def alerts(since: float = 0.0, x_api_key: str | None = Header(None)):
        need(x_api_key, "customer", "vetted")
        return {"alerts": svc.alerts(x_api_key, since)}

    @app.exception_handler(json.JSONDecodeError)
    async def bad_json(_, __):
        return JSONResponse({"detail": "invalid JSON"}, status_code=400)

    if web_dir and Path(web_dir).is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


def __getattr__(name: str):
    if name == "app":                       # built lazily so importing this module has no side effects
        return create_app()
    raise AttributeError(name)


__all__ = ["create_app", "privacy"]
