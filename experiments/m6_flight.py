"""Milestone 6, step 3: one passive real-world log from a documented interference area.

The public dataset Zenodo 14712684 (Takiguchi Medina and Lohan, CC BY 4.0) holds a
GnssLogger trace recorded by a passenger on a flight from Riga to Tampere on
22 March 2024. The route crosses Estonia and the Gulf of Finland, where aircraft
reported GNSS interference almost daily in spring 2024. The dataset authors note
that this is the one folder where interference may be present.

This script runs the detector on that log exactly as configured (no refitting),
bins the phone's own measurements along the track, and puts them next to the
share of aircraft that reported low navigation accuracy in the same map cells on
the same day (GPSJam daily data, looked up by hand and stored below).

    python experiments/m6_flight.py <path to FLIGHT/gnss_log_*.txt>

Writes results/m6_flight.json. This is one flight and one phone. It is an
observation, not a detection rate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from spoofnet.detect.detector import DetectorConfig, detect, probabilities
from spoofnet.detect.features import IDX, extract, fit_device_baseline
from spoofnet.geo import ecef_to_lla
from spoofnet.io.gnsslogger import read_log
from spoofnet.net import cells

# GPSJam daily file for 2024-03-22, H3 resolution 4: cell -> (aircraft with good accuracy,
# aircraft with low accuracy). Looked up on 11 November 2026 from
# https://gpsjam.org/data/2024-03-22-h3_4.csv. Cells not looked up are absent.
GPSJAM_2024_03_22 = {
    "841f607ffffffff": (99, 0),
    "841f609ffffffff": (65, 4),
    "841f65dffffffff": (75, 16),
    "84089a1ffffffff": (62, 11),
    "84089bdffffffff": (86, 27),
    "84089b9ffffffff": (95, 23),
    "8408991ffffffff": (66, 2),
    "841124dffffffff": (17, 0),
    "8411249ffffffff": (20, 1),
}
BIN_S = 300


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--out", default="results/m6_flight.json")
    args = ap.parse_args()
    cfg = DetectorConfig.load("config/detector.json")
    ms = read_log(args.log)
    ms.meta["tier"] = "A" if ms.meta["has_agc"] and ms.meta["dual"] else "B" if ms.meta["has_agc"] or ms.meta["dual"] else "C"
    n = ms.n_epochs

    # The phone's own normal: fitted on the 20 minutes at the gate before take-off only.
    ground = ms.copy()
    for k, v in list(ground.__dict__.items()):
        if isinstance(v, np.ndarray) and v.shape[:1] == (n,):
            setattr(ground, k, v[:1200].copy())
    base = fit_device_baseline(ground)
    x = extract(ms, base, cfg.gates).x
    pj, ps, e = probabilities(x, cfg)
    events = detect(x, cfg, (pj, ps, e))

    agc0 = float(np.nanmedian(ms.agc[:1200, 0]))
    top3_0 = float(np.nanmedian(np.sort(np.where(np.isfinite(ms.cn0[:1200]), ms.cn0[:1200], -1), axis=1)[:, -3:]))
    rows = []
    for a in range(0, n, BIN_S):
        sl = slice(a, min(a + BIN_S, n))
        fx = ms.fix_ecef[sl]
        ok = np.all(np.isfinite(fx), axis=1)
        if not ok.any():
            continue
        lat, lon, alt = (float(np.median(v)) for v in ecef_to_lla(fx[ok]))
        cell = cells.latlng_to_cell(lat, lon, 4)
        c = ms.cn0[sl]
        top3 = float(np.nanmedian(np.sort(np.where(np.isfinite(c), c, -1), axis=1)[:, -3:]))
        good_bad = GPSJAM_2024_03_22.get(cell)
        rows.append({
            "minute": a // 60, "lat": round(lat, 2), "lon": round(lon, 2), "alt_m": round(alt),
            "tracked_signals": float(np.median(np.isfinite(c).sum(axis=1))),
            "cn0_top3_change_db": round(top3 - top3_0, 1),
            "agc_change_db": round(float(np.nanmedian(ms.agc[sl, 0])) - agc0, 1),
            "fix_accuracy_m": round(float(np.nanmedian(ms.fix_acc[sl][ok])), 1),
            "p_jam_median": round(float(np.median(pj[sl])), 3), "p_spoof_median": round(float(np.median(ps[sl])), 3),
            "baseline_frozen_share": round(float(np.mean(x[sl, IDX["frozen"]])), 2),
            "h3_res4": cell,
            "adsb_aircraft": None if good_bad is None else sum(good_bad),
            "adsb_low_accuracy_share": None if good_bad is None else round(good_bad[1] / sum(good_bad), 3),
        })
    out = {
        "evidence": "real (one flight, one phone; detector thresholds fitted in replay and not refitted)",
        "source": "Zenodo 10.5281/zenodo.14712684, FLIGHT folder, CC BY 4.0",
        "phone": ms.meta.get("header", ""), "tier": ms.meta["tier"], "duration_min": round(n / 60, 1),
        "baseline_from": "first 20 minutes, on the ground", "baseline": base.to_dict(),
        "adsb_source": "GPSJam daily data for 2024-03-22, H3 res 4, looked up by hand",
        "events": [{"type": ev["type"], "minute_start": round(ev["start"] / 60, 1), "minute_end": round(ev["end"] / 60, 1),
                    "score": round(ev["score"], 4), "reasons": ev["reasons"]} for ev in events],
        "track": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1, default=float))
    print(f"{'min':>4} {'lat':>6} {'alt':>6} {'trk':>4} {'dCN0':>5} {'dAGC':>5} {'acc':>5} {'p_jam':>6} {'p_spf':>6} {'frz':>4} {'ADS-B low-accuracy share'}")
    for r in rows:
        ad = "not looked up" if r["adsb_aircraft"] is None else f"{r['adsb_low_accuracy_share']*100:4.0f}% of {r['adsb_aircraft']}"
        print(f"{r['minute']:4d} {r['lat']:6.2f} {r['alt_m']:6d} {r['tracked_signals']:4.0f} {r['cn0_top3_change_db']:5.1f} "
              f"{r['agc_change_db']:5.1f} {r['fix_accuracy_m']:5.1f} {r['p_jam_median']:6.3f} {r['p_spoof_median']:6.3f} "
              f"{r['baseline_frozen_share']:4.2f} {ad}")
    for ev in out["events"]:
        print("event", ev)
    if not out["events"]:
        print("no events raised")


if __name__ == "__main__":
    main()
