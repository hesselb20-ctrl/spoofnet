# SpoofNet: final report

11 November 2026. Every number below was measured by a script in
`experiments/` and is stored in `results/`. `python experiments/summarise.py`
prints them all.

Two labels are used and never mixed:

* **replay**: software replay on simulated phones, or on recorded phone logs
  with synthetic interference injected.
* **real**: passively recorded phone data under real interference.

## Summary

* The spoofing detector, the false-alarm rate, the network's time to detect
  and its source localisation meet their minimum targets **in replay**.
* The jamming detector does not. It finds about half of moderate jamming per
  phone: 87 % on phones with working AGC and a second band, 16 % on phones
  with neither.
* On **real** data there is one observation: on a public log of a flight over
  the eastern Baltic, the detector, unchanged, raised one jamming event over
  exactly the map cells where aircraft reported interference that day.
* The first run on real clean logs broke the spoofing detector. It was fixed
  with data, and the fix cost about ten points of jamming detection.
* The Android app is written and has never been built. Nothing has been
  measured at ground or sea level under real interference.

## Targets

| Metric | Minimum | Stretch | Measured | Label | Verdict |
|---|---|---|---|---|---|
| Jamming detection, moderate (6 to 15 dB), per phone | >= 95 % | >= 99 % | 49 % of 250 (95 % interval 43 to 55); tier A 87 %, B 51 %, C 16 % | replay | **Missed** |
| Spoofing detection, consistent pseudoranges, per phone | >= 85 % | >= 95 % | 100 % of 200 (lower bound 98.1 %) | replay | Met, stretch met |
| False alarms per device-hour | < 0.01 | < 0.001 | 0.0031 (4 in 1 286 h; 95 % upper bound 0.0071) | replay | Met; stretch missed |
| | | | 0 in 2.84 h on real clean logs, which bounds nothing below 1 per hour | replay on real noise | Not established |
| Time to detect an incident, network | <= 60 s | <= 10 s | median 6.2 s, 90th percentile 7.9 s | replay | Met, stretch met |
| Source localisation, median error, 10+ devices | <= 500 m | <= 100 m | 280 m (75th percentile 553 m, 90th 1 047 m) | replay | Met; stretch missed |
| Battery cost of background logging | < 5 %/day | < 2 %/day | not measured: no phone | | **No result** |

Tiers: A has working AGC and a second frequency band, B has one of the two, C
has neither. The jamming figure pools two held-out sets fitted and thresholded
the same way (45 % of 150 and 54 % of 100).

## What works on real data

One thing, once.

**A flight from Riga to Tampere, 22 March 2024** (public log, Zenodo
10.5281/zenodo.14712684, one Samsung phone, 79 minutes). The detector ran with
its weights and thresholds from replay and the phone's baseline from the 20
minutes at the gate.

| | On the ground and climbing | Over Estonia and the Gulf of Finland | Descending into Finland |
|---|---|---|---|
| Minutes | 0 to 37 | 40 to 60 | 65 to 79 |
| Strongest three signals, C/N0 | reference | 7.7 to 10.2 dB lower | 2 to 3 dB lower |
| AGC | reference | 4.4 to 6.3 dB lower | back to reference |
| Detector | no alarm | **one jamming event, minute 40.2 to 62.6** | no alarm |
| Aircraft reporting low navigation accuracy in the same cells that day (GPSJam) | 0 % and 6 % | **18 %, 15 %, 24 %, 20 %** | 3 %, 0 %, 5 % |

No spoofing alarm at any point. The four cells inside the event are the four on
the track that the aircraft-based map marks as affected.

What this is worth: it shows the phone-side chain (log format, baseline,
AGC and C/N0 evidence, thresholds, event logic) responding correctly to what is
very probably real interference. What it is not: a detection rate, a
ground-level result, or proof of cause. It is one phone at 8 km altitude, with
altitude and place confounded. `docs/validation/real_world.md` has the full
table and every caveat.

**Also on real phone data, but with synthetic interference (label: replay):**

* Four clean real logs, 2.84 hours, four phone models: no alarm with the
  final detector. Those same logs were used to widen the detector's normal
  ranges, so this confirms the fix and measures nothing new.
