"""Compare every evidence term on real clean phone logs with what the simulator calls normal.

Each term is normalised so that 1.0 is the 99th percentile of simulated clean data. A term
whose 99th percentile on real clean logs is far above 1 is a simulator artefact: the detector
would fire on it in the field. Prints one row per log.

    python experiments/m6_term_audit.py <folder with logs> [--out results/m6_term_audit.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from m6_recorded_logs import segment                      # noqa: E402
from spoofnet.detect import fusion                        # noqa: E402
from spoofnet.detect.detector import DetectorConfig       # noqa: E402
from spoofnet.detect.features import extract, fit_device_baseline   # noqa: E402
from spoofnet.io import rinex_nav                         # noqa: E402
from spoofnet.io.gnsslogger import read_log               # noqa: E402

# Parts of logs that are not known to be clean: folder -> (first second, last second).
NOT_CLEAN = {"FLIGHT": (2200, 4000)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default="results/m6_term_audit.json")
    args = ap.parse_args()
    cfg = DetectorConfig.load("config/detector.json")
    terms = sorted(set(cfg.spoof.terms) | set(cfg.jam["agc"].terms) | set(cfg.jam["noagc"].terms))
    out = {}
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
        e = fusion.evidence(x, cfg.norm)
        keep = np.ones(ms.n_epochs, dtype=bool)
        keep[:120] = False
        if path.parent.name in NOT_CLEAN:
            a, b = NOT_CLEAN[path.parent.name]
            keep[a:b] = False
        out[path.parent.name] = {"hours": float(keep.sum() / 3600.0), "ephemeris": bool(nav),
                                 "imu": ms.meta["imu_source"],
                                 "p99": {t: float(np.percentile(e[t][keep], 99)) for t in terms},
                                 "max": {t: float(np.max(e[t][keep])) for t in terms}}
    Path(args.out).write_text(json.dumps(out, indent=1))
    names = list(out)
    print("99th percentile on real clean logs, in units of the simulator's own 99th percentile")
    print(f"{'term':16s}" + "".join(f"{n[:7]:>8s}" for n in names) + "   worst")
    for t in terms:
        vals = [out[n]["p99"][t] for n in names]
        flag = "  <-- artefact" if max(vals) > 3.0 else ""
        print(f"{t:16s}" + "".join(f"{v:8.1f}" for v in vals) + f"   {max(vals):5.1f}{flag}")
    print({n: (round(out[n]["hours"], 2), "eph" if out[n]["ephemeris"] else "no eph", out[n]["imu"]) for n in names})


if __name__ == "__main__":
    main()
