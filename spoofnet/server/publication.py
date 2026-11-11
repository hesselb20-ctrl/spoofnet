"""What each audience may see (DESIGN.md sections 9 and 10).

Three views of one incident:
  public    coarse area, type, confidence, device count band, coverage. No source estimate.
  customer  affected cells at res 7, timing, reasons. No source estimate.
  vetted    everything, including the source estimate and its 95 % ellipse.

Region rules can make the public view coarser, later, or absent. The shipped
rule file has no regions: which places are restricted is a legal decision.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..net import cells, privacy

DEFAULT = {"mode": "default", "public_res": privacy.PUBLIC_RES, "delay_s": 900, "k": privacy.K_MIN,
           "quantise_s": 300, "public_source": "none"}
MODES = ("default", "restricted", "no_collection")
TIERS = ("public", "customer", "vetted")


@dataclass
class Rules:
    default: dict = field(default_factory=lambda: dict(DEFAULT))
    regions: list = field(default_factory=list)     # each: {name, mode, cells5: [...], + overrides}

    @staticmethod
    def load(path="config/publication_rules.json") -> "Rules":
        p = Path(path)
        if not p.exists():
            return Rules()
        d = json.loads(p.read_text())
        r = Rules({**DEFAULT, **d.get("default", {})}, d.get("regions", []))
        for reg in r.regions:
            if reg.get("mode") not in MODES:
                raise ValueError(f"region {reg.get('name')}: unknown mode")
        return r

    def rule_for_cell(self, cell: str) -> dict:
        """The rule that applies to a cell: the first region whose res 5 cell list contains it."""
        c5 = cells.parent(cell, 5) if cells.resolution(cell) > 5 else cell
        for reg in self.regions:
            if c5 in reg.get("cells5", []):
                base = dict(self.default)
                if reg["mode"] == "restricted":
                    base.update(public_res=5, delay_s=6 * 3600)
                base.update({k: v for k, v in reg.items() if k not in ("name", "cells5")})
                base["region"] = reg.get("name")
                return base
        return dict(self.default)

    def collection_allowed(self, cell: str) -> bool:
        return self.rule_for_cell(cell)["mode"] != "no_collection"


def device_band(n: int) -> str:
    """Device counts are published in bands, not exactly."""
    return "3-5" if n <= 5 else "6-10" if n <= 10 else "11-25" if n <= 25 else "26+"


def view(inc: dict, tier: str, rules: Rules, now: float) -> dict | None:
    """Project a stored incident onto what `tier` may see. None means: not visible."""
    if tier not in TIERS:
        raise ValueError(tier)
    rule = rules.rule_for_cell(inc["cells8"][0])
    if rule["mode"] == "no_collection":
        return None
    common = {"id": inc["id"], "type": inc["type"], "confidence": inc["confidence"], "evidence": inc["evidence"],
              "adsb": inc.get("adsb", "not_checked")}
    if tier == "public":
        if inc["n_devices"] < rule["k"] or now < inc["t_created"] + rule["delay_s"]:
            return None
        q = rule["quantise_s"]
        area = sorted(set(cells.parents(inc["affected7"], rule["public_res"])))
        out = {**common, "t_start": int(inc["t_start"] // q * q), "t_end": int(-(-inc["t_end"] // q) * q),
               "devices": device_band(inc["n_devices"]), "cells": area, "cell_res": rule["public_res"]}
        if rule.get("public_source") == "coarse" and inc.get("source"):
            out["source_cell"] = cells.latlng_to_cell(inc["source"]["lat"], inc["source"]["lon"], 5)
        return out
    out = {**common, "t_start": inc["t_start"], "t_end": inc["t_end"], "t_created": inc["t_created"],
           "devices": inc["n_devices"], "weight": inc["weight"], "reasons": inc["reasons"],
           "cells": inc["affected7"], "cell_res": 7, "clean_cells": inc.get("clean7", [])}
    if tier == "vetted":
        out["source"] = inc.get("source")
        out["cells8"] = inc["cells8"]
    return out
