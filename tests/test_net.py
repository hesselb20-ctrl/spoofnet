"""Tests for cells, privacy, event validation, clustering, classification, localisation and ADS-B."""
import numpy as np
import pytest

from spoofnet.geo import ecef_to_lla, enu_to_ecef
from spoofnet.net import adsb, cells, privacy
from spoofnet.net.events import validate_event, validate_ping
from spoofnet.net.incidents import build_incidents, classify, cluster
from spoofnet.net.localize import Obs, inside_ellipse, jn_db, locate

LAT0, LON0 = 54.52, 18.80
T0 = 1_794_300_000


def _cell(e, n, res=10):
    lat, lon, _ = ecef_to_lla(enu_to_ecef(np.array([e, n, 0.0]), LAT0, LON0, 0.0))
    return cells.latlng_to_cell(float(lat), float(lon), res)


def _event(i, e, n, kind="jam", drop=8.0, tier="A", t=T0, score=0.99, claimed=None, saturated=False):
    return {"schema": 1, "token": f"{i:024x}", "tier": tier, "t_start": t, "t_end": t + 200, "cell": _cell(e, n),
            "pos_source": "last_trusted", "type": kind, "score": score, "reasons": ["CN0_DROP_UNIFORM"],
            "obs": {"d_cn0_db": None if saturated else drop, "d_cn0_spread_db": 0.9, "d_cn0_l5_db": None,
                    "d_cn0_min_db": 22.0 if saturated else 0.0, "saturated": saturated, "d_agc_db": None,
                    "sats_before": 12.0, "sats_min": 8.0, "bands": [], "claimed_cell": claimed},
            "evidence": "replay", "t_received": t + 3.0 + i * 0.5}


def test_cells_roundtrip_and_hierarchy():
    c10 = cells.latlng_to_cell(52.37, 4.90, 10)
    assert cells.is_valid(c10) and cells.resolution(c10) == 10
    lat, lon = cells.cell_centers([c10])[0]
    assert abs(lat - 52.37) < 0.002 and abs(lon - 4.90) < 0.002
    assert cells.resolution(cells.parent(c10, 6)) == 6
    assert c10 in cells.grid_disks([c10], 1)[0] and len(cells.grid_disks([c10], 1)[0]) == 7
    assert len(cells.cell_boundaries([c10])[0]) == 6
    assert not cells.is_valid("not-a-cell")


def test_token_matches_the_android_implementation():
    # Same vector as android/sdk/src/test/.../ContributorTokenTest.kt
    assert privacy.contributor_token(b"spoofnet-test-secret", 20000, "851f0000fffffff") == "4d6527761161e456731ed4bb"
    assert privacy.contributor_token(b"spoofnet-test-secret", 20001, "851f0000fffffff") == "3a7b15d6ef4def65e2a30093"
    with pytest.raises(ValueError):
        privacy.contributor_token(b"", 1, "851f0000fffffff")


def test_token_is_unlinkable_across_days_and_regions():
    s = b"0123456789abcdef0123456789abcdef"
    a = privacy.token_for_position(s, T0, 54.52, 18.80)
    assert a == privacy.token_for_position(s, T0 + 600, 54.521, 18.801)       # same day, same region
    assert a != privacy.token_for_position(s, T0 + 86400, 54.52, 18.80)       # next day
    assert a != privacy.token_for_position(s, T0, 52.37, 4.90)                # another region


def test_k_anonymity_filter():
    d = {"c1": ["a", "b", "c"], "c2": ["a", "a", "b"], "c3": ["a"]}
    assert set(privacy.k_anonymous(d, 3)) == {"c1"}