* Synthetic jamming of 10 to 13 dB injected into those logs: 7 of 8 detected.
* Pseudoranges rebuilt from the raw log fields, with satellite positions from
  broadcast ephemeris, agree with the phone's own fixes to a median of 7 to
  9 m per constellation.

## What works only in replay

All of it was measured on scenarios kept apart from fitting and from threshold
choice. The simulated phones were recalibrated to the five real logs first.

**Per phone** (1 286 clean hours, 100 scenarios per attack type):

| Attack | Detected | 95 % interval | Median time to detect | Type named correctly |
|---|---|---|---|---|
| Spoofing, one constellation, flat power | 100 % | 96 to 100 | 13 s | 97 % |
| Spoofing, all L1 constellations, flat power | 100 % | 96 to 100 | 16 s | 84 % |
| Meaconing | 81 % | 72 to 88 | 16 s | 66 % |
| Spoofing, time only | 67 % | 57 to 75 | 23 s | 45 % |
| Spoofing, slow drag-off with realistic power | 49 % | 39 to 59 | 58 s | 45 % |
| Jamming, strong (15 to 35 dB) | 53 % | 43 to 63 | 5 s | |
| Jamming, moderate (6 to 15 dB) | 54 % | 44 to 63 | 8 s | |
| Jamming, weak (3 to 6 dB) | 10 % | 6 to 17 | 7 s | |

ROC curves per attack type: `docs/figures/roc_spoof.png`,
`docs/figures/roc_jam.png`.

Jamming by phone tier (both held-out sets pooled, 250 scenarios each):

| | Tier A | Tier B | Tier C |
|---|---|---|---|
| Moderate | 52 of 60 (87 %) | 57 of 111 (51 %) | 13 of 79 (16 %) |
| Strong | 41 of 42 (98 %) | 82 of 117 (70 %) | 12 of 91 (13 %) |

On phones without AGC, most missed strong jamming is reported as
`loss_unknown`: "everything went quiet and I cannot tell a jammer from a
tunnel". That is deliberate. Those reports cannot open an incident, but they
add evidence to one that other phones opened.

**False alarms** (replay): 4 in 1 286 hours. By environment: tunnel 0 in 83 h,
parking garage 0 in 84 h, street canyon 1 in 189 h, forest 2 in 191 h, boat
cabin 1 in 96 h, and two environments never used for fitting (indoors by a
window, a car with a metallised windscreen) 0 in 168 h. No single environment
has enough hours to prove 0.01 on its own. On repeated routes the per-place
table cuts `loss_unknown` reports from 1.94 to 0.25 per hour (tunnels 5.41 to
0.27) and removes no alarm.

**Network** (160 multi-device scenarios with known source positions; every
phone runs the full detector, the server sees only uploads):

| | Result |
|---|---|
| Jamming incident created | 115 of 120; type right every time |
| False incident in the five minutes before onset | 0 |
| Onset to incident | median 6.2 s, 90th percentile 7.9 s (includes 1 to 5 s simulated upload delay) |
| Source error, jamming | median 280 m; 111 m with 40 phones in free space; 731 m with 10 phones and heavy shadowing |
| Source inside its "95 %" ellipse | 79 % of cases |
| Cost of ten times coarser upload cells | 280 m becomes 294 m |
| Spoofing incident created, type right | 20 of 20, 20 of 20; source error 1 153 m |
| Meaconing incident created, type exact | 20 of 20, 18 of 20; source error 131 m |

**Map, API, alerts:** 41 unit tests pass. A demo feed of three simulated
incidents flows through ingest, incident building, the three access tiers,
geofence alerts and the static map, and the map was checked by hand in a
browser. Nothing is deployed.

## What failed

1. **The jamming target.** 49 % against 95 %. The cause is physical, not a
   tuning gap: without AGC a phone sees jamming only as lower C/N0, and so does
   a roof. What separates them is band selectivity (GPS L1 falls, GLONASS or L5
   does not), and that only works against band-limited sources on phones that
   track another band well. On tier A phones the figure is 87 %.
2. **The first jamming detector.** One model for all phones, fitted on an
   optimistic simulator: 56 % detection and 0.045 false alarms per hour, most
   of them a phone being carried into a car
   (`results/m2_detector_v1_first_attempt.json`).
