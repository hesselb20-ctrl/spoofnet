"""Tests for geometry, the solver, the simulator, injection, log I/O and scoring."""
import numpy as np
import pytest

from spoofnet import geo, pvt
from spoofnet.data import LOWER, UPPER
from spoofnet.detect.fusion import EventRule, events_from_prob
from spoofnet.io.gnsslogger import read_log, write_log
from spoofnet.replay import scoring
from spoofnet.sim import catalog
from spoofnet.sim.inject import JamSpec, SpoofSpec
from spoofnet.sim.scenario import ScenarioSpec, constellation, simulate


def test_lla_ecef_roundtrip():
    lat, lon, h = np.array([52.1, -33.9, 0.0, 89.0]), np.array([5.2, 151.2, -170.0, 10.0]), np.array([10.0, 500.0, 0.0, 3000.0])
    la, lo, hh = geo.ecef_to_lla(geo.lla_to_ecef(lat, lon, h))
    assert np.allclose(la, lat, atol=1e-9) and np.allclose(lo, lon, atol=1e-9) and np.allclose(hh, h, atol=1e-3)


def test_enu_roundtrip_and_az_el():
    enu = np.array([[100.0, -250.0, 30.0]])
    xyz = geo.enu_to_ecef(enu, 54.5, 18.8, 0.0)
    assert np.allclose(geo.ecef_to_enu(xyz, 54.5, 18.8, 0.0), enu, atol=1e-6)
    rx = geo.lla_to_ecef(54.5, 18.8, 0.0)[None, :]
    up = geo.lla_to_ecef(54.5, 18.8, 20_000_000.0)[None, None, :]
    _, el = geo.az_el(rx, up)
    assert el[0, 0] == pytest.approx(90.0, abs=1e-4)
    north = geo.enu_to_ecef(np.array([[0.0, 1000.0, 0.0]]), 54.5, 18.8, 0.0)[None]
    az, el = geo.az_el(rx, north)
    assert az[0, 0] == pytest.approx(0.0, abs=1e-6) and abs(el[0, 0]) < 0.01


def test_constellation_orbits_are_physical():
    con = constellation()
    t = np.array([0.0, 1.0])
    p, v = con.states(t)
    radius = np.linalg.norm(p[0], axis=1)
    assert np.allclose(radius, con.a, rtol=1e-9)
    # finite-difference velocity matches the analytic one
    assert np.allclose((p[1] - p[0]), v[0], atol=1.0)
    assert len(con.svid) == 31 + 24 + 24 + 24


def test_open_sky_fix_is_metre_level():
    ms = simulate(ScenarioSpec(seed=42, env="open_static", duration=180, archetype="flagship_dual_agc"))
    err = np.linalg.norm(ms.fix_ecef - ms.truth["pos"], axis=1)
    assert np.nanmedian(err) < 5.0
    assert np.isfinite(ms.cn0).sum(axis=1).min() >= 20


def test_group_solutions_agree_when_clean():
    ms = simulate(ScenarioSpec(seed=43, env="open_static", duration=120, archetype="flagship_dual_agc"))
    sols = pvt.solve_groups(ms, ms.fix_ecef)
    assert {"G1", "E1", "R1", "C1"} <= set(sols)
    for s in sols.values():
        ok = s.ok & (s.n >= 5)
        assert np.median(np.linalg.norm(s.x[ok] - ms.truth["pos"][ok], axis=1)) < 25.0


def _pair(attack, seed=7, env="open_static", arch="flagship_dual_agc", dur=600):
    dev = catalog.make_device(seed, archetype=arch)
    clean = simulate(ScenarioSpec(seed=seed, env=env, duration=dur, device=dev))
    hit = simulate(ScenarioSpec(seed=seed, env=env, duration=dur, device=dev, attacks=[attack]))
    return clean, hit


def test_narrow_jam_drops_l1_and_leaves_l5():
    clean, hit = _pair(JamSpec(300, 500, drop_db=10.0, kind="L1_NARROW", ramp_s=2.0))
    w = slice(320, 480)
    l1 = clean.sig_sub == 0
    both = np.isfinite(clean.cn0[w]) & np.isfinite(hit.cn0[w])
    d = np.where(both, clean.cn0[w] - hit.cn0[w], np.nan)
    assert np.nanmedian(d[:, l1]) == pytest.approx(10.0, abs=1.2)
    assert abs(np.nanmedian(d[:, clean.sig_band == LOWER])) < 0.2
    assert np.nanmedian(clean.agc[w, UPPER] - hit.agc[w, UPPER]) > 2.0          # more power: AGC falls
    assert abs(np.nanmedian(clean.agc[w, LOWER] - hit.agc[w, LOWER])) < 0.2
    before = slice(100, 290)
    assert np.allclose(np.nan_to_num(clean.cn0[before]), np.nan_to_num(hit.cn0[before]))


def test_all_band_jam_drops_both_bands():
    clean, hit = _pair(JamSpec(300, 500, drop_db=12.0, kind="ALL_BANDS"))
    w = slice(320, 480)
    both = np.isfinite(clean.cn0[w]) & np.isfinite(hit.cn0[w])
    d = np.where(both, clean.cn0[w] - hit.cn0[w], np.nan)
    assert np.nanmedian(d[:, clean.sig_band == LOWER]) > 6.0


