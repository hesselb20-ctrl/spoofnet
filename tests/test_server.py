"""Tests for the service layer, publication rules and the HTTP API."""
import json

import numpy as np
import pytest

from spoofnet.geo import ecef_to_lla, enu_to_ecef
from spoofnet.net import cells, privacy
from spoofnet.server import publication
from spoofnet.server.service import Service, cells_geojson, save_snapshot, sign_webhook

LAT0, LON0 = 54.52, 18.80
NOW = 1_794_300_000.0


def _latlon(e, n):
    lat, lon, _ = ecef_to_lla(enu_to_ecef(np.array([e, n, 0.0]), LAT0, LON0, 0.0))
    return float(lat), float(lon)


def _event(i, e, n, kind="jam", t=None, drop=9.0, tier="A"):
    lat, lon = _latlon(e, n)
    t = int(NOW - 3600 if t is None else t)
    return {"schema": 1, "token": f"{i:024x}", "tier": tier, "t_start": t, "t_end": t + 240,
            "cell": cells.latlng_to_cell(lat, lon, 10), "pos_source": "last_trusted", "type": kind, "score": 0.99,
            "reasons": ["CN0_DROP_UNIFORM", "AGC_DROP"],
            "obs": {"d_cn0_db": drop, "d_cn0_spread_db": 0.8, "saturated": False, "sats_before": 14, "sats_min": 9,
                    "bands": ["L1_ONLY"], "claimed_cell": None}, "evidence": "replay"}


