"""Draw the ROC curves per attack type from results/m3_detector.json.

    python experiments/plot_roc.py        # writes docs/figures/roc_spoof.png and roc_jam.png

x: false alarms per clean device-hour (log scale). y: share of attacks detected.
Points with no false alarm observed are drawn at the left edge, which is the
smallest rate the test set could have shown (one alarm in all its clean hours).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

NAMES = {"spoof_simple": "one constellation, flat power", "spoof_multi": "all L1 constellations, flat power",
         "spoof_drag": "slow drag-off, shaped power", "spoof_time": "time only", "meacon": "meaconing (replay)",
         "jam_weak": "weak, 3 to 6 dB", "jam_moderate": "moderate, 6 to 15 dB", "jam_strong": "strong, 15 to 35 dB"}
COLORS = ["#1b6ca8", "#d1495b", "#2e933c", "#8a4fd6", "#b8860b"]


def draw(roc: dict, hours: float, chosen: float, title: str, out: Path) -> None:
    floor = 1.0 / hours
    # Below a threshold of 0.5 the detector is in alarm most of the time, so events no longer
    # open during an attack and the event-based rate stops meaning anything.
    roc = {**roc, "curve": [r for r in roc["curve"] if r["p_on"] >= 0.5]}
    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=150)
    classes = [k for k in roc["curve"][0] if k not in ("p_on", "fa_per_hour", "fa")]
    for cls, color in zip(classes, COLORS):
        xs = [max(r["fa_per_hour"], floor) for r in roc["curve"]]
        ys = [100.0 * r[cls] for r in roc["curve"]]
        ax.plot(xs, ys, marker="o", ms=3.5, lw=1.6, color=color, label=NAMES.get(cls, cls))
    row = min(roc["curve"], key=lambda r: abs(r["p_on"] - chosen))
    ax.axvline(max(row["fa_per_hour"], floor), color="#555555", lw=1.0, ls="--")
    ax.text(max(row["fa_per_hour"], floor) * 1.15, 4, "chosen threshold", color="#555555", fontsize=8, rotation=90, va="bottom")
    ax.axvline(0.01, color="#999999", lw=0.8, ls=":")
    ax.text(0.01 * 1.1, 97, "target 0.01/h", color="#777777", fontsize=8, va="top")
    ax.set_xscale("log")
    ax.set_xlim(floor * 0.8, 20)
    ax.set_ylim(0, 101)
    ax.set_xlabel(f"False alarms per clean device-hour (left edge: none in {hours:.0f} h)")
    ax.set_ylabel("Attacks detected (%)")
    ax.set_title(title, fontsize=11, loc="left")
    ax.grid(True, which="major", color="#e3e3e3", lw=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, fontsize=8.5, loc="lower right")
    fig.text(0.01, 0.01, "Software replay on simulated phones. Not measured on real interference.", fontsize=7.5, color="#777777")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)


def main() -> None:
    d = json.loads(Path("results/m3_detector.json").read_text())
    hours = d["test"]["false_alarms"]["clean_hours"]
    cfg = d["config"]
    draw(d["test"]["roc"]["spoof"], hours, cfg["spoof_rule"]["p_on"],
         "Spoofing detector on one phone: detection against false alarms", Path("docs/figures/roc_spoof.png"))
    draw(d["test"]["roc"]["jam"], hours, cfg["jam_rule"]["agc"]["p_on"],
         "Jamming detector on one phone: detection against false alarms", Path("docs/figures/roc_jam.png"))
    print("wrote docs/figures/roc_spoof.png and docs/figures/roc_jam.png")


if __name__ == "__main__":
    main()