def test_multi_constellation_spoof_moves_the_fix_and_one_constellation_does_not():
    off = (3000.0, 4000.0)
    _, multi = _pair(SpoofSpec(300, 500, kind="multi", consts="GERC", offset_enu=off, time_off_m=500.0))
    _, simple = _pair(SpoofSpec(300, 500, kind="simple", consts="G", offset_enu=off, time_off_m=500.0))
    w = slice(330, 480)
    e_multi = np.nanmedian(np.linalg.norm(multi.fix_ecef[w] - multi.truth["pos"][w], axis=1))
    e_simple = np.nanmedian(np.linalg.norm(simple.fix_ecef[w] - simple.truth["pos"][w], axis=1))
    assert e_multi == pytest.approx(5000.0, rel=0.02)
    assert e_simple < 50.0                       # the receiver stays with the consistent majority
    g = (simple.sig_const == 0) & (simple.sig_band == UPPER)
    # Flat power on the false signals. Robust spread, as in the detector: authentic stragglers
    # near the horizon stay tracked and must not hide the flat set.
    x = simple.cn0[w][:, g]
    mad = 1.4826 * np.nanmedian(np.abs(x - np.nanmedian(x, axis=1, keepdims=True)), axis=1)
    assert np.nanmedian(mad) < 1.5


def test_log_roundtrip(tmp_path):
    ms = simulate(ScenarioSpec(seed=9, env="open_car", duration=90, archetype="flagship_dual_agc"))
    path = tmp_path / "log.txt"
    write_log(ms, path, almanac=constellation().to_dict())
    back = read_log(path)
    assert back.n_epochs == ms.n_epochs
    key = lambda m: {(int(c), int(s), int(b)): i for i, (c, s, b) in enumerate(zip(m.sig_const, m.sig_svid, m.sig_band))}
    ka, kb = key(ms), key(back)
    assert set(kb) <= set(ka) and len(kb) >= 20
    ia = np.array([ka[k] for k in kb])
    ib = np.array([kb[k] for k in kb])
    trk = np.isfinite(ms.cn0[:, ia])
    assert np.array_equal(trk, np.isfinite(back.cn0[:, ib]))
    assert np.nanmax(np.abs(ms.pr[:, ia] - back.pr[:, ib])) < 0.5            # 1 ns quantisation is 0.3 m
    assert np.nanmax(np.abs(ms.cn0[:, ia] - back.cn0[:, ib])) < 0.011
    assert np.nanmax(np.abs(ms.prr[:, ia] - back.prr[:, ib])) < 1e-3
    assert np.nanmax(np.abs(ms.el[:, ia] - back.el[:, ib])[trk]) < 0.011
    assert np.nanmax(np.abs(ms.agc - back.agc)) < 0.011
    assert np.nanmax(np.linalg.norm(ms.fix_ecef - back.fix_ecef, axis=1)) < 0.05
    assert back.sat_pos is not None
    assert np.allclose(back.sat_pos[:, back.sig_sat[ib]], ms.sat_pos[:, ms.sig_sat[ia]], atol=1e-3)


def test_reader_ignores_unknown_columns_and_order(tmp_path):
    path = tmp_path / "other.txt"
    path.write_text(
        "# Raw,Svid,ConstellationType,TimeNanos,FullBiasNanos,BiasNanos,utcTimeMillis,State,ReceivedSvTimeNanos,"
        "Cn0DbHz,PseudorangeRateMetersPerSecond,CarrierFrequencyHz,Extra\n"
        "Raw,5,1,1000000000000,-1451520000000000000,0.0,1700000000000,16399,999930000000,41.5,-120.5,1575420000,x\n"
        "Raw,5,1,1001000000000,-1451520000000000000,0.0,1700000001000,16399,1000930000000,41.0,-120.4,1575420000,x\n")
    ms = read_log(path)
    assert ms.n_epochs == 2 and ms.n_signals == 1
    assert ms.cn0[0, 0] == 41.5 and ms.pr[0, 0] == pytest.approx(0.07 * geo.C, rel=1e-9)


def test_events_need_persistence_and_merge():
    p = np.zeros(400)
    p[100] = 1.0                      # single spike: no event
    p[200:260] = 0.99
    p[270:300] = 0.99                 # 10 s gap: merged with the previous event
    ev = events_from_prob(p, EventRule(p_on=0.9, k_on=4, m_on=6, p_off=0.4, t_off=10, merge_s=30), warmup=0)
    assert len(ev) == 1 and ev[0][0] == 203 and ev[0][1] == 300
    assert events_from_prob(p, EventRule(p_on=0.9, k_on=4, m_on=6), warmup=350) == []


def test_scoring_counts_detections_and_false_alarms():
    y = np.zeros(900, dtype=np.int8)
    y[300:500] = 1
    events = [{"type": "jam", "start": 150, "end": 160, "score": 0.9, "reasons": []},      # false alarm
              {"type": "jam", "start": 306, "end": 505, "score": 0.99, "reasons": []},     # detection, 6 s
              {"type": "loss_unknown", "start": 700, "end": 720, "score": 0.2, "reasons": []}]
    s = scoring.score_scenario(events, y)
    assert len(s["false_alarms"]) == 1 and s["loss_unknown"] == 1
    assert s["attacks"][0]["detected"] and s["attacks"][0]["ttd"] == 6.0
    assert s["clean_s"] == 900 - 90 - (200 + scoring.PRE_S + scoring.POST_S)
    lo, hi = scoring.wilson(95, 100)
    assert 0.88 < lo < 0.95 < hi < 0.99
    assert scoring.poisson_upper(0, 300.0) == pytest.approx(3.0 / 300.0, rel=0.01)