def _ping(i, e, n, hour=None, tier="A"):
    lat, lon = _latlon(e, n)
    return {"schema": 1, "token": f"{i:024x}", "cell7": cells.latlng_to_cell(lat, lon, 7),
            "hour": int((NOW - 3600) // 3600 if hour is None else hour), "tier": tier, "seconds": 3000}


@pytest.fixture()
def svc():
    s = Service(":memory:")
    evs = [_event(i, 300.0 * i, 200.0 * (i % 3), drop=14.0 - 2 * i) for i in range(5)]
    assert s.ingest_events(evs, NOW - 3000)["accepted"] == 5
    s.ingest_pings([_ping(i, 300.0 * i, 200.0 * (i % 3)) for i in range(5)] + [_ping(20 + i, 9000.0, 9000.0) for i in range(6)])
    s.rebuild(NOW - 2900)
    return s


def test_ingest_rejects_bad_records_and_duplicates(svc):
    res = svc.ingest_events([_event(1, 300.0, 200.0), {"schema": 1, "token": "bad"}], NOW - 3000)
    assert res["accepted"] == 0 and len(res["rejected"]) == 1 and res["rejected"][0]["index"] == 1
    assert svc.ingest_pings([{"schema": 1}])["rejected"]


def test_incident_is_built_and_views_differ_by_tier(svc):
    incs = svc.incidents(NOW - 7200, NOW)
    assert len(incs) == 1 and incs[0]["type"] == "jam" and incs[0]["n_devices"] == 5
    pub = svc.incidents_for("public", NOW - 7200, NOW, NOW)
    cust = svc.incidents_for("customer", NOW - 7200, NOW, NOW)
    vet = svc.incidents_for("vetted", NOW - 7200, NOW, NOW)
    assert len(pub) == len(cust) == len(vet) == 1
    assert pub[0]["cell_res"] == 6 and all(cells.resolution(c) == 6 for c in pub[0]["cells"])
    assert "source" not in pub[0] and "source" not in cust[0] and "reasons" not in pub[0]
    assert pub[0]["devices"] == "3-5"                                  # a band, not the exact count
    assert pub[0]["t_start"] % 300 == 0 and pub[0]["evidence"] == "replay"
    assert vet[0]["source"] is not None and "lat" in vet[0]["source"]
    assert pub[0]["coverage"] in ("some", "good")


def test_public_view_is_delayed_and_needs_k_contributors(svc):
    assert svc.incidents_for("public", NOW - 7200, NOW, now=NOW - 2800) == []        # inside the delay
    small = Service(":memory:")
    small.ingest_events([_event(i, 300.0 * i, 0.0) for i in range(3)], NOW - 3000)
    small.rebuild(NOW - 2900)
    inc = small.incidents(NOW - 7200, NOW)[0]
    strict = publication.Rules({**publication.DEFAULT, "k": 4})
    assert publication.view(inc, "public", strict, NOW) is None
    assert publication.view(inc, "customer", strict, NOW) is not None


def test_region_rules_restrict_and_disable(svc):
    inc = svc.incidents(NOW - 7200, NOW)[0]
    c5 = cells.parent(inc["cells8"][0], 5)
    restricted = publication.Rules(regions=[{"name": "r", "mode": "restricted", "cells5": [c5]}])
    assert publication.view(inc, "public", restricted, NOW) is None                    # six-hour delay not over
    late = publication.view(inc, "public", restricted, NOW + 7 * 3600)
    assert late["cell_res"] == 5
    off = publication.Rules(regions=[{"name": "n", "mode": "no_collection", "cells5": [c5]}])
    assert publication.view(inc, "vetted", off, NOW) is None
    blocked = Service(":memory:", off)
    res = blocked.ingest_events([_event(1, 0.0, 0.0)], NOW - 3000)
    assert res["accepted"] == 0 and "disabled" in res["rejected"][0]["error"]


def test_coverage_hides_cells_below_k(svc):
    cov = svc.coverage(NOW - 7200, NOW)
    assert cov and all(v["level"] in ("some", "good") for v in cov.values())
    lonely = Service(":memory:")
    lonely.ingest_pings([_ping(1, 0.0, 0.0), _ping(2, 50.0, 0.0)])
    assert lonely.coverage(NOW - 7200, NOW) == {}                       # two contributors: shown as no data


def test_old_event_cells_are_coarsened(svc):
    svc.rebuild(NOW + 2 * 3600)
    res = {cells.resolution(r["cell"]) for r in svc.db.execute("SELECT cell FROM events")}
    assert res == {privacy.STORE_RES}


def test_geofence_alert_fires_once_and_reports_coverage(svc):
    svc.add_key("k-cust", "customer", "port")
    gid = svc.add_geofence("k-cust", "Port approach", LAT0, LON0, radius_km=8, min_confidence=0.5)
    new = svc.rebuild(NOW - 2800)
    assert len(new) == 1 and new[0]["geofence_id"] == gid
    assert 0.0 <= new[0]["body"]["geofence_coverage_share"] <= 1.0 and "source" not in new[0]["body"]["incident"]
    assert svc.rebuild(NOW - 2700) == []                                # not raised twice
    assert len(svc.alerts("k-cust")) == 1 and svc.alerts("other-key") == []
    far = svc.add_geofence("k-cust", "Elsewhere", LAT0 + 3.0, LON0, radius_km=5)
    assert all(a["geofence_id"] != far for a in svc.rebuild(NOW - 2600))
    assert len(sign_webhook("s", b"{}")) == 64


def test_export_risk_and_snapshot(svc, tmp_path):
    csv = svc.export_csv("customer", NOW - 7200, NOW, NOW)
    assert csv.splitlines()[0].startswith("id,type,confidence,evidence") and len(csv.splitlines()) == 2
    risk = svc.risk_heatmap(int(NOW // 86400))
    assert any(v["incident_minutes_weighted"] > 0 for v in risk.values())
    assert all(v["coverage"] in ("none", "some", "good") for v in risk.values())
    fc = cells_geojson({cells.latlng_to_cell(LAT0, LON0, 6): {"level": "good"}})
    ring = fc["features"][0]["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 7
    meta = save_snapshot(svc, tmp_path, NOW - 6 * 3600, NOW, NOW)
    assert (tmp_path / "incidents.geojson").exists() and len(meta["slots"]) >= 6
    assert "replay" in meta["evidence_note"].lower()
    assert json.loads((tmp_path / "incidents.geojson").read_text())["features"]


def test_http_api_tiers_and_limits(svc):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from spoofnet.server.app import create_app

    svc.add_key("k-vet", "vetted", "authority")
    svc.add_key("k-cust", "customer", "fleet")
    client = TestClient(create_app(svc, web_dir=None, clock=lambda: NOW))
    assert client.get("/v1/public/meta").json()["k"] == 3
    pub = client.get("/v1/public/incidents?hours=24").json()
    assert pub["count"] == 1 and pub["features"][0]["properties"]["type"] == "jam"
    assert "source" not in json.dumps(pub)
    assert client.get("/v1/public/coverage").json()["type"] == "FeatureCollection"
    q = f"/v1/incidents?t0={NOW - 7200}&t1={NOW}"
    assert client.get(q).status_code == 403
    assert "source" not in client.get(q, headers={"X-API-Key": "k-cust"}).json()["incidents"][0]
    assert client.get(q, headers={"X-API-Key": "k-vet"}).json()["incidents"][0]["source"]["method"]
    assert client.get(f"/v1/export.csv?t0={NOW - 7200}&t1={NOW}", headers={"X-API-Key": "k-cust"}).text.count("\n") == 2
    r = client.post("/v1/geofences", headers={"X-API-Key": "k-cust"},
                    json={"name": "Port", "lat": LAT0, "lon": LON0, "radius_km": 6})
    assert r.status_code == 200 and r.json()["id"] >= 1
    assert client.post("/v1/geofences", headers={"X-API-Key": "k-cust"}, json={"name": "x"}).status_code == 400
    up = client.post("/v1/events", json=[_event(7, 100.0, 100.0, t=NOW - 600)])
    assert up.status_code == 200 and up.json()["accepted"] == 1
    assert client.post("/v1/events", json={"not": "a list"}).status_code == 400
    assert client.post("/v1/coverage", json=[_ping(7, 100.0, 100.0)]).json()["accepted"] == 1
    assert len(client.get("/v1/alerts", headers={"X-API-Key": "k-cust"}).json()["alerts"]) >= 1
