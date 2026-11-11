"""Milestone 6, step 2 of the validation plan: recorded phone logs.

Runs the detector on real GnssLogger-format logs.

  * On the logs as recorded: every alarm on a clean log is a false alarm on real
    phone behaviour.
  * With synthetic jamming injected into the recorded measurements: detection on
    real noise, real satellite geometry and real phone quirks.

Both are replay evidence. Neither is a detection of real interference.

    python experiments/m6_recorded_logs.py <folder with .txt logs> [--out results/m6_recorded_logs.json]

When a broadcast-ephemeris file (*.rnx) sits next to a log, satellite positions
are attached and the ephemeris-assisted spoofing checks run too. Without one,
only the checks that need no satellite position run. Spoofing is never injected
into recorded logs here: that needs a trusted true position.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from spoofnet.detect.detector import DetectorConfig, detect
from spoofnet.detect.features import extract, fit_device_baseline
from spoofnet.io import rinex_nav
from spoofnet.io.gnsslogger import read_log
from spoofnet.replay import scoring
from spoofnet.sim.inject import JamSpec, apply_attacks

SEGMENT_S = 900            # logs are cut into segments of this length for the injection runs
JAMS = (("L1_NARROW", 8.0), ("L1_WIDE", 10.0), ("ALL_BANDS", 10.0), ("L1_NARROW", 13.0))


def segment(ms, a: int, b: int):
    out = ms.copy()
    for k, v in list(out.__dict__.items()):
        if isinstance(v, np.ndarray) and v.shape[:1] == (ms.n_epochs,):
            setattr(out, k, v[a:b].copy())
    out.t = out.t - out.t[0]
    out.clk_disc = out.clk_disc - out.clk_disc[0]
    return out


def analyse(path: Path, cfg: DetectorConfig, rng) -> dict:
    ms = read_log(path)
    trk = np.isfinite(ms.cn0)
    nav_files = sorted(path.parent.glob("*.rnx"))
    eph = rinex_nav.attach(ms, rinex_nav.read_nav(nav_files[0])) if nav_files else None
    info = {"file": f"{path.parent.name}/{path.name}", "phone": ms.meta.get("header", ""), "ephemeris": eph,
            "epochs": ms.n_epochs, "signals": ms.n_signals, "dual": ms.meta["dual"],
            "agc_usable": ms.meta["has_agc"], "has_elevation": bool(np.isfinite(ms.el).any()),
            "median_tracked": float(np.median(trk.sum(axis=1))), "median_cn0": float(np.nanmedian(ms.cn0)),
            "capability": ms.meta.get("capability")}
    if ms.n_epochs < 300 or info["median_tracked"] < 5:
        info["skipped"] = "too short or too few signals"
        return info
    ms.meta["tier"] = "A" if ms.meta["has_agc"] and ms.meta["dual"] else "B" if ms.meta["has_agc"] or ms.meta["dual"] else "C"
    # Injection must not drop signals this phone demonstrably tracks: use its own lowest levels.
    seen = ms.cn0[np.isfinite(ms.cn0)]
    ms.meta["device"] = {"track_thr": float(np.percentile(seen, 1.0)) - 0.5, "acq_margin": 1.0, "acq_delay": 2,
                         "cn0_quant": 0.1}
    # The phone's own normal comes from the start of the log, as it would from its stored history.
    cal_n = min(1200, ms.n_epochs // 3)
    base = fit_device_baseline(segment(ms, 0, cal_n))
    info["baseline_from_first_s"] = cal_n
    x = extract(ms, base, cfg.gates).x
    events = detect(x, cfg)
    alarms = [e for e in events if e["type"] != "loss_unknown"]
    hours = max(ms.n_epochs - cfg.warmup_s, 0) / 3600.0
    info.update(clean_hours=hours, alarms=[{"type": e["type"], "t": e["start"], "end": e["end"], "score": e["score"],
                                             "reasons": e["reasons"]} for e in alarms],
                clock_discontinuities=int(ms.clk_disc[-1] - ms.clk_disc[0]),
                loss_unknown=sum(1 for e in events if e["type"] == "loss_unknown"), baseline=base.to_dict(), injected=[])
    for i, a in enumerate(range(0, ms.n_epochs - SEGMENT_S + 1, SEGMENT_S)):
        kind, drop = JAMS[i % len(JAMS)]
        seg = segment(ms, a, a + SEGMENT_S)
        if np.isfinite(seg.cn0[300:600]).sum(axis=1).min() < 4:
            continue                                     # the phone had no signal there anyway
        apply_attacks(seg, [JamSpec(360, 600, drop_db=drop, kind=kind, ramp_s=3.0)], rng)
        xs = extract(seg, base, cfg.gates).x
        evs = detect(xs, cfg)
        y = np.zeros(SEGMENT_S, dtype=np.int8)
        y[360:600] = 1
        sc = scoring.score_scenario(evs, y, cfg.warmup_s)["attacks"][0]
        info["injected"].append({"kind": kind, "drop_db": drop, "detected": sc["detected"], "ttd_s": sc["ttd"],
                                 "loss_unknown": sc["loss_unknown"]})
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default="results/m6_recorded_logs.json")
    ap.add_argument("--exclude", nargs="*", default=[], help="folder names of logs that are not known to be clean")
    args = ap.parse_args()
    cfg = DetectorConfig.load("config/detector.json")
    rng = np.random.default_rng(11)
    files = sorted(p for p in Path(args.folder).rglob("*.txt") if p.parent.name not in args.exclude)
    rows = []
    for p in files:
        try:
            rows.append(analyse(p, cfg, rng))
        except Exception as exc:                          # one unreadable file must not stop the run
            rows.append({"file": p.name, "skipped": f"{type(exc).__name__}: {exc}"})
        print(rows[-1]["file"], rows[-1].get("skipped") or f"{rows[-1]['clean_hours']:.2f} h, {len(rows[-1]['alarms'])} alarms",
              flush=True)
    used = [r for r in rows if "skipped" not in r]
    hours = sum(r["clean_hours"] for r in used)
    n_alarm = sum(len(r["alarms"]) for r in used)
    inj = [i for r in used for i in r["injected"]]
    det = sum(i["detected"] for i in inj)
    lo, hi = scoring.wilson(det, len(inj)) if inj else (float("nan"), float("nan"))
    summary = {
        "evidence": "replay (recorded clean logs, synthetic jamming injected)",
        "logs_used": len(used), "logs_skipped": len(rows) - len(used), "excluded_folders": args.exclude,
        "clean_hours": hours,
        "alarms_on_clean_logs": n_alarm, "alarm_rate_per_hour": n_alarm / max(hours, 1e-9),
        "alarm_rate_upper95_per_hour": scoring.poisson_upper(n_alarm, hours) if hours > 0 else None,
        "injected_runs": len(inj), "injected_detected": det, "injected_detection_rate": det / max(len(inj), 1),
        "injected_ci95": [lo, hi],
        "by_kind": {k: [sum(i["detected"] for i in inj if i["kind"] == k), sum(1 for i in inj if i["kind"] == k)]
                    for k in sorted({i["kind"] for i in inj})},
        "with_agc": sum(1 for r in used if r["agc_usable"]), "dual_frequency": sum(1 for r in used if r["dual"]),
        "logs_with_ephemeris": sum(1 for r in used if r.get("ephemeris")),
        "alarms_by_type": {t: sum(1 for r in used for a in r["alarms"] if a["type"] == t) for t in ("jam", "spoof", "meacon")},
        "not_covered": "spoofing injection (needs a trusted true position); ephemeris-assisted checks on logs without an ephemeris file",
        "logs": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=1, default=float))
    print(json.dumps({k: v for k, v in summary.items() if k != "logs"}, indent=1, default=float))


if __name__ == "__main__":
    main()
