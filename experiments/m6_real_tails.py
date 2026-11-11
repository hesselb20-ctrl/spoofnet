"""Measure, on real clean phone logs, how far each detector quantity strays from the
simulated clean median, and write the widest tails to config/real_tails.json.

The detector fit then uses, for every quantity, the wider of the simulated and the real
tail as its "normal range" (spoofnet.detect.fusion.fit_norm). This is how real phone
behaviour that the simulator does not reproduce is kept from raising alarms.

    python experiments/m6_real_tails.py <folder with logs>

The reference medians come from a detector configuration fitted on simulated data only
(results/m3_detector_sim_only.json), so re-running this after a refit gives the same file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from m6_recorded_logs import segment                      # noqa: E402
from m6_term_audit import NOT_CLEAN                       # noqa: E402
from spoofnet.detect import fusion                        # noqa: E402
from spoofnet.detect.detector import DetectorConfig       # noqa: E402
from spoofnet.detect.features import extract, fit_device_baseline   # noqa: E402
from spoofnet.io import rinex_nav                         # noqa: E402
from spoofnet.io.gnsslogger import read_log               # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--reference", default="results/m3_detector_sim_only.json")
    ap.add_argument("--out", default="config/real_tails.json")
    args = ap.parse_args()
    cfg = DetectorConfig.from_dict(json.loads(Path(args.reference).read_text())["config"])
    per_log, hours = {}, 0.0
    for path in sorted(Path(args.folder).rglob("gnss_log*.txt")):
        try:
            ms = read_log(path)
        except ValueError:
            continue
        nav = sorted(path.parent.glob("*.rnx"))
        if nav:
            rinex_nav.attach(ms, rinex_nav.read_nav(nav[0]))
        base = fit_device_baseline(segment(ms, 0, min(1200, ms.n_epochs // 3)))
        x = extract(ms, base, cfg.gates).x
        keep = np.ones(ms.n_epochs, dtype=bool)
        keep[:120] = False
        if path.parent.name in NOT_CLEAN:
            a, b = NOT_CLEAN[path.parent.name]
            keep[a:b] = False
        per_log[path.parent.name] = fusion.raw_tails(x, cfg.norm, keep)
        hours += keep.sum() / 3600.0
    terms = sorted({t for v in per_log.values() for t in v})
    tails = {t: max(v[t] for v in per_log.values() if t in v) for t in terms}
    out = {"source": "Zenodo 10.5281/zenodo.14712684 (five GnssLogger logs, four phone models), clean parts only",
           "clean_hours": round(hours, 2), "logs": sorted(per_log), "reference": args.reference,
           "tails": {t: round(v, 4) for t, v in tails.items() if v > 0},
           "simulated_tails": {t: round(cfg.norm[t][1], 4) for t in terms},
           "per_log": {k: {t: round(v, 4) for t, v in d.items()} for k, d in per_log.items()}}
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"{'term':12s} {'simulated':>10s} {'real':>10s}  ratio")
    for t in terms:
        sim, real = cfg.norm[t][1], tails[t]
        print(f"{t:12s} {sim:10.3f} {real:10.3f}  {real / sim:5.1f}" + ("  widened" if real > sim else ""))


if __name__ == "__main__":
    main()
