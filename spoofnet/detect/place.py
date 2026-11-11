"""Per-place baseline (DESIGN.md section 6, item 3).

A table kept on the device, keyed by H3 res 9 cell, that remembers where GNSS
is routinely lost: tunnels, garages, underpasses. Total loss at such a place is
expected and is not reported as `loss_unknown`.

Two deliberate limits (THREAT_MODEL.md B6.1, B6.2):
  * the table only silences `loss_unknown`. It never silences a jam or spoof
    alarm, so a source that is always on at one place cannot hide behind it;
  * a place counts as "known loss" only after loss on at least two different
    days, learned from sessions without alarms.
"""
from __future__ import annotations

import numpy as np

from ..geo import ecef_to_lla
from ..net import cells
from .features import IDX, _ffill_rows

PLACE_RES = 9


class PlaceTable:
    def __init__(self, min_days: int = 2, min_share: float = 0.5) -> None:
        self.min_days = min_days
        self.min_share = min_share
        self.visits: dict = {}     # cell -> set of days seen
        self.losses: dict = {}     # cell -> set of days with loss

    @staticmethod
    def session_cells(ms) -> list:
        """Res 9 cell per epoch from the last trusted fix, or None before the first fix."""
        pos = _ffill_rows(ms.fix_ecef)
        ok = np.maximum.accumulate(np.all(np.isfinite(ms.fix_ecef), axis=1))
        if not ok.any():
            return [None] * ms.n_epochs
        lat, lon, _ = ecef_to_lla(pos)
        out = cells.latlng_to_cells(lat, lon, PLACE_RES)
        return [c if o else None for c, o in zip(out, ok)]

    def learn(self, ms, x: np.ndarray, day: int, events: list) -> None:
        """Add one session. Sessions that raised an alarm are not learned from."""
        if any(e["type"] in ("jam", "spoof", "meacon") for e in events):
            return
        cs = self.session_cells(ms)
        lost = np.nan_to_num(x[:, IDX["lost_l1"]]) >= 0.9
        secs: dict = {}
        for c, l in zip(cs, lost):
            if c is None:
                continue
            s = secs.setdefault(c, [0, 0])
            s[0] += 1
            s[1] += int(l)
        for c, (n, n_lost) in secs.items():
            self.visits.setdefault(c, set()).add(day)
            if n_lost >= 5:
                self.losses.setdefault(c, set()).add(day)

    def expected_loss(self, cell: str | None) -> bool:
        """Has GNSS been lost here, or in an adjacent cell, on enough earlier days?"""
        if cell is None:
            return False
        lost_days, seen_days = set(), set()
        for c in cells.grid_disks([cell], 1)[0]:
            lost_days |= self.losses.get(c, set())
            seen_days |= self.visits.get(c, set())
        return len(lost_days) >= self.min_days and len(lost_days) / max(len(seen_days), 1) >= self.min_share

    def filter_events(self, ms, events: list) -> list:
        """Drop `loss_unknown` at places with a history of loss, and mark alarms raised there."""
        cs = self.session_cells(ms)
        out = []
        for e in events:
            cell = cs[min(max(e["start"] - 12, 0), len(cs) - 1)]
            known = self.expected_loss(cell)
            if e["type"] == "loss_unknown" and known:
                continue
            out.append({**e, "place_history": True} if known else e)
        return out

    def to_dict(self) -> dict:
        return {"min_days": self.min_days, "min_share": self.min_share,
                "visits": {c: sorted(d) for c, d in self.visits.items()},
                "losses": {c: sorted(d) for c, d in self.losses.items()}}

    @staticmethod
    def from_dict(d: dict) -> "PlaceTable":
        t = PlaceTable(d.get("min_days", 2), d.get("min_share", 0.5))
        t.visits = {c: set(v) for c, v in d.get("visits", {}).items()}
        t.losses = {c: set(v) for c, v in d.get("losses", {}).items()}
        return t
