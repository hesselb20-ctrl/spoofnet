"""Fits every detector constant from replay data and evaluates the result.

Nothing in the detector is hand-tuned. The order is:
  1. gates      from clean training data (levels at which baselines stop adapting)
  2. norm       from clean training data (what "unusual" means for each quantity)
  3. weights    logistic fusion fitted on training attacks against clean data
  4. rules      event thresholds chosen on validation data for a false-alarm budget
  5. test       measured once on held-out scenarios
"""
from __future__ import annotations

from functools import partial

import numpy as np

from ..detect import fusion
from ..detect.detector import PROFILES, DetectorConfig, detect, probabilities, profile_of
from ..detect.features import IDX, Gates, latch
from ..detect.fusion import EventRule, events_from_prob
from ..sim import catalog
from . import scoring
from .harness import run_many

WARMUP = 90
MEACON_TERMS = ("xpos", "xclk", "xvel", "flat", "slope", "grpfail", "alm", "clk", "nloc", "jump", "rise")
JAM_CLASSES = ("jam_weak", "jam_moderate", "jam_strong")
SPOOF_CLASSES = ("spoof_simple", "spoof_multi", "spoof_drag", "spoof_time", "meacon")


def nominal_jobs(split, indices, duration=3600):
    return [(split, "nominal", i, duration) for i in indices]


def attack_jobs(split, classes, indices, duration=900):
    return [(split, c, i, duration) for c in classes for i in indices]


# --- 1. gates -----------------------------------------------------------------------------

def fit_gates(clean: list) -> Gates:
    def col(name):
        return np.concatenate([r["x"][WARMUP:, IDX[name]] for r in clean])

    def q(v, pct):
        v = v[np.isfinite(v)]
        return float(np.percentile(v, pct)) if v.size else float("inf")

    u = np.fmax(col("drop_l1") / (col("spread_l1") + 1.0), col("drop_l5") / (col("spread_l5") + 1.0))
    lat = lambda name: np.concatenate([latch(r["x"][:, IDX[name]].astype(float), 30.0)[WARMUP:] for r in clean])
    return Gates(u=q(u, 99.0), spread=q(col("spread_l1"), 75.0),
                 agc=q(np.fmax(-col("zagc_u"), -col("zagc_l")), 99.9), flat=q(col("flat_min"), 0.1),
                 clk=q(lat("clk_step"), 99.9), xpos=q(col("xpos"), 99.9), nloc=q(col("nloc"), 99.9),
                 jump=q(lat("jump"), 99.9))


# --- 2 and 3. normalisation and fusion weights ---------------------------------------------

def _rows(r, which: str):
    """Row masks for fitting: (clean rows, positive rows) for the jam or the spoof model."""
    y = r["y"]
    n = len(y)
    t = np.arange(n)
    clean = (y == 0) & (t >= WARMUP)
    pos = np.zeros(n, dtype=bool)
    for a, b, lab in scoring.attack_windows(y):
        clean[max(a - 5, 0):min(b + 45, n)] = False
        if which == "jam" and lab == 1:
            pos[a + 2:b] = True
        if which == "spoof" and lab in (2, 3):
            if r["meta"].get("cls") == "spoof_drag":
                pos[a + 30:b] = True          # a slow drag shows nothing at first and more as it goes
            else:
                pos[a + 1:min(a + 61, b)] = True
    return clean, pos


