"""Tests for the per-place baseline: it may silence `loss_unknown`, never an alarm."""
from types import SimpleNamespace

import numpy as np

from spoofnet.detect.features import IDX, NAMES
from spoofnet.detect.place import PlaceTable
from spoofnet.geo import enu_to_ecef

N = 600


def _session(loss_from=300, loss_to=360):
    """A straight drive east at 10 m/s; GNSS is lost between two points on the route."""
    enu = np.zeros((N, 3))
    enu[:, 0] = 10.0 * np.arange(N)
    fix = enu_to_ecef(enu, 52.0, 5.0, 0.0)
    x = np.zeros((N, len(NAMES)))
    x[loss_from:loss_to, IDX["lost_l1"]] = 1.0
    fix[loss_from:loss_to] = np.nan                      # no fix while the signal is gone
    return SimpleNamespace(fix_ecef=fix, n_epochs=N), x


LOSS = {"type": "loss_unknown", "start": 310, "end": 360, "score": 0.2, "reasons": []}
JAM = {"type": "jam", "start": 310, "end": 360, "score": 0.99, "reasons": []}


def test_place_is_learned_after_two_days_only():
    table = PlaceTable()
    ms, x = _session()
    assert table.filter_events(ms, [LOSS]) == [LOSS]              # nothing known yet
    table.learn(ms, x, day=1, events=[LOSS])
    assert table.filter_events(ms, [LOSS]) == [LOSS]              # one day is not a pattern
    table.learn(ms, x, day=2, events=[LOSS])
    assert table.filter_events(ms, [LOSS]) == []                  # now it is expected here
    elsewhere = {**LOSS, "start": 100, "end": 130}
    assert table.filter_events(ms, [elsewhere]) == [elsewhere]    # only at that place


def test_alarms_are_never_silenced_and_never_learned_from():
    table = PlaceTable()
    ms, x = _session()
    for day in (1, 2, 3):
        table.learn(ms, x, day, events=[LOSS])
    kept = table.filter_events(ms, [JAM, LOSS])
    assert [e["type"] for e in kept] == ["jam"] and kept[0]["place_history"] is True
    fresh = PlaceTable()
    for day in (1, 2, 3):
        fresh.learn(ms, x, day, events=[JAM])                     # sessions with an alarm teach nothing
    assert fresh.losses == {} and fresh.filter_events(ms, [LOSS]) == [LOSS]


def test_place_that_is_usually_fine_is_not_marked():
    table = PlaceTable()
    ms, x = _session()
    clean_ms, clean_x = _session(loss_from=0, loss_to=0)
    table.learn(ms, x, 1, [LOSS])
    table.learn(ms, x, 2, [LOSS])
    for day in range(3, 9):
        table.learn(clean_ms, clean_x, day, [])                   # six later visits without loss
    assert table.filter_events(ms, [LOSS]) == [LOSS]
    assert PlaceTable.from_dict(table.to_dict()).to_dict() == table.to_dict()
