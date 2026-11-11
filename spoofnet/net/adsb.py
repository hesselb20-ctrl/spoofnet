"""Cross-check of ground incidents against ADS-B-derived interference aggregates.

Method (the one GPSJam uses): aircraft broadcast a navigation accuracy value
(NACp) with their position. The share of aircraft per map cell that report low
accuracy, having reported good accuracy before, is an interference indicator
for the airspace above that cell. GPSJam marks a cell from 2 % and marks it
strongly above 10 %; this module uses the 10 % level.

This module does not download anything. It consumes a table of aggregates that
an operator has prepared, because:
  * OpenSky Network data is free for research and non-profit use only. Any
    commercial use needs a licence from OpenSky first.
  * The integrity fields are in OpenSky's historical database, which needs an
    approved account, not in the anonymous live API.

Table format, CSV with a header:  cell,hour,aircraft,degraded
  cell      H3 cell at res 4 (about 1 770 km2)
  hour      whole hours since the Unix epoch
  aircraft  distinct aircraft seen in the cell in that hour
  degraded  how many of them reported degraded navigation integrity

A ground-level source often does not reach cruising altitude, so "not seen in
ADS-B" does not contradict a ground incident. It is reported as exactly that.
"""
from __future__ import annotations

import csv
from pathlib import Path

from . import cells

ADSB_RES = 4
MIN_AIRCRAFT = 5          # below this the cell-hour says nothing
DEGRADED_SHARE = 0.10     # share of aircraft that marks a cell-hour as affected


def load_table(path) -> dict:
    table: dict = {}
    with open(Path(path), newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            table[(row["cell"], int(row["hour"]))] = (int(row["aircraft"]), int(row["degraded"]))
    return table


def cross_check(incident_cells: list, t_start: int, t_end: int, table: dict) -> dict:
    """Compare one incident with the table. Returns a status and the numbers behind it."""
    if not table or not incident_cells:
        return {"status": "no_adsb_coverage", "aircraft": 0, "degraded": 0}
    parents = set(cells.parents(list(incident_cells), ADSB_RES))
    aircraft = degraded = 0
    for cell in parents:
        for hour in range(int(t_start) // 3600, int(t_end) // 3600 + 1):
            a, d = table.get((cell, hour), (0, 0))
            aircraft += a
            degraded += d
    if aircraft < MIN_AIRCRAFT:
        status = "no_adsb_coverage"
    elif degraded / aircraft >= DEGRADED_SHARE:
        status = "agrees"
    else:
        status = "not_seen_in_adsb"
    return {"status": status, "aircraft": aircraft, "degraded": degraded}