def fit_models(train: list, l2: float = 1e-2, with_spoof: bool = True):
    clean_frames = [(r["x"].astype(float), _rows(r, "jam")[0]) for r in train]
    norm = fusion.fit_norm(clean_frames)
    xj, yj = {p: [] for p in PROFILES}, {p: [] for p in PROFILES}
    xs, ys, xm, ym = [], [], [], []
    for r in train:
        x = r["x"].astype(float)
        e = fusion.evidence(x, norm)
        cls = r["meta"]["cls"]
        step = 4 if cls == "nominal" else 1
        cj, pj = _rows(r, "jam")
        cs, ps = _rows(r, "spoof")
        ds = fusion.design(e, fusion.SPOOF_TERMS)
        if cls == "nominal" or cls in JAM_CLASSES:
            prof = profile_of(x)
            dj = fusion.design(e, fusion.JAM_TERMS[prof])
            if prof == "noagc":
                # Without AGC, losing everything cannot be told from a tunnel, so that is not taught
                # as jamming. Losing GPS and Galileo L1 while GLONASS or L5 stays is taught: no
                # obstruction does that.
                gone = (np.nan_to_num(x[:, IDX["lost_l1"]]) >= 0.9) | ~np.isfinite(x[:, IDX["drop_l1"]])
                others = (np.nan_to_num(x[:, IDX["n_g1"]]) >= 4) | (np.nan_to_num(x[:, IDX["n_l5"]]) >= 4)
                pj = pj & (~gone | others)
            keep = np.flatnonzero(cj)[::step]
            xj[prof].append(dj[keep]); yj[prof].append(np.zeros(keep.size))
            xj[prof].append(dj[pj]); yj[prof].append(np.ones(int(pj.sum())))
        # Jamming epochs are negatives for the spoofing model, so jamming is not called spoofing.
        neg = cs | (r["y"] == 1)
        keep = np.flatnonzero(neg)[::step]
        xs.append(ds[keep]); ys.append(np.zeros(keep.size))
        xs.append(ds[ps]); ys.append(np.ones(int(ps.sum())))
        for a, b, lab in scoring.attack_windows(r["y"]):
            if lab in (2, 3):
                xm.append(np.array([float(np.max(e[t][a:min(a + 60, b)])) for t in MEACON_TERMS]))
                ym.append(float(lab == 3))
    jam = {p: fusion.fit_logit(np.concatenate(xj[p]), np.concatenate(yj[p]), fusion.JAM_TERMS[p], l2) for p in PROFILES}
    if with_spoof and any(float(v.sum()) > 0 for v in ys):
        spoof = fusion.fit_logit(np.concatenate(xs), np.concatenate(ys), fusion.SPOOF_TERMS, l2)
    else:       # no spoofing model yet: a constant that never fires
        spoof = fusion.Logit(fusion.SPOOF_TERMS, np.zeros(len(fusion.SPOOF_TERMS)), -30.0)
    meacon = fusion.fit_logit(np.stack(xm), np.array(ym), MEACON_TERMS, 0.1) if len(set(ym)) == 2 else None
    return norm, jam, spoof, meacon


# --- 4. event rules --------------------------------------------------------------------------

def reduce_probs(cfg_d: dict, out: dict) -> dict:
    """Runs inside the worker: keep only what rule selection and scoring need."""
    cfg = DetectorConfig.from_dict(cfg_d)
    x = out["x"].astype(float)
    pj, ps, e = probabilities(x, cfg)
    events = detect(x, cfg, (pj, ps, e))
    return {"meta": out["meta"], "y": out["y"], "pj": pj.astype(np.float32), "ps": ps.astype(np.float32),
            "profile": profile_of(x),
            "events": events, "score": scoring.score_scenario(events, out["y"], cfg.warmup_s)}


def _rule_stats(results: list, which: str, rule, key_classes, p_on: float | None = None) -> dict:
    """`rule` is one EventRule, or a dict of them by profile. `p_on` overrides the threshold."""
    fa, hours, det, tot, ttds = 0, 0.0, 0, 0, []
    want = 1 if which == "jam" else None
    for r in results:
        y = r["y"]
        n = len(y)
        ru = rule[r["profile"]] if isinstance(rule, dict) else rule
        if p_on is not None:
            ru = EventRule(p_on=p_on, k_on=ru.k_on, m_on=ru.m_on, p_off=min(ru.p_off, p_on / 2), t_off=ru.t_off,
                           merge_s=ru.merge_s)
        evs = events_from_prob(r["pj" if which == "jam" else "ps"].astype(float), ru, WARMUP)
        wins = scoring.attack_windows(y)
        clean = np.ones(n, dtype=bool)
        clean[:WARMUP] = False
        for a, b, _ in wins:
            clean[max(a - scoring.PRE_S, 0):min(b + scoring.POST_S, n)] = False
        fa += sum(1 for s, _, _ in evs if clean[min(s, n - 1)])
        hours += clean.sum() / 3600.0
        if r["meta"]["cls"] in key_classes:
            for a, b, lab in wins:
                if (lab == 1) != (want == 1):
                    continue
                hit = [s for s, _, _ in evs if a - scoring.PRE_S <= s < b + 10]
                tot += 1
                det += bool(hit)
                if hit:
                    ttds.append(max(min(hit) - a, 0))
    return {"fa": fa, "hours": hours, "det": det, "tot": tot,
            "rate": det / max(tot, 1), "ttd": float(np.median(ttds)) if ttds else float("inf")}


RULE_GRID = [EventRule(p_on=p, k_on=k, m_on=m, p_off=min(0.5, p / 2), t_off=10, merge_s=30)
             for p in (0.5, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995, 0.998, 0.999, 0.9995, 0.9999)
             for k, m in ((2, 3), (3, 5), (5, 8), (8, 12))]


