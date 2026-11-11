"""Scoring of detector output against simulator ground truth (DESIGN.md section 13)."""
from __future__ import annotations

import numpy as np

ALARM_TYPES = ("jam", "spoof", "meacon")
PRE_S, POST_S = 5, 30     # an event this close to an attack belongs to the attack


def attack_windows(y: np.ndarray) -> list:
    """Contiguous labelled regions as (start, end, label)."""
    out, t, n = [], 0, len(y)
    while t < n:
        if y[t] == 0:
            t += 1
            continue
        u = t
        while u < n and y[u] != 0:
            u += 1
        out.append((t, u, int(np.max(y[t:u]))))
        t = u
    return out


def score_scenario(events: list, y: np.ndarray, warmup: int = 90) -> dict:
    wins = attack_windows(y)
    n = len(y)
    clean = np.ones(n, dtype=bool)
    clean[:warmup] = False
    for a, b, _ in wins:
        clean[max(a - PRE_S, 0):min(b + POST_S, n)] = False
    res = {"clean_s": int(clean.sum()), "false_alarms": [], "attacks": [], "loss_unknown": 0}
    for ev in events:
        if ev["type"] == "loss_unknown":
            res["loss_unknown"] += int(clean[min(ev["start"], n - 1)])
            continue
        if clean[min(ev["start"], n - 1)]:
            res["false_alarms"].append({"type": ev["type"], "start": ev["start"], "reasons": ev["reasons"]})
    for a, b, lab in wins:
        hits = [ev for ev in events if ev["type"] in ALARM_TYPES and a - PRE_S <= ev["start"] < b + 10]
        want = ("jam",) if lab == 1 else ("spoof", "meacon")
        typed = [ev for ev in hits if ev["type"] in want]
        loss = [ev for ev in events if ev["type"] == "loss_unknown" and a - PRE_S <= ev["start"] < b + 10]
        res["attacks"].append({
            "t0": a, "t1": b, "label": lab,
            "detected_any": bool(hits), "detected": bool(typed),
            "ttd": float(max(min(ev["start"] for ev in typed) - a, 0)) if typed else None,
            "ttd_any": float(max(min(ev["start"] for ev in hits) - a, 0)) if hits else None,
            "exact_type": bool(typed) and ((lab == 3) == (typed[0]["type"] == "meacon")),
            "loss_unknown": bool(loss), "types": sorted({ev["type"] for ev in hits}),
        })
    return res


def wilson(k: int, n: int, z: float = 1.96):
    """Wilson score interval for a proportion."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (float(max(c - h, 0.0)), float(min(c + h, 1.0)))


def poisson_upper(k: int, hours: float, conf: float = 0.95) -> float:
    """Upper confidence bound on a rate per hour given k events (exact, chi-square form)."""
    from scipy.stats import chi2
    return float(chi2.ppf(conf, 2 * (k + 1)) / 2.0 / max(hours, 1e-9))