def test_event_validation_rejects_bad_input():
    good = _event(1, 100.0, 200.0)
    assert validate_event(good, now=T0 + 60)["cell"] == good["cell"]
    for patch in ({"token": "xyz"}, {"tier": "Z"}, {"type": "boom"}, {"score": 1.5}, {"cell": "abc"},
                  {"t_end": T0 - 5}, {"schema": 2}):
        with pytest.raises(ValueError):
            validate_event({**good, **patch}, now=T0 + 60)
    with pytest.raises(ValueError):
        validate_event(good, now=T0 + 30 * 86400)                              # too old
    bad_obs = {**good, "obs": {**good["obs"], "d_cn0_db": 500.0}}
    with pytest.raises(ValueError):
        validate_event(bad_obs, now=T0 + 60)
    ping = {"schema": 1, "token": "0" * 24, "cell7": _cell(0, 0, 7), "hour": T0 // 3600, "tier": "B", "seconds": 1800}
    assert validate_ping(ping)["seconds"] == 1800
    with pytest.raises(ValueError):
        validate_ping({**ping, "cell7": _cell(0, 0, 9)})


def test_cluster_links_near_and_simultaneous_only():
    evs = [_event(1, 0, 0), _event(2, 800, 300), _event(3, -600, 900),
           _event(4, 60_000, 0),                 # same time, far away
           _event(5, 100, 100, t=T0 + 7200)]     # same place, two hours later
    groups = sorted(sorted(g) for g in cluster(evs))
    assert groups == [[0, 1, 2], [3], [4]]


def test_one_or_two_devices_do_not_make_an_incident():
    assert build_incidents([_event(1, 0, 0)]) == []
    assert build_incidents([_event(1, 0, 0), _event(2, 300, 0)]) == []
    assert len(build_incidents([_event(1, 0, 0), _event(2, 300, 0), _event(3, 0, 400)])) == 1


def test_total_loss_alone_never_makes_an_incident():
    # Five cars losing GNSS in the same tunnel at the same time: no power evidence, no incident.
    evs = [_event(i, 50.0 * i, 0, kind="loss_unknown", saturated=True, score=0.2) for i in range(5)]
    assert build_incidents(evs) == []


def test_low_tier_devices_need_more_agreement():
    c = [_event(i, 200.0 * i, 0, tier="C") for i in range(3)]         # 3 x 0.4 = 1.2: just enough
    assert len(build_incidents(c, w_min=1.2)) == 1
    assert build_incidents(c[:3], w_min=1.5) == []


def test_classification_uses_shared_claimed_position():
    claim = _cell(5000, 5000, 9)
    evs = [_event(i, 400.0 * i, 100.0 * i, kind="spoof", claimed=claim) for i in range(3)]
    kind, conf, reasons = classify(evs)
    assert kind == "spoof" and "SHARED_CLAIMED_POSITION" in reasons and conf > 0.9
    kind, _, _ = classify([_event(i, 400.0 * i, 0) for i in range(3)])
    assert kind == "jam"
    evs = [_event(i, 400.0 * i, 100.0 * i, kind="meacon", claimed=claim) for i in range(3)]
    inc = build_incidents(evs)[0]
    assert inc.type == "meacon" and inc.source["method"] == "claimed_position"


def _synthetic_obs(rng, src, n_dev, n_exp, p_db, shadow, area=2500.0):
    obs = []
    for _ in range(n_dev):
        e, n = rng.uniform(-area, area, 2)
        r = max(np.hypot(e - src[0], n - src[1]), 10.0)
        x = p_db - 10 * n_exp * np.log10(r) + rng.normal(0, shadow)
        drop = 10 * np.log10(1 + 10 ** (x / 10)) + rng.normal(0, 0.8)
        if drop > 22:
            obs.append(Obs(e, n, "sat", 20.0))
        elif drop > 2.0:
            obs.append(Obs(e, n, "meas", drop))
        else:
            obs.append(Obs(e, n, "clean"))
    return obs


def test_localisation_recovers_a_known_source():
    rng = np.random.default_rng(3)
    errs, inside = [], []
    for _ in range(40):
        src = rng.uniform(-800, 800, 2)
        p_db = float(jn_db(10.0) + 20 * np.log10(700.0))            # 10 dB loss at 700 m
        est = locate(_synthetic_obs(rng, src, 25, 2.0, p_db, shadow=2.0))
        if est is None:
            continue
        errs.append(np.hypot(est["e"] - src[0], est["n"] - src[1]))
        inside.append(inside_ellipse(est, src[0], src[1]))
    assert len(errs) >= 35
    assert np.median(errs) < 150.0
    assert np.mean(inside) > 0.7


def test_localisation_needs_enough_observations():
    assert locate([Obs(0, 0, "meas", 8.0), Obs(100, 0, "clean")]) is None


def test_adsb_cross_check_states():
    c7 = _cell(0, 0, 7)
    c4 = cells.parent(c7, adsb.ADSB_RES)
    hour = T0 // 3600
    assert adsb.cross_check([c7], T0, T0 + 600, {})["status"] == "no_adsb_coverage"
    assert adsb.cross_check([c7], T0, T0 + 600, {(c4, hour): (3, 3)})["status"] == "no_adsb_coverage"
    assert adsb.cross_check([c7], T0, T0 + 600, {(c4, hour): (40, 12)})["status"] == "agrees"
    assert adsb.cross_check([c7], T0, T0 + 600, {(c4, hour): (40, 1)})["status"] == "not_seen_in_adsb"
