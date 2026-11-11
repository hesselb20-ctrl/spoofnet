"""Multi-device scenarios with a known source position, run end to end.

Every device is a full raw-measurement simulation with the real on-device
detector. What reaches the aggregation code is exactly what a phone would
upload: events with a coarse cell and a measured C/N0 loss, plus coverage pings.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from ..detect.detector import DetectorConfig, detect
from ..detect.features import extract, fit_device_baseline
from ..geo import ecef_to_lla, enu_to_ecef
from ..sim import catalog
from ..sim.inject import JamSpec, SpoofSpec, apply_attacks, profile_from_source
from ..sim.scenario import ScenarioSpec, simulate
from . import events as ev_mod

UNIX0 = 1_794_300_000          # arbitrary fixed wall-clock origin for simulated uploads
_ENVS = ("open_static", "open_static", "open_static", "open_walk", "open_walk", "urban_walk", "urban_car",
         "forest_walk", "open_car", "boat_deck")


@dataclass
class NetScenario:
    seed: int
    n_devices: int = 20            # devices inside the zone where the loss is about 6 dB or more
    kind: str = "jam"              # jam | spoof | meacon
    n_exp: float = 2.0             # true path-loss exponent
    shadow_db: float = 4.0         # per-device shadow fading sigma
    r10_m: float = 800.0           # distance at which the C/N0 loss is 10 dB
    duration: int = 700
    t0: int = 300
    t1: int = 600
    jam_kind: str = "L1_NARROW"
    origin: tuple = (54.52, 18.80)

    @property
    def n_total(self) -> int:
        return self.n_devices + int(np.ceil(self.n_devices / 3))

    def layout(self):
        """Source position and device positions at the moment the interference starts, in a
        local east/north frame. `n_devices` phones are spread over a disk of radius 1.6 r10
        whose centre is offset from the source, and in four scenarios out of ten they are all
        on one side of it (a quay, a coast road). A third as many again sit further out,
        between 1.6 and 4 r10, where the loss is small or nil."""
        rng = np.random.default_rng(self.seed)
        src = rng.normal(0.0, 300.0, 2)
        ang = rng.uniform(0, 2 * np.pi)
        u = np.array([np.cos(ang), np.sin(ang)])
        centre = src + rng.uniform(0.0, 0.8) * self.r10_m * u
        one_sided = rng.random() < 0.4
        pts = []
        while len(pts) < self.n_devices:
            a, r = rng.uniform(0, 2 * np.pi), 1.6 * self.r10_m * np.sqrt(rng.random())
            p = centre + r * np.array([np.cos(a), np.sin(a)])
            if one_sided and (p - src) @ u < -0.2 * self.r10_m:
                continue
            pts.append(p)
        for _ in range(self.n_total - self.n_devices):
            a, r = rng.uniform(0, 2 * np.pi), rng.uniform(1.6, 4.0) * self.r10_m
            pts.append(src + r * np.array([np.cos(a), np.sin(a)]))
        return src, np.array(pts), rng


def _device_job(args) -> dict:
    scn, i, cfg_d = args
    cfg = DetectorConfig.from_dict(cfg_d)
    src, dev_xy, _ = scn.layout()
    seed = scn.seed * 1000 + i
    rng = np.random.default_rng(seed)
    lat0, lon0 = scn.origin
    lat, lon, _ = ecef_to_lla(enu_to_ecef(np.array([dev_xy[i, 0], dev_xy[i, 1], 0.0]), lat0, lon0, 0.0))
    device = catalog.make_device(seed, wide=bool(i % 2))
    env = _ENVS[int(rng.integers(len(_ENVS)))]
    spec = ScenarioSpec(seed=seed, env=env, duration=scn.duration, device=device, origin=(float(lat), float(lon)),
                        t0_gps=float(scn.seed % 600_000), anchor_t=scn.t0)
    ms = simulate(spec)
    base = fit_device_baseline(simulate(catalog.calibration_spec(device, seed)))
    src_ecef = enu_to_ecef(np.array([src[0], src[1], 0.0]), lat0, lon0, 30.0)
    dist0 = float(np.linalg.norm(ms.truth["pos"][scn.t0] - src_ecef))
    shadow = float(rng.normal(0, scn.shadow_db)) if scn.shadow_db > 0 else 0.0
    p1m = 9.54 + 10.0 * scn.n_exp * np.log10(scn.r10_m)
    true_drop = 0.0
    if scn.kind == "jam":
        prof = profile_from_source(ms, src_ecef, p1m, scn.n_exp, shadow, scn.t0, scn.t1, rng)
        true_drop = float(np.median(prof[scn.t0:scn.t0 + 60]))
        apply_attacks(ms, [JamSpec(scn.t0, scn.t1, kind=scn.jam_kind, profile=prof)], rng)
    else:
        # Devices inside the capture radius are taken over; the rest only see a raised noise floor.
        claim_xy = src + np.array([900.0, 1300.0]) if scn.kind == "spoof" else src
        captured = dist0 < scn.r10_m * 10 ** (shadow / (10.0 * scn.n_exp))
        if captured:
            off = (float(claim_xy[0] - dev_xy[i, 0]), float(claim_xy[1] - dev_xy[i, 1]))
            meacon = scn.kind == "meacon"
            atk = SpoofSpec(scn.t0, scn.t1, kind="meacon" if meacon else "multi", consts=device.consts,
                            lower_band=meacon, offset_enu=off, time_off_m=(dist0 + 400.0) if meacon else 650.0,
                            power_adv_db=float(rng.uniform(5, 12)), cn0_mode="shaped" if meacon else "flat",
                            cn0_level=float(rng.uniform(38, 47)), fade_sigma=float(rng.uniform(0.4, 2.0)),
                            gap_s=int(rng.integers(1, 4)))
            apply_attacks(ms, [atk], rng)
        else:
            prof = profile_from_source(ms, src_ecef, p1m - 6.0, scn.n_exp, shadow, scn.t0, scn.t1, rng)
            true_drop = float(np.median(prof[scn.t0:scn.t0 + 60]))
            apply_attacks(ms, [JamSpec(scn.t0, scn.t1, kind="L1_NARROW", profile=prof)], rng)
    frame = extract(ms, base, cfg.gates)
    dets = detect(frame.x.astype(np.float32).astype(float), cfg)
    secret = hashlib.sha256(f"device-{seed}".encode()).digest()
    uploads = []
    for d in dets:
        rec = ev_mod.build_event(ms, frame.x, d, secret, UNIX0, agc_sigma=base.agc_sigma)
        if rec is not None:
            rec["t_received"] = rec["t_start"] + float(rng.uniform(1.0, 5.0))      # upload latency
            rec["_device"] = i
            uploads.append(rec)
    return {"device": i, "events": uploads, "pings": ev_mod.coverage_pings(ms, secret, UNIX0),
            "truth": {"xy": dev_xy[i].tolist(), "dist_m": dist0, "true_drop_db": true_drop, "tier": device.tier,
                      "env": env, "shadow_db": shadow}}


def device_jobs(scn: NetScenario, cfg: DetectorConfig) -> list:
    d = cfg.to_dict()
    return [(scn, i, d) for i in range(scn.n_total)]


def run(scn: NetScenario, cfg: DetectorConfig, pool=None) -> dict:
    jobs = device_jobs(scn, cfg)
    res = pool.map(_device_job, jobs, chunksize=1) if pool is not None else [_device_job(j) for j in jobs]
    return collect(scn, res)


def collect(scn: NetScenario, res: list) -> dict:
    src, _, _ = scn.layout()
    lat, lon, _ = ecef_to_lla(enu_to_ecef(np.array([src[0], src[1], 0.0]), scn.origin[0], scn.origin[1], 0.0))
    return {"scenario": scn, "source_xy": src.tolist(), "source_latlon": [float(lat), float(lon)],
            "events": [e for r in res for e in r["events"]], "pings": [p for r in res for p in r["pings"]],
            "devices": [r["truth"] for r in res]}
