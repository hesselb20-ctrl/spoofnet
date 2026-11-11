"""Fit and measure the on-device detector in replay.

    python experiments/detector_pipeline.py --stage m2     # jamming detector v1
    python experiments/detector_pipeline.py --stage m3     # plus spoofing detectors
    python experiments/detector_pipeline.py --stage final  # large clean set for the false-alarm bound

Each stage evaluates on test scenarios that no earlier stage has touched.
Writes config/detector.json and results/<stage>_detector.json.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from spoofnet.detect.detector import PROFILES, DetectorConfig
from spoofnet.detect.features import Gates
from spoofnet.replay import calibration as cal
from spoofnet.replay.harness import run_many

STAGES = {
    # classes, test nominal index range, test attack index range, validation hours
    "m2": dict(classes=cal.JAM_CLASSES, test_nom=(5000, 5150), test_atk=(2000, 2150), val_nom=240),
    "m3": dict(classes=cal.JAM_CLASSES + cal.SPOOF_CLASSES, test_nom=(300, 600), test_atk=(300, 450), val_nom=600),
    # Same configuration as m3, fresh scenarios, sized for the false-alarm bound per environment.
    "final": dict(classes=cal.JAM_CLASSES + cal.SPOOF_CLASSES, test_nom=(1000, 2200), test_atk=(600, 700), val_nom=600),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=list(STAGES), required=True)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--train-atk", type=int, default=120)
    ap.add_argument("--val-atk", type=int, default=100)
    ap.add_argument("--reuse-config", action="store_true", help="skip fitting; evaluate config/detector.json")
    ap.add_argument("--skip-test", action="store_true", help="fit and choose rules only; leave the test split untouched")
    args = ap.parse_args()
    st = STAGES[args.stage]
    classes = st["classes"]
    log = {"stage": args.stage, "evidence": "replay", "timing_s": {}}
    t0 = time.time()

    if args.reuse_config:
        cfg = DetectorConfig.load("config/detector.json")
    else:
        # 1. gates from clean training data, extracted with freezing disabled
        clean = run_many(cal.nominal_jobs("train", range(120), 1200), Gates(), workers=args.workers)
        gates = cal.fit_gates(clean)
        del clean
        log["timing_s"]["gates"] = time.time() - t0
        print("gates", gates.to_dict(), flush=True)

        # 2 and 3. normalisation and fusion weights
        train = run_many(cal.nominal_jobs("train", range(200), 1800)
                         + cal.attack_jobs("train", classes, range(args.train_atk)), gates, workers=args.workers)
        tails_file = Path("config/real_tails.json")
        tails = json.loads(tails_file.read_text()) if tails_file.exists() and args.stage != "m2" else None
        norm, jam, spoof, meacon = cal.fit_models(train, with_spoof=any(c in cal.SPOOF_CLASSES for c in classes),
                                                  real_tails=tails["tails"] if tails else None)
        log["real_tails"] = tails
        log["train"] = {"scenarios": len(train), "nominal_hours": 200 * 0.5, "attacks_per_class": args.train_atk}
        del train
        cfg = DetectorConfig(gates, norm, jam, spoof, meacon=meacon)
        log["timing_s"]["fit"] = time.time() - t0

        # 4. event rules on validation data
        val = cal.evaluate(cal.nominal_jobs("val", range(st["val_nom"]), 3600)
                           + cal.attack_jobs("val", classes, range(args.val_atk)), cfg, workers=args.workers)
        log["val"] = {"nominal_hours": st["val_nom"], "attacks_per_class": args.val_atk, "jam_rule": {},
                      "jam_candidates": {}}
        for prof in PROFILES:      # each capability profile gets its own threshold and its own budget
            sub = [r for r in val if r["profile"] == prof]
            cfg.jam_rule[prof], table = cal.choose_rule(sub, "jam", ("jam_moderate",))
            log["val"]["jam_rule"][prof] = cfg.jam_rule[prof].to_dict()
            log["val"]["jam_candidates"][prof] = table
        if any(c in cal.SPOOF_CLASSES for c in classes):
            # Chosen for all five spoofing classes together. Choosing for the two target classes
            # alone picked a stricter threshold that cost a third of the drag-off, time-only and
            # meaconing detections for no measured gain (results/m3_detector_first_threshold.json).
            cfg.spoof_rule, spoof_table = cal.choose_rule(val, "spoof", cal.SPOOF_CLASSES)
            log["val"].update(spoof_rule=cfg.spoof_rule.to_dict(), spoof_candidates=spoof_table)
        del val
        cfg.provenance = {"stage": args.stage, "evidence": "replay", "fitted_on": "simulated train split",
                          "normal_ranges_widened_by_real_logs": bool(tails),
                          "rules_chosen_on": "simulated val split", "classes": list(classes)}
        cfg.save("config/detector.json")
        log["timing_s"]["rules"] = time.time() - t0
        print("jam rule", {k: v.to_dict() for k, v in cfg.jam_rule.items()}, "spoof rule", cfg.spoof_rule.to_dict(), flush=True)

    if args.skip_test:
        for prof, table in log["val"]["jam_candidates"].items():
            print(f"-- val, jam, profile {prof}: chosen {log['val']['jam_rule'][prof]}")
            for row in table:
                if row["k_on"] in (3, 8):
                    print(f"   p_on={row['p_on']:<7} k/m={row['k_on']}/{row['m_on']} fa={row['fa']:4d} in {row['hours']:.0f} h  "
                          f"moderate det={row['rate']*100:5.1f}%  ttd={row['ttd']}")
        for row in log["val"].get("spoof_candidates", []):
            if row["k_on"] in (3, 8):
                print(f"   spoof p_on={row['p_on']:<7} k/m={row['k_on']}/{row['m_on']} fa={row['fa']:4d} in {row['hours']:.0f} h  "
                      f"det={row['rate']*100:5.1f}%  ttd={row['ttd']}")
        for prof, m in cfg.jam.items():
            print(prof, {t: round(float(w), 2) for t, w in zip(m.terms, m.w)}, "b", round(m.b, 2))
        return

    # 5. held-out test
    a, b = st["test_nom"]
    c, d = st["test_atk"]
    test = cal.evaluate(cal.nominal_jobs("test", range(a, b), 3600) + cal.attack_jobs("test", classes, range(c, d)),
                        cfg, workers=args.workers)
    summary = cal.summarise(test)
    summary["roc"] = {"jam": cal.roc(test, "jam", [x for x in classes if x in cal.JAM_CLASSES], cfg.jam_rule)}
    sp = [x for x in classes if x in cal.SPOOF_CLASSES]
    if sp:
        summary["roc"]["spoof"] = cal.roc(test, "spoof", sp, cfg.spoof_rule)
    log["test"] = summary
    log["test_ranges"] = {"nominal_index": [a, b], "attack_index": [c, d]}
    log["config"] = cfg.to_dict()
    log["timing_s"]["total"] = time.time() - t0
    Path("results").mkdir(exist_ok=True)
    Path(f"results/{args.stage}_detector.json").write_text(json.dumps(log, indent=1, default=float))

    fa = summary["false_alarms"]
    print(f"\n== {args.stage} test (replay) ==")
    print(f"clean hours {fa['clean_hours']:.0f}  false alarms {fa['count']}  rate {fa['rate_per_hour']:.4f}/h  "
          f"upper95 {fa['upper95_per_hour']:.4f}/h  loss_unknown {fa['loss_unknown_per_hour']:.3f}/h")
    for name, s in summary["attacks"].items():
        print(f"{name:14s} n={s['n']:4d} det={s['rate']*100:5.1f}% [{s['ci95'][0]*100:.1f},{s['ci95'][1]*100:.1f}] "
              f"any={s['rate_any']*100:5.1f}% ttd med={s['ttd_median_s']:.0f}s p90={s['ttd_p90_s']:.0f}s "
              f"tiers={ {k: f'{v[0]}/{v[1]}' for k, v in sorted(s['by_tier'].items())} }")
    for env, v in fa["by_env"].items():
        if v["fa"]:
            print(f"  FA in {env}: {v['fa']} in {v['hours']:.0f} h")


if __name__ == "__main__":
    main()
