# SpoofNet design

SpoofNet is a ground-level map of GNSS jamming and spoofing built from the raw
satellite measurements that Android phones expose. It is **passive detection
only**: no component transmits, and nothing in this repository describes or
helps build transmitting equipment. Every interference signal used in
development exists only as numbers in a software replay.

This document is the contract for the build. Section 13 says how each target is
measured. Section 14 lists what the design cannot do.

## 0. Prior art, and what is new here

Checked on 11 November 2026.

| Work | What it established | What SpoofNet takes from it |
|---|---|---|
| Olsson, Nilsson, Axell, Larsson, Papadimitratos, [arXiv 2305.02038](https://arxiv.org/abs/2305.02038) | Phones can jointly detect and locate a jammer from C/N0. Median error 50 m at path-loss exponent 2, worse at higher exponents, with a Samsung S20+ driven by a signal simulator. The phone's AGC output was too noisy for positioning. | Localisation uses C/N0 loss, not AGC. AGC is used for detection only, and only where it is seen to work. |
| Rustamov, Minetto, Dovis (Politecnico di Torino) | Android phones can be spoofed, and checks on raw measurements can reveal it. | The raw-measurement spoofing checks in section 5.3. |
| Sensors 2018, 18(12), 4130 | Raw measurements have been available on Android since 2017; crowdsourced detection was proposed for aviation and Baltic maritime awareness. | The crowdsourcing premise. |
| Google, [Detect GNSS jamming and spoofing](https://developer.android.com/develop/sensors-and-location/sensors/gnss-spoof-jam) | GnssLogger's Spoof/Jam tab: C/N0 and AGC falling together suggests jamming; C/N0 rising while AGC falls suggests spoofing; GNSS time is compared with network time. Google calls it experimental and says it does not catch every case. | The same single-device cues. They are the starting point, not the product. |
| Tegedor, Piccolo, Gioia, Barbero (JRC), [Jammertest 2025 paper](https://publications.jrc.ec.europa.eu/repository/handle/JRC144749) | A research app (CrowdShield) using AGC on dual-frequency phones detected jamming and meaconing in static, motorcade and airborne tests, and complemented ADS-B in the airborne case. | Field evidence that the AGC cue works on real hardware. Also the nearest thing to a competitor: a public-sector research effort with the same idea. |
| Flightradar24 interference layer, [GPSJam](https://gpsjam.org/faq/) | Daily maps from aircraft ADS-B navigation accuracy. No ground or sea-level view. Blank cells mean no data. | The cross-check layer, and the "no data is not clean" rule. |

The Torino and Sensors rows are quoted from the project brief; those two papers
were not re-read for this document. The other rows were opened and checked.

What this project adds: a measured false-alarm rate across everyday
obstructions; detection on phones without AGC through band selectivity;
spoofing and meaconing checks combined into one score; multi-device source
localisation with honest uncertainty; a privacy design in which tracks never
leave the phone; and a map that draws ignorance as ignorance. No commercial
phone-based service was found, but the JRC work shows the idea is under active
public research, so "nobody else is doing this" would be false.

## 1. Evidence labels

Every number in a report, a commit message, the API and the map carries one of
two labels, and they are never merged:

| Label | Meaning |
|---|---|
| `replay` | Measured in software replay, on simulated logs or on recorded logs with synthetic interference injected. |
| `real` | Measured on passively recorded logs from a documented real interference event. |

An incident on the map carries the label of the detector configuration that
produced it. A detector whose thresholds were only ever tuned in replay is
labelled `replay` even when it runs on a real phone.

## 2. System overview

```
 phone (app or embedded SDK)                 server                        clients
┌───────────────────────────────┐   events  ┌──────────────────────┐   ┌────────────────┐
│ capability probe              │  + cover- │ ingest + validation  │   │ public map     │
│ raw GNSS / clock / AGC / IMU  │   age     │ H3 clustering        │──▶│ (coarse, K-anon)│
│ per-device, per-place baseline│──────────▶│ source localisation  │   ├────────────────┤
│ detectors -> score + reasons  │  no tracks│ classification       │──▶│ API, alerts,   │
│ "can I trust my GPS?" light   │           │ ADS-B cross-check    │   │ exports (vetted)│
└───────────────────────────────┘           │ publication rules    │   └────────────────┘
                                            └──────────────────────┘
```

* All detection runs on the device. The server never sees raw measurements or
  position tracks.
* The Python package `spoofnet` holds the reference detectors, the simulator,
  the replay harness, the aggregation logic and the server. The Android SDK
  reproduces the detector feature pipeline and loads thresholds from the
  configuration file that replay calibration writes (`config/detector.json`),
  so thresholds are never hand-typed into the app.

## 3. Data formats

### 3.1 Raw log (device, local only)

Text, line-oriented, compatible with Google GnssLogger so existing tools and
public datasets can be replayed. The reader is header-driven: it reads each
`# <Type>,<field>,...` header line and maps columns by name, so column order
differences between GnssLogger versions do not matter.

| Record | Source API | Used for |
|---|---|---|
| `Raw` | `GnssMeasurementsEvent` (`GnssClock` + `GnssMeasurement`) | pseudorange, pseudorange rate, C/N0, per-measurement AGC, clock |
| `Agc` | `GnssAutomaticGainControl` (Android 13+) | AGC per constellation and carrier |
| `Status` | `GnssStatus` | azimuth, elevation, used-in-fix |
| `Fix` | `Location` from `gps` and `network` providers (never `fused`) | chipset fix, network position |
| `UncalAccel`, `UncalGyro` | `SensorManager` | motion |
| `SnImu` (SpoofNet extension) | derived on device | 1 Hz motion summary, section 5.1 |
| `SnCap` (SpoofNet extension) | capability probe | one JSON line, section 4 |

Raw logs never leave the phone unless the user exports a file by hand for
validation work.

### 3.2 Event (device to server)

```json
{
  "schema": 1,
  "token": "9f2c...",            // unlinkable contributor token, section 9
  "tier": "A",                   // device quality tier, section 4
  "t_start": 1794300000, "t_end": 1794300140,
  "cell": "8a1f...",             // H3 res 10 of the last trusted position
  "pos_source": "last_trusted",  // last_trusted | network | gnss
  "type": "jam",                 // jam | spoof | meacon | loss_unknown
  "score": 0.97,
  "reasons": ["CN0_DROP_UNIFORM", "AGC_DROP", "BAND_L1_ONLY"],
  "obs": {
    "d_cn0_db": 9.3, "d_cn0_spread_db": 0.8, "d_agc_db": -6.1,
    "sats_before": 28, "sats_min": 9, "bands": ["L1"],
    "claimed_cell": null, "clock_step_m": null
  },
  "evidence": "replay"
}
```

`cell` is where the device believes it really is. During a spoofing event the
GNSS fix is not trusted, so the cell comes from the last trusted fix advanced by
dead reckoning, or from the network position. `claimed_cell` is the H3 res 9
cell of the position the spoofed signals claim. It is a property of the attack,
not of the user, and it lets the server recognise many devices being pulled to
one false point.

### 3.3 Coverage ping (device to server)

```json
{"schema": 1, "token": "9f2c...", "cell7": "871f...", "hour": 498416, "tier": "A", "seconds": 3540}
```

One per H3 res 7 cell and hour in which the device logged. This is what makes
the "no data" layer possible: an area with no pings is drawn as unknown, never
as clean.

## 4. Device capability matrix

The probe (`android/sdk`, `CapabilityProbe`) records, per device:

| Field | How it is determined |
|---|---|
| raw measurements | `GnssCapabilities.hasMeasurements()`, confirmed by receiving a callback |
| AGC | per-measurement AGC present, or `GnssAutomaticGainControl` list non-empty; plus whether the value ever changes |
| dual frequency | carrier frequencies near 1176 MHz observed |
| accumulated delta range | share of measurements with a valid ADR state |
| duty cycling | hardware clock discontinuities and ADR resets while full tracking is requested or not |
| constellations | constellation types observed |
| C/N0 resolution | smallest non-zero step observed |
| chipset | `getGnssHardwareModelName()`, `getGnssYearOfHardware()` |

Tiers, used as weights by the server:

| Tier | Requirement | Weight |
|---|---|---|
| A | raw + working AGC + dual frequency | 1.0 |
| B | raw + (working AGC or dual frequency) | 0.7 |
| C | raw only | 0.4 |
| D | no raw measurements (fix-level checks only) | 0.15 |

The public matrix of tested phones is `docs/device_matrix.md`. A phone enters it
only after a real capability report from that phone exists.

## 5. Detectors

Sampling is 1 Hz. Each detector consumes per-epoch features and produces a
sub-score. A fusion stage turns sub-scores into one calibrated probability per
attack class. A small state machine turns probabilities into events.

### 5.1 Per-epoch features

Signals are grouped by band: `L1` (GPS L1, Galileo E1, BeiDou B1, GLONASS G1) and
`L5` (GPS L5, Galileo E5a, BeiDou B2a).

| Feature | Definition |
|---|---|
| `d_cn0[band]` | median over satellites of (C/N0 minus that satellite's expected C/N0). Expected C/N0 comes from the baseline, section 6. |
| `d_cn0_spread[band]` | robust spread (1.4826 x MAD) over satellites of the same per-satellite difference |
| `n_sats[band]`, `lost_frac` | tracked signals, and the share of recently tracked signals that vanished |
| `d_agc[band]` | AGC minus its slow baseline, in units of the device's own AGC noise |
| `cn0_flat` | spread of C/N0 across satellites after removing nothing: single-antenna spoofers deliver every PRN at nearly the same level |
| `cn0_el_slope` | slope of C/N0 against sin(elevation): authentic signals are stronger overhead, single-antenna spoofing is not |
| `cn0_common` | share of short-term C/N0 variance that is common to all satellites of a constellation: one transmit antenna means one fading channel |
| `clk_step`, `clk_drift_step` | innovation of receiver clock bias and drift against a two-state clock model, ignoring epochs where the hardware clock discontinuity counter changed |
| `xconst_pos`, `xconst_clk` | disagreement between per-constellation position and clock solutions, in units of their formal uncertainty |
| `resid_rms` | pseudorange residual RMS of the all-constellation solution |
| `nloc_dist` | GNSS fix minus network position, in units of the combined accuracy |
| `imu_static_but_moving` | Doppler-derived speed while the IMU says the phone is at rest |
| `imu_moving_but_static` | no Doppler speed and no heading change while the IMU reports turning and vehicle or walking motion |
| `alm_below` | share of tracked satellites that the almanac puts below the horizon at the trusted position |
| `handling` | recent tilt change above threshold: the phone was just picked up, pocketed or put down |

Position, velocity and clock solutions come from a weighted least-squares solver
run per constellation and for all constellations. Satellite positions come from
an almanac or broadcast ephemeris. On a phone this needs ephemeris from
navigation messages or a download; detectors that need it are marked
"ephemeris-assisted" and the rest work without it.

The IMU summary (`SnImu`) is computed from 50 Hz accelerometer and gyroscope
samples in 1 s windows: `vib_rms` (RMS of high-passed acceleration magnitude),
`acc_h` (mean horizontal linear acceleration after removing a low-passed gravity
estimate), `yaw_rate` (mean rotation rate about the gravity axis) and `tilt_deg`
(angle between the gravity estimates at the start and end of the window).

### 5.2 Jamming

Noise-like interference raises the noise floor, so every satellite in the
affected band loses the same number of dB at the same moment:

`d_cn0 = -10 log10(1 + J / (N0 * Bq))`

where `J` is received jammer power and `Bq` the effective spreading bandwidth.
The jamming sub-score rises with:

1. a **large** `d_cn0` drop,
2. a **small** `d_cn0_spread` (uniform across satellites, azimuths and
   elevations),
3. an AGC drop on the same band at the same time, when the device has working
   AGC,
4. loss of satellites that follows C/N0 order (weakest first),
5. **band selectivity**: a larger drop on the L1 carrier than on the
   neighbouring GLONASS G1 and BeiDou B1 carriers, or than on L5/E5a
   (`BAND_SELECTIVE`, `BAND_L1_ONLY`, `BAND_ALL`), and
6. no `handling` event in the preceding seconds.

Item 5 is the strongest single cue on phones without AGC. Obstruction is flat
across carriers that are tens of MHz apart; most interference sources are not.
It is available on every phone that tracks GLONASS, including single-frequency
ones. Its limit is a source that covers every band evenly: on a phone without
AGC that looks like the phone being put in a metal box, and items 2 and 6 are
all that is left.

Obstruction (tunnel, building, foliage, body, metal roof) is the main confuser.
It differs in items 2 and 3: blockage is direction-dependent, so the spread is
large, and it does not add power to the front end, so AGC does not fall. Total
loss with no AGC information is ambiguous on one device. It is reported as
`loss_unknown` with a low score and is only promoted to an incident by the
server when independent devices agree and the place has no history of loss.

### 5.3 Spoofing

Sub-scores, each with its own reason code:

| Reason code | Evidence | Needs |
|---|---|---|
| `CN0_UNIFORM` | `cn0_flat` low and `cn0_el_slope` near zero | status az/el |
| `CN0_COMMON_MODE` | `cn0_common` high | - |
| `AGC_CN0_MISMATCH` | AGC fell (more power in band) while C/N0 did not fall | AGC |
| `CLOCK_STEP`, `CLOCK_DRIFT` | clock innovation beyond the oscillator model with no hardware discontinuity | - or ephemeris |
| `XCONST_DISAGREE` | per-constellation solutions disagree | ephemeris |
| `BAND_DISAGREE` | L1-only and L5-only solutions disagree | ephemeris, dual frequency |
| `NETLOC_MISMATCH` | GNSS fix far from the network position | network fix |
| `POS_JUMP` | fix displacement beyond what the IMU and a speed limit allow | - |
| `DOPPLER_IMU` | Doppler speed against IMU motion, both directions | IMU |
| `ALMANAC_SKY` | tracked satellites that should be below the horizon | almanac |
| `RESIDUALS` | pseudorange residual RMS far above baseline | ephemeris |

### 5.4 Meaconing

A meaconer rebroadcasts real signals with a delay from one antenna. Every
constellation and band stays self-consistent, so `XCONST_DISAGREE`,
`BAND_DISAGREE` and `ALMANAC_SKY` are blind. On the device meaconing shows as a
clock step equal to the delay, a position jump to the meaconer's antenna, a
frozen position while the IMU reports motion, and common-mode C/N0. The device
labels an event `meacon` when the spoofing score is high, all constellations
moved together and the clock offset is steady. The server confirms it when
devices in different cells report the same `claimed_cell`.

### 5.5 Fusion and calibration

Sub-scores are combined by logistic regression, one model per class (`jam`,
`spoof`), fitted on replay training scenarios. The output is a probability.
Calibration is checked on held-out scenarios with a reliability table and the
Brier score, and the result is reported.

Missing evidence is handled explicitly. The jamming model is fitted separately
for phones with working AGC and phones without, and each of the two has its own
event threshold and its own false-alarm budget, because the evidence available
to them differs in kind and one shared threshold serves neither. Within a
profile, absent inputs (no second band, no network position) contribute zero
evidence and the model carries a flag for their presence. The first version of
the detector used one model for all phones; its measured failure is recorded in
`results/m2_detector_v1_first_attempt.json`.

### 5.6 Event state machine

An event opens when the class probability stays above `p_on` for `k_on` of the
last `m_on` seconds, and closes after `t_off` seconds below `p_off`. Events
closer than `t_merge` are merged. `p_on`, `k_on` and `m_on` are chosen on replay
validation data to meet the false-alarm budget, then frozen and measured once on
the test split. No threshold in this repository is set by hand: each one is
written by `experiments/calibrate.py` into `config/detector.json` with the data
that produced it.

## 6. False-alarm strategy

False alarms destroy trust, so they are a measured quantity with a confidence
bound, not an impression. With zero false alarms in `N` device-hours the 95 %
upper bound on the rate is `3 / N`, so proving `< 0.01 /h` needs at least 300
clean hours and `< 0.001 /h` needs 3 000.

Mechanisms:

1. **Per-device baseline.** Expected C/N0 as a function of elevation, learned
   per band from the device's own clean data (running quantile fit). Removes
   model-to-model differences in antenna and front end.
2. **Per-satellite short-term baseline.** A slow median of each satellite's
   C/N0 offset from the elevation model. It adapts to placement (dashboard,
   pocket, cabin) over minutes, and it freezes while any detector is elevated so
   interference cannot be learned as normal.
3. **Per-place baseline.** A table keyed by H3 res 9 cell holding the usual
   C/N0 deficit and loss rate at that place, learned over repeat visits. A
   tunnel or a garage becomes "expected loss here". Stored on the device.
   The server keeps a coarse equivalent (res 8, aggregated) so new users benefit.
4. **Uniformity gate.** Jamming requires a small spread of the per-satellite
   drop. Obstruction almost never produces one.
5. **AGC gate.** When AGC works, a C/N0 drop without an AGC change is treated as
   obstruction.
6. **Handling gate.** After a tilt change (the phone was pocketed, mounted or
   carried into a vehicle) the baselines do not freeze. They re-settle on the
   new placement with a 20 s time constant for 60 s. A source that switches on
   inside that minute is detected late or not at all; that is the price.
   AGC evidence only freezes a baseline together with a C/N0 effect, so thermal
   AGC drift cannot hold a freeze open.
7. **Clock discontinuity gate.** Clock innovations are ignored when the hardware
   clock discontinuity counter changes, and steps within a few metres of a whole
   number of milliseconds are treated as receiver clock steering.
8. **Ambiguity is a first-class result.** `loss_unknown` exists so the device is
   not forced to choose between a missed jammer and a false alarm in a tunnel.
9. **Server-side corroboration.** A public incident needs `K` independent
   contributors (section 9), which also suppresses single-device false alarms.

The false-alarm rate is reported twice: per device (target metric) and per
published incident.

## 7. Simulator and replay harness

Built before the detectors. Code: `spoofnet/sim`, `spoofnet/replay`.

**Constellations.** GPS, Galileo, GLONASS and BeiDou MEO as circular Kepler
orbits (nominal Walker parameters). This gives correct geometry, visibility,
elevation and Doppler statistics. It is not a precise orbit model and is not
used for anything that needs one.

**Receiver.** Device models differ in C/N0 level and elevation slope, C/N0
quantisation, AGC presence, AGC noise and front-end bandwidth, dual-frequency
support, oscillator stability and duty cycling. Code noise and Doppler noise
scale with C/N0. Signals drop out below a tracking threshold and need a higher
level and a delay to come back.

**Motion.** Static, pedestrian, car, boat and tractor trajectories, with an IMU
summary that is consistent with the motion plus noise, and handling events.

**Environments.** Open sky, urban canyon, tunnel, parking garage, forest, boat
cabin under a metal roof, car dashboard, pocket. Each is a model of attenuation
per satellite as a function of azimuth, elevation and time, plus excess
pseudorange error for reflected signals.

**Network position.** Wi-Fi-class, cell-class, or absent (open sea), with the
accuracy and update rate of each.

**Injection.**

* Jamming: received jammer power from a source position, power and path-loss
  exponent, or a direct J/N schedule; band coverage `L1_NARROW`, `L1_WIDE` or
  `ALL_BANDS`; effects on C/N0, AGC, tracking and measurement noise.
* Spoofing: `simple` (one constellation, uniform C/N0, time and frequency
  offset, position jump), `multi` (all L1 constellations), `drag` (starts
  aligned with the true signals, then pulls position away slowly, with a
  realistic per-satellite power profile), `time_only` (clock attack with the
  position kept).
* Meaconing: all signals replayed with a delay, position pulled to the
  rebroadcast antenna.

Injection works on any measurement set, so the same code injects into simulated
logs and into recorded real logs.

**Scoring.** Detection rate, false alarms per device-hour with a 95 % bound,
time to detect, ROC per attack type, calibration, and source-localisation error.

**Data splits.** Scenarios are generated from seeds. Seeds are divided once
into `train` (fit baselines and fusion), `val` (choose thresholds) and `test`
(report). Test scenarios also draw environment and attack parameters from wider
ranges than training, to expose over-fitting to the simulator.

**The limit of replay.** The simulator and the detectors are written by the
same team from the same understanding of the physics. Replay numbers therefore
show that the logic is right and give an upper bound on performance. They do not
show how real phones behave. Only section 11 can do that.

## 8. Network aggregation

Code: `spoofnet/net`.

**Clustering.** Two events are linked when their H3 res 7 cells are within 2
rings of each other (about 5 km) and their time intervals overlap within 30 s.
Events that report the same claimed position are linked regardless of distance.
Connected components are incident candidates. A candidate becomes an incident
when it has alarm events (`jam`, `spoof` or `meacon`) from at least `K_min = 3`
distinct tokens with a summed tier weight of at least 1.2, so three tier C
phones are the minimum. `loss_unknown` events never create an incident on their
own: several cars losing GNSS in one tunnel is not interference. They do add
"at least this strong" observations to an incident that other devices opened.

**Affected area.** The union of event cells, grown by one ring, minus cells
where devices were present and clean during the incident. Cells with no
coverage inside the hull are marked unknown, not affected.

**Source localisation.** For device `i` with C/N0 drop `d_i` on the jammed
band, the received interference-to-noise ratio in dB is

`x_i = 10 log10(10^(d_i/10) - 1)`.

The model is `x_i = P - 10 n log10(r_i) + e_i`, where `r_i` is the distance from
the source at `(x, y)`, `P` absorbs transmit power, the 1 m path loss and the
noise bandwidth, and `n` is the path-loss exponent. `(x, y, P)` are estimated by
robust non-linear least squares from several starting points, with `n` fixed at
2 by default and estimated within [1.8, 4] when there are enough devices.
Three kinds of observation are used:

* measured drop: two-sided residual, weighted by tier and by the sensitivity of
  `x` to errors in `d` (small drops carry little information);
* saturated (all signals lost): one-sided, "at least this strong";
* present and clean: one-sided, "at most this strong".

The 95 % uncertainty ellipse comes from the estimator covariance. Its honesty is
measured: in simulation the true source must fall inside about 95 % of the
ellipses, and the measured coverage is reported next to the error.

For spoofing and meaconing there is no equivalent of the C/N0 drop on the
spoofed signals. The source estimate uses the noise-floor rise seen on
constellations or bands that are not being spoofed, when there is one, and
otherwise falls back to the weighted centre of the affected cells with a wide
uncertainty. This is weaker and is labelled as such.

**Classification.** Weighted vote of event types, then cross-device evidence:
many devices in different cells reporting one `claimed_cell` means spoofing or
meaconing; consistent clock offsets with all constellations moved together
means meaconing. Confidence combines device count, tier weights, event scores
and coverage, and is always shown.

**ADS-B cross-check.** The same method GPSJam uses: the share of aircraft per
cell and hour that report degraded navigation integrity. The module takes those
aggregates as input and returns `agrees`, `disagrees` or `no_adsb_coverage` for
each incident. OpenSky data is free for research and non-profit use. Any
commercial use needs a licence from OpenSky first, so the importer is offline
and no commercial flow depends on it.

## 9. Privacy architecture

| Rule | Implementation |
|---|---|
| Process on the device | Raw measurements, fixes and IMU never leave the phone. |
| Events and aggregates, not tracks | Only the event and coverage records in section 3. Nothing is sent while nothing is detected except hourly coverage pings at res 7 (about 5 km2). |
| Unlinkable contributors | `token = HMAC(device_secret, utc_day || H3 res 5 parent cell)`, truncated to 96 bits. The server can count distinct contributors in a place on a day. It cannot link one device across days or across distant places. The secret never leaves the phone. |
| Coarse public positions | The public map shows H3 res 6 (about 36 km2) by default. Event cells at res 10 are used for localisation and then dropped; storage keeps res 8. |
| K-anonymity | A public cell or incident is shown only with at least `K = 3` distinct tokens. Below `K` it contributes to "coverage: some" but shows no incident. |
| Timing | Public data is quantised to 5 minutes and delayed, so a single contributor's movements cannot be read off live updates. |
| Retention | Event detail 90 days, then aggregates only. Tokens expire with their day. |
| No sale of identities or tracks | There is nothing to sell: neither is collected. The API serves incidents and aggregates only. |
| Transport | TLS, certificate pinning in the app, device attestation to limit forged uploads. |

The localisation accuracy that each upload resolution allows is measured in
milestone 5 so the privacy cost of precision is a number, not a guess.

## 10. Legal and publication rules

This section is engineering policy, not legal advice. Each market needs local
counsel before launch.

* **Passive only.** Receiving GNSS signals and reporting their quality needs no
  radio licence in most places. Transmitting on GNSS bands is illegal almost
  everywhere, and nothing here does it.
* **Announced tests.** Real-world validation uses passive logging near officially
  announced interference tests and in publicly documented interference areas,
  from lawful and safe locations only.
* **Region rules** (`config/publication_rules.json`). Each region sets: public
  cell resolution, whether a source estimate is published at all, the delay, and
  `K`. The default publishes the affected area at res 6 and never publishes a
  precise source estimate. A `restricted` region publishes only a coarse area at
  res 5 with a longer delay. A `no_collection` region disables logging in the
  app, for places where recording interference near defence sites could put a
  contributor at legal risk. The file ships with an empty region list on
  purpose; the entries are a legal decision, not an engineering default.
* **Tiers of access.** Public: coarse area, type, confidence, coverage.
  Customers: incident history, alerts, risk maps at res 7 or 8. Vetted customers
  and authorities: source estimates with uncertainty ellipses.
* **Safety authorities.** Aviation and maritime safety authorities get incident
  data free through the same API. Contact: `docs/RESPONSIBLE_DISCLOSURE.md`.
* **Data licences.** OSM tiles and data under ODbL with attribution; OpenSeaMap
  under its own terms; OpenSky for non-commercial use only unless licensed.
* **Honest confidence.** Every incident shows confidence, device count and
  coverage. An area without enough coverage is drawn as "no data". "No incident"
  is only shown as "no incident detected" and only where coverage exists.

## 11. Validation plan

1. **Replay on simulated logs** (milestones 2 to 5): all targets in section 13.
2. **Replay on recorded clean logs with injection**: our own baseline logs and
   public datasets such as the Google Smartphone Decimeter Challenge. Measures
   false alarms on real phone behaviour and detection of injected attacks on
   real noise. Still labelled `replay`.
3. **Real interference** (milestone 6): passive logs from a documented
   interference region or an announced exercise, compared with official notices
   and ADS-B-derived maps for the same place and time. Labelled `real`. Reports
   state the number of events, devices and hours, and never extrapolate a
   detection rate from a handful of events.

A detector configuration is called "validated on real-world data" only after
step 3.

## 12. Stack and layout

| Part | Choice | Cost |
|---|---|---|
| App and SDK | Kotlin, Android API 26+, no paid services | free |
| Detectors, simulator, analysis | Python, NumPy, SciPy | free |
| Server | FastAPI; SQLite for local runs, Postgres + PostGIS + h3-pg for deployment | free tier |
| H3 in Python | `h3` package when a build exists for the interpreter, otherwise the same H3 library through a Node bridge (`h3-js`) | free |
| Map | MapLibre GL, OSM and OpenSeaMap tiles | free |

```
android/         Kotlin SDK and app
spoofnet/io      log reader and writer
spoofnet/sim     constellations, receivers, environments, injection
spoofnet/detect  features, baselines, detectors, fusion, events
spoofnet/replay  harness and scoring
spoofnet/net     cells, clustering, localisation, classification, ADS-B, privacy
spoofnet/server  API, storage, alerts, publication rules
web/             static map
experiments/     scripts that produce every reported number
results/         their output, one file per milestone
docs/            device matrix, validation notes, pitch pack
config/          detector.json, publication_rules.json
```

## 13. Targets and how each is measured

| Metric | Minimum | Stretch | Measurement |
|---|---|---|---|
| Jamming detection rate, moderate jamming | >= 95 % | >= 99 % | Test-split scenarios with a C/N0 drop of 6 to 15 dB lasting at least 60 s. Detected when a `jam` event opens during the attack. Wilson 95 % interval reported. |
| Spoofing detection rate, consistent-pseudorange | >= 85 % | >= 95 % | Test-split `simple` and `multi` scenarios. Detected when a `spoof` or `meacon` event opens during the attack. Other attack types are reported separately. |
| False alarms per device-hour | < 0.01 | < 0.001 | Events of any class that open outside an attack, over all clean test hours across every environment. Upper 95 % bound reported. |
| Time to detect, network | <= 60 s | <= 10 s | Multi-device simulation: interference onset to incident creation, including upload latency. Median and 90th percentile. |
| Source localisation median error, 10+ devices | <= 500 m | <= 100 m | Multi-device simulation with known source positions, shadow fading and several path-loss exponents. Median and ellipse coverage. |
| Battery cost of background logging | < 5 %/day | < 2 %/day | On a real phone only: charge counter over at least 8 h per mode. Not measurable in replay. |

## 14. Known limits

* Replay results depend on the simulator. See the end of section 7.
* A spoofer that matches power, time, position and per-satellite C/N0 and stays
  within the network-position accuracy is invisible to one phone until it moves
  the position. Detection then depends on the IMU, a second frequency band or
  other devices.
* Phone AGC is coarse and noisy, and absent on many models. Tier C devices
  cannot separate strong jamming from total blockage on their own.
* Android may duty-cycle or stop background GNSS. Coverage in the background is
  best effort and varies by manufacturer.
* Network positions can be wrong, and a long-running spoofer can pollute the
  databases behind them.
* Source localisation from C/N0 loss assumes a single dominant source and a
  simple path-loss law. Ground-level propagation violates both often.
* At sea there is no network position, so one of the strongest spoofing checks
  is missing exactly where spoofing matters most. The clock, IMU, band and
  constellation checks carry more weight there.