3. **The first simulator.** Compared with real logs it was far too clean: real
   phones are 3 to 8 dB weaker, have half the elevation trend, three times the
   second-to-second C/N0 noise, and AGC that wanders by several dB.
4. **First contact with real clean logs.** The spoofing detector raised a
   continuous false alarm on a real ferry log (85 of 92 minutes). Real phones
   report elevation in whole degrees, their network position at sea is far
   worse than it claims, and their clocks and AGC misbehave more than
   simulated.
5. **The Doppler-against-IMU checks.** They worked in replay and fired
   constantly on both real logs with usable sensor data. A phone resting in a
   moving vehicle is "still" to an accelerometer. They are out of the score.
6. **The cost of fixing 4 and 5.** Moderate jamming 64 % to 54 %, drag-off
   68 % to 49 %, time-only 77 % to 67 %, meaconing 96 % to 81 % on the same
   scenarios. False alarms fell from 0.0086 to 0.0031 per hour.
7. **Slow drag-off spoofing: 49 %.** A careful attacker who starts aligned and
   mimics per-satellite power is found half the time, and after a minute.
8. **Uncertainty ellipses are too small.** 79 % coverage where 95 % is claimed.
9. **Spoofing source localisation.** About 1.2 km; it is mostly a centroid.
10. **Milestone 1 has no measured result.** No toolchain was available, so the
    app was not compiled, no baseline log was collected, the device matrix is
    empty, and battery cost is unknown.
11. **The app does not detect anything yet.** The detectors exist in Python.
    The Kotlin SDK logs and probes; it has no detector, no uploader and no
    trust indicator.
12. **No ADS-B feed is connected**, and attestation, rate limiting beyond a
    simple counter, and the region list are designed, not implemented.
13. **Stretch targets missed:** false alarms under 0.001 per hour, localisation
    under 100 m, jamming at 99 %.

Process notes, for honesty: the spoofing threshold rule was changed once after
seeing a held-out result (it had been chosen for two attack types only and was
needlessly strict for the other three); the headline numbers come from a later
set that played no part in that. The milestones were committed in the order 1,
2, 3, 4, 6, 5, 7, 8, because the real-log work (6) forced changes to the
hardening (4).

## What nobody knows yet

* How any of this behaves at ground or sea level under real interference.
* What share of phones in the field have working AGC. All four models in the
  public logs do; the simulated population assumes about half. That share
  moves per-phone jamming detection between 16 % and 87 %.
* Whether real spoofing looks like the simulated kind. No real spoofed phone
  log has been processed.
* Battery cost, and how long Android lets the logger run in the background.
* Whether anyone will pay.

## The three next steps to a paying customer

**1. Get the logger onto 20 real phones on one route where interference is
documented and a buyer is nearby.** Build the app (a day with Android Studio
and the checklist in `android/README.md`), then run it for a week on a Baltic
ferry route or in a port on that coast. Twenty phones for fifteen hours each is
300 device-hours: the smallest amount that can show whether real false alarms
are under 0.01 per hour. It also gives the first sea-level observations, the
battery figure and the device matrix. Stop condition: more than three false
alarms in those 300 hours means the detector is not ready for a customer.

**2. Get ground truth.** Apply to Jammertest 2027 (the 2026 call closed on
6 April; expect the next one in the first quarter) and write to the JRC authors
of the Jammertest 2025 phone study about shared logging. Announced tests are
the only lawful source of real jamming and spoofing with known times, powers
and positions, and so the only way to replace the replay figures for detection
and localisation.

**3. Test willingness to pay before building more.** Ten conversations in one
segment, with the one-pager and the flight result. Start where a wrong position
already has a money figure and a named budget: marine war-risk and hull
underwriters and their claims handlers. Ask for one thing: a pilot on five
insured vessels with their own incident log beside ours. If fewer than two of
ten agree to that, the first segment is wrong, and ports or fleet operators
come next before any more engineering. That marine insurers pay first is an
assumption, not a finding.

One cheap side task decides how good the product can be: survey AGC and
dual-frequency support across phone models (the 285-model public dataset is a
day's work).