def choose_rule(val: list, which: str, key_classes, max_fa: int = 0, slack: float = 0.03):
    """Among rules within the false-alarm budget, keep those whose detection rate is within
    `slack` of the best, then take the strictest. Returns (rule, table of every candidate)."""
    table = []
    for rule in RULE_GRID:
        s = _rule_stats(val, which, rule, key_classes)
        table.append({**rule.to_dict(), **s})
    ok = [row for row in table if row["fa"] <= max_fa] or sorted(table, key=lambda row: row["fa"])[:4]
    best = max(row["rate"] for row in ok)
    near = [row for row in ok if row["rate"] >= best - slack]
    pick = max(near, key=lambda row: (row["p_on"], row["k_on"]))
    rule = EventRule(**{k: pick[k] for k in ("p_on", "k_on", "m_on", "p_off", "t_off", "merge_s")})
    return rule, table


# --- 5. evaluation -----------------------------------------------------------------------------

def evaluate(jobs, cfg: DetectorConfig, cache_dir="results/cache", workers=None) -> list:
    return run_many(jobs, cfg.gates, cache_dir, workers, reduce=partial(reduce_probs, cfg.to_dict()))


def summarise(results: list) -> dict:
    """Aggregate scored scenarios into the numbers the reports quote."""
    out: dict = {"attacks": {}, "false_alarms": {}, "evidence": "replay"}
    hours, fa, loss = 0.0, [], 0
    by_env: dict = {}
    for r in results:
        sc, meta = r["score"], r["meta"]
        h = sc["clean_s"] / 3600.0
        hours += h
        loss += sc["loss_unknown"]
        env = by_env.setdefault(meta["env"], {"hours": 0.0, "fa": 0, "loss_unknown": 0})
        env["hours"] += h
        env["fa"] += len(sc["false_alarms"])
        env["loss_unknown"] += sc["loss_unknown"]
        for f in sc["false_alarms"]:
            fa.append({**f, "env": meta["env"], "tier": meta["tier"], "cls": meta["cls"], "index": meta["index"]})
        if meta["cls"] != "nominal":
            for a in sc["attacks"]:
                c = out["attacks"].setdefault(meta["cls"], {"n": 0, "detected": 0, "detected_any": 0, "exact_type": 0,
                                                            "loss_unknown_only": 0, "ttd": [], "by_tier": {}, "by_env": {}})
                c["n"] += 1
                c["detected"] += a["detected"]
                c["detected_any"] += a["detected_any"]
                c["exact_type"] += a["exact_type"]
                c["loss_unknown_only"] += (not a["detected_any"]) and a["loss_unknown"]
                if a["ttd"] is not None:
                    c["ttd"].append(a["ttd"])
                for grp, key in (("by_tier", meta["tier"]), ("by_env", meta["env"])):
                    g = c[grp].setdefault(key, [0, 0])
                    g[0] += a["detected"]
                    g[1] += 1
    for c in out["attacks"].values():
        lo, hi = scoring.wilson(c["detected"], c["n"])
        tt = c.pop("ttd")
        t = np.array(tt) if tt else np.array([np.nan])
        c.update(rate=c["detected"] / c["n"], ci95=[lo, hi], rate_any=c["detected_any"] / c["n"],
                 ttd_median_s=float(np.nanmedian(t)), ttd_p90_s=float(np.nanpercentile(t, 90)))
    out["false_alarms"] = {
        "count": len(fa), "clean_hours": hours, "rate_per_hour": len(fa) / max(hours, 1e-9),
        "upper95_per_hour": scoring.poisson_upper(len(fa), hours),
        "loss_unknown_per_hour": loss / max(hours, 1e-9),
        "by_env": {k: {**v, "upper95_per_hour": scoring.poisson_upper(v["fa"], v["hours"])} for k, v in sorted(by_env.items())},
        "events": fa[:200],
    }
    return out


def roc(results: list, which: str, classes, rule, p_grid=None) -> dict:
    """Detection rate per attack class against false alarms per clean hour, sweeping the
    event threshold with the persistence rule held fixed."""
    p_grid = p_grid or [0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995, 0.998, 0.999, 0.9995, 0.9999]
    curve = []
    for p in p_grid:
        row = {"p_on": p}
        for c in classes:
            st = _rule_stats(results, which, rule, (c,), p_on=p)
            row[c] = st["rate"]
            row["fa_per_hour"] = st["fa"] / max(st["hours"], 1e-9)
            row["fa"] = st["fa"]
        curve.append(row)
    return {"which": which, "curve": curve}
