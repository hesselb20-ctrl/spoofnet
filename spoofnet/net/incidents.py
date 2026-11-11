"""Group device events into incidents, classify them and locate the source (DESIGN.md section 8)."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

import numpy as np

from ..geo import ecef_to_enu, ecef_to_lla, enu_to_ecef, lla_to_ecef
from . import cells, privacy
from .events import TIER_WEIGHT
from .localize import Obs, locate

LINK_RES = 7          # events are linked through res 7 cells ...
LINK_RINGS = 2        # ... at most this many rings apart (about 5 km)
SLACK_S = 30          # and overlapping in time within this slack
K_MIN = privacy.K_MIN
W_MIN = 1.2           # summed tier weight of distinct contributors
ALARM = ("jam", "spoof", "meacon")
# RMS distance from a hexagon's centre to a uniformly placed point, per resolution, in metres.
CELL_SIGMA_M = {7: 790.0, 8: 300.0, 9: 112.0, 10: 43.0}


@dataclass
class Incident:
    id: str
    type: str
    confidence: float
    t_start: int
    t_end: int
    t_created: float
    n_devices: int
    weight: float
    cells8: list
    affected7: list
    clean7: list
    source: dict | None
    reasons: list
    evidence: str
    events: list = field(default_factory=list, repr=False)
    adsb: str = "not_checked"

    def to_dict(self, with_events: bool = False) -> dict:
        d = asdict(self)
        if not with_events:
            d.pop("events")
        return d


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int) -> None:
        self.p[self.find(a)] = self.find(b)


def cluster(events: list) -> list:
    """Indices of events grouped by proximity in space (H3 rings) and overlap in time."""
    n = len(events)
    if n == 0:
        return []
    c7 = cells.parents([e["cell"] for e in events], LINK_RES)
    by_cell: dict = {}
    for i, c in enumerate(c7):
        by_cell.setdefault(c, []).append(i)
    distinct = list(by_cell)
    disks = dict(zip(distinct, cells.grid_disks(distinct, LINK_RINGS)))
    uf = _UnionFind(n)

    def overlap(a, b) -> bool:
        return a["t_start"] <= b["t_end"] + SLACK_S and b["t_start"] <= a["t_end"] + SLACK_S

    for c in distinct:
        near = [j for d in disks[c] if d in by_cell for j in by_cell[d]]
        for i in by_cell[c]:
            for j in near:
                if j > i and overlap(events[i], events[j]):
                    uf.union(i, j)
    # Devices pulled to one false position belong together even when they are far apart.
    by_claim: dict = {}
    for i, e in enumerate(events):
        cc = e["obs"].get("claimed_cell")
        if cc:
            by_claim.setdefault(cells.parent(cc, 8), []).append(i)
    for idx in by_claim.values():
        for i in idx[1:]:
            if overlap(events[idx[0]], events[i]):
                uf.union(idx[0], i)
    groups: dict = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)
    return list(groups.values())


def created_time(evs: list, k_min: int = K_MIN, w_min: float = W_MIN):
    """Server time at which the group first has enough independent alarm reports, or None."""
    seen: dict = {}
    for e in sorted((e for e in evs if e["type"] in ALARM), key=lambda e: e.get("t_received", e["t_start"])):
        seen[e["token"]] = max(seen.get(e["token"], 0.0), TIER_WEIGHT[e["tier"]])
        if len(seen) >= k_min and sum(seen.values()) >= w_min:
            return float(e.get("t_received", e["t_start"]))
    return None


def classify(evs: list) -> tuple:
    """Return (type, confidence, reasons)."""
    alarm = [e for e in evs if e["type"] in ALARM]
    votes = {t: 0.0 for t in ALARM}
    best: dict = {}
    for e in alarm:
        votes[e["type"]] += TIER_WEIGHT[e["tier"]] * e["score"]
        best[e["token"]] = max(best.get(e["token"], 0.0), TIER_WEIGHT[e["tier"]] * e["score"])
    reasons = []
    # Several devices in different places reporting one claimed position: spoofing or meaconing.
    claim: dict = {}
    for e in alarm:
        cc = e["obs"].get("claimed_cell")
        if cc:
            claim.setdefault(cells.parent(cc, 8), set()).add((e["token"], privacy.coarsen(e["cell"], 9)))
    shared = max((len({c for _, c in v}) for v in claim.values()), default=0)
    kind = max(votes, key=votes.get)
    if shared >= 2:
        reasons.append("SHARED_CLAIMED_POSITION")
        kind = "meacon" if votes["meacon"] >= votes["spoof"] else "spoof"
    elif votes["spoof"] + votes["meacon"] > votes["jam"]:
        kind = "meacon" if votes["meacon"] > votes["spoof"] else "spoof"
    else:
        kind = "jam"
    counts: dict = {}
    for e in alarm:
        for r in e["reasons"]:
            counts[r] = counts.get(r, 0) + 1
    reasons += [r for r, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:4]]
    # Noisy-OR over independent contributors, scaled down until K_MIN of them agree.
    p_none = float(np.prod([1.0 - 0.9 * v for v in best.values()])) if best else 1.0
    conf = (1.0 - p_none) * min(1.0, len(best) / K_MIN)
    return kind, round(conf, 3), reasons


def _frame(evs: list):
    centres = cells.cell_centers([e["cell"] for e in evs])
    lat0, lon0 = float(centres[:, 0].mean()), float(centres[:, 1].mean())
    enu = ecef_to_enu(lla_to_ecef(centres[:, 0], centres[:, 1], 0.0), lat0, lon0, 0.0)
    return lat0, lon0, centres, enu


def locate_source(evs: list, pings: list, kind: str, n_exp: float = 2.0, fit_n: bool = False) -> dict | None:
    """Source estimate with a 95 % ellipse, in geographic coordinates."""
    lat0, lon0, centres, enu = _frame(evs)
    if kind == "meacon":
        # A meaconer makes every victim compute the position of its own receive antenna.
        claimed = [e["obs"]["claimed_cell"] for e in evs if e["obs"].get("claimed_cell")]
        if claimed:
            c = cells.cell_centers(claimed)
            return {"lat": float(np.median(c[:, 0])), "lon": float(np.median(c[:, 1])),
                    "ellipse95": {"semi_major_m": 300.0, "semi_minor_m": 300.0, "bearing_deg": 0.0},
                    "method": "claimed_position", "n_meas": len(claimed)}
    obs: dict = {}
    for e, p in zip(evs, enu):
        o = e["obs"]
        res = cells.resolution(e["cell"])
        w = TIER_WEIGHT[e["tier"]] * (0.5 if e["type"] == "loss_unknown" else 1.0)
        if o.get("saturated") or o.get("d_cn0_db") is None:
            cand = Obs(p[0], p[1], "sat", o.get("d_cn0_min_db") or 20.0, w, CELL_SIGMA_M.get(res, 300.0))
        elif o["d_cn0_db"] >= 1.5:
            cand = Obs(p[0], p[1], "meas", o["d_cn0_db"], w, CELL_SIGMA_M.get(res, 300.0))
        else:
            continue
        key = (e["token"], e["cell"])
        old = obs.get(key)
        # One observation per device and place: saturation outranks a measurement, a larger loss a smaller one.
        rank = lambda q: (q.kind == "sat", q.drop_db)
        if old is None or rank(cand) > rank(old):
            obs[key] = cand
    affected_tokens = {e["token"] for e in evs}
    t0, t1 = min(e["t_start"] for e in evs), max(e["t_end"] for e in evs)
    clean = [p for p in pings if p["token"] not in affected_tokens and t0 // 3600 <= p["hour"] <= t1 // 3600
             and p["tier"] in ("A", "B")]
    if clean:
        cc = cells.cell_centers([p["cell7"] for p in clean])
        ce = ecef_to_enu(lla_to_ecef(cc[:, 0], cc[:, 1], 0.0), lat0, lon0, 0.0)
        for p, q in zip(clean, ce):
            obs[(p["token"], p["cell7"])] = Obs(q[0], q[1], "clean", np.nan, 0.5 * TIER_WEIGHT[p["tier"]], CELL_SIGMA_M[7])
    est = locate(list(obs.values()), n_exp=n_exp, fit_n=fit_n)
    if est is None:
        # Too little for multilateration: weighted centre of the affected cells, wide uncertainty.
        aff = np.array([[o.e, o.n] for o in obs.values() if o.kind != "clean"])
        if len(aff) == 0:
            return None
        c = aff.mean(axis=0)
        rad = float(max(np.sqrt(((aff - c) ** 2).sum(axis=1).mean()), 500.0))
        est = {"e": float(c[0]), "n": float(c[1]), "ellipse95": {"semi_major_m": 2.5 * rad, "semi_minor_m": 2.5 * rad,
               "bearing_deg": 0.0}, "method": "centroid", "n_meas": len(aff), "cov": [[rad**2, 0], [0, rad**2]]}
    lat, lon, _ = ecef_to_lla(enu_to_ecef(np.array([est["e"], est["n"], 0.0]), lat0, lon0, 0.0))
    est.update(lat=float(lat), lon=float(lon), frame=[lat0, lon0])
    return est


def build_incidents(events: list, pings: list | None = None, n_exp: float = 2.0, fit_n: bool = False,
                    k_min: int = K_MIN, w_min: float = W_MIN) -> list:
    """All incidents supported by `events`. Groups that never reach the contributor
    threshold are dropped: one device is not an incident."""
    pings = pings or []
    out = []
    for idx in cluster(events):
        evs = [events[i] for i in idx]
        created = created_time(evs, k_min, w_min)
        if created is None:
            continue
        kind, conf, reasons = classify(evs)
        tokens = {e["token"] for e in evs if e["type"] in ALARM}
        weight = sum(max(TIER_WEIGHT[e["tier"]] for e in evs if e["token"] == t) for t in tokens)
        c8 = sorted(set(cells.parents([e["cell"] for e in evs], privacy.STORE_RES)))
        c7 = sorted(set(cells.parents([e["cell"] for e in evs], LINK_RES)))
        t0, t1 = min(e["t_start"] for e in evs), max(e["t_end"] for e in evs)
        clean7 = sorted({p["cell7"] for p in pings if p["token"] not in {e["token"] for e in evs}
                         and t0 // 3600 <= p["hour"] <= t1 // 3600} - set(c7))
        source = locate_source(evs, pings, kind, n_exp, fit_n)
        iid = hashlib.sha1(f"{c8[0]}|{t0 // 300}|{kind}".encode()).hexdigest()[:12]
        out.append(Incident(iid, kind, conf, int(t0), int(t1), created, len(tokens), round(weight, 2), c8, c7, clean7,
                            source, reasons, "real" if all(e["evidence"] == "real" for e in evs) else "replay", evs))
    return out
