"""H3 cell operations, batch-first.

Uses the `h3` Python package when the interpreter has a build of it. Otherwise
it talks to the same H3 library through a small Node process (h3-js), so cell
identifiers are identical either way and match h3-pg in Postgres and h3-js in
the browser.
"""
from __future__ import annotations

import atexit
import json
import subprocess
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

try:                                    # pragma: no cover - depends on the interpreter
    import h3 as _h3
except ImportError:                     # pragma: no cover
    _h3 = None

_BRIDGE_DIR = Path(__file__).parent / "h3bridge"


class _Bridge:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None

    def _start(self) -> None:
        if not (_BRIDGE_DIR / "node_modules" / "h3-js").exists():
            raise RuntimeError("H3 is unavailable: install the `h3` package, or run `npm install` in "
                               f"{_BRIDGE_DIR} (needs Node.js)")
        self._proc = subprocess.Popen(["node", "bridge.js"], cwd=_BRIDGE_DIR, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        atexit.register(self.close)

    def call(self, op: str, **kw):
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._start()
            self._proc.stdin.write(json.dumps({"op": op, **kw}) + "\n")
            self._proc.stdin.flush()
            reply = json.loads(self._proc.stdout.readline())
        if not reply.get("ok"):
            raise ValueError(reply.get("err", "h3 bridge error"))
        return reply["out"]

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=2)
            except Exception:
                self._proc.kill()
        self._proc = None


_bridge = _Bridge()


def backend() -> str:
    return "h3-py" if _h3 is not None else "h3-js via node"


def latlng_to_cells(lat, lon, res: int) -> list:
    lat, lon = np.atleast_1d(np.asarray(lat, dtype=float)), np.atleast_1d(np.asarray(lon, dtype=float))
    if _h3 is not None:
        return [_h3.latlng_to_cell(float(a), float(b), res) for a, b in zip(lat, lon)]
    return _bridge.call("cell", pts=[[float(a), float(b)] for a, b in zip(lat, lon)], res=int(res))


def latlng_to_cell(lat: float, lon: float, res: int) -> str:
    return latlng_to_cells([lat], [lon], res)[0]


def cell_centers(cells) -> np.ndarray:
    """(n, 2) array of latitude, longitude."""
    cells = list(cells)
    if not cells:
        return np.zeros((0, 2))
    if _h3 is not None:
        return np.array([_h3.cell_to_latlng(c) for c in cells], dtype=float)
    return np.array(_bridge.call("center", cells=cells), dtype=float)


def cell_boundaries(cells) -> list:
    """For each cell, a list of [lat, lon] vertices."""
    cells = list(cells)
    if not cells:
        return []
    if _h3 is not None:
        return [[list(p) for p in _h3.cell_to_boundary(c)] for c in cells]
    return _bridge.call("boundary", cells=cells)


def grid_disks(cells, k: int) -> list:
    cells = list(cells)
    if not cells:
        return []
    if _h3 is not None:
        return [list(_h3.grid_disk(c, k)) for c in cells]
    return _bridge.call("disk", cells=cells, k=int(k))


def parents(cells, res: int) -> list:
    cells = list(cells)
    if not cells:
        return []
    if _h3 is not None:
        return [_h3.cell_to_parent(c, res) for c in cells]
    return _bridge.call("parent", cells=cells, res=int(res))


@lru_cache(maxsize=200_000)
def parent(cell: str, res: int) -> str:
    return parents([cell], res)[0]


def resolution(cell: str) -> int:
    if _h3 is not None:
        return int(_h3.get_resolution(cell))
    return int(_bridge.call("res", cells=[cell])[0])


def is_valid(cell: str) -> bool:
    if not isinstance(cell, str) or not 10 <= len(cell) <= 16:
        return False
    if _h3 is not None:
        return bool(_h3.is_valid_cell(cell))
    return bool(_bridge.call("valid", cells=[cell])[0])


def grid_distances(pairs) -> list:
    """Grid distance in cells for each (a, b) pair; -1 when H3 cannot compute it."""
    pairs = [list(p) for p in pairs]
    if not pairs:
        return []
    if _h3 is not None:
        out = []
        for a, b in pairs:
            try:
                out.append(int(_h3.grid_distance(a, b)))
            except Exception:
                out.append(-1)
        return out
    return _bridge.call("distance", pairs=pairs)


# Average hexagon area in km^2 per resolution (H3 documentation), for coverage statistics.
AREA_KM2 = {5: 252.9, 6: 36.13, 7: 5.161, 8: 0.7373, 9: 0.1053, 10: 0.01505}
