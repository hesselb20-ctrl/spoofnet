# Real-world validation: what was done, what was found, what is missing

Checked on 11 November 2026.

## Status in three lines

* **Real phone data, no interference:** the detector was run on four public
  real-phone logs (2.8 hours). First result: a continuous false spoofing alarm.
  After hardening: no alarm. Synthetic jamming injected into those logs: 7 of 8
  detected.
* **Real phone data, real interference:** one public log of one flight across
  a documented interference area. The detector raised one jamming event, over
  the same map cells where aircraft reported interference that day, and
  nothing elsewhere.
* **Not done:** anything at ground or sea level under real interference, any
  log from our own app, any real spoofing. No detection rate can be quoted
  from real data.

Nothing here amounts to "validated on real-world data". It is one real
observation and one real-noise check, and it is labelled that way everywhere.

## The data

[Zenodo 10.5281/zenodo.14712684](https://zenodo.org/records/14712684): "GNSSLogger
traces for multi-modal transportation studies", E. Takiguchi Medina and
E. S. Lohan, CC BY 4.0. GnssLogger text logs recorded by the authors. Their
README says no known spoofers are present, "except perhaps in the FLIGHT
folder".

| Log | Phone | Usable length | AGC changes | Second band | Ephemeris file | Note |
|---|---|---|---|---|---|---|
| WALK | Xiaomi 2201123G | 0.92 h | yes | yes | no | city walk |
| BIKE | Samsung SM-A528B | 0.20 h | yes | no | no | |
| BUS | Google Pixel 7 | 0.22 h | yes | yes | no | sensors logged too sparsely to use |
| FERRY | Xiaomi 22111317G | 1.51 h | yes | no | yes | near Split; 17 clock resets; cabin outages |
| FLIGHT | Samsung SM-A528B | 1.32 h | yes | no | no | Riga to Tampere, 22 March 2024 |
| CAR | n/a | n/a | | | | no raw log in the folder, only a converted file |

The raw data stays out of this repository (`data/` is ignored). Fetch it from
Zenodo to reproduce.

## 1. Real clean logs: false alarms and injected jamming

`experiments/m6_recorded_logs.py`, result in `results/m6_recorded_logs.json`.
Evidence label: `replay` (real phone noise, synthetic interference).

**First run, detector fitted on simulated data only.** On the ferry log the
spoofing model sat above its threshold for 85 of 92 minutes. The causes, found
with `experiments/m6_term_audit.py` (every evidence term on real clean logs, in
units of the simulated 99th percentile):

| Check | Real clean tail / simulated tail | Why |
|---|---|---|
| Elevation against almanac | 44 | Phones report whole degrees; the simulator reported exact values |
| Frozen position while IMU reports motion | over 1000 | Fired on both logs with usable sensors |
| Doppler acceleration without IMU acceleration | 9.0 | Sustained acceleration leaks into the gravity estimate |
| Network position mismatch | 5.3 | Network positions at sea are far worse than they claim |
| AGC step, AGC level | 4.3, 3.2 | Real AGC wanders more than simulated |
| Clock drift step | 3.9 | Real receivers reset more roughly |
| Uniform C/N0 drop | 2.3 | |
| Everything else | 0.2 to 1.7 | The recalibrated simulator is close |

Two bugs also surfaced: a constellation without ephemeris counted as a failed
solution, and attaching ephemeris erased GLONASS pseudoranges.

**What was changed.** The three Doppler-against-IMU checks left the score
(`DESIGN.md` 5.3). Every other quantity's normal range became the wider of its
simulated and its real clean tail (`config/real_tails.json`), and the detector
was refitted.

**Second run, final detector.**

| | Result |
|---|---|
| Jamming, spoofing or meaconing alarms on 2.84 h of clean real logs | 0 |
| 95 % upper bound that 2.84 hours can support | 1.05 per hour |
| `loss_unknown` reports | 8, all on the ferry (cabin outages) |
| Injected jamming detected (10 to 13 dB, 15-minute segments) | 7 of 8 |
| by kind | L1 only 3 of 4, L1 wide 2 of 2, all bands 2 of 2 |

Read this with two cautions. The same four logs set the widened ranges, so
"no alarm" on them is a consistency check, not an independent measurement.
And 2.84 hours cannot show a rate anywhere near the 0.01 per hour target:
that needs 300 clean hours on real phones.

One more thing these logs say: all four phone models have AGC that moves. The
simulated population assumes about half of phones have none, and those are the
phones on which jamming detection is poor. The real share decides which
detection figure applies in the field. A capability survey across many models
(for example the 285 models in [Zenodo 20092798](https://zenodo.org/records/20092798))
would settle it.

## 2. One real observation: a flight across the Baltic interference area

`experiments/m6_flight.py`, result in `results/m6_flight.json`. Evidence label:
`real`, for this one log.

A passenger's phone logged the whole flight. The phone's normal was taken from
the first 20 minutes, on the ground in Riga. The detector ran unchanged, with
weights and thresholds from replay. The right-hand column is independent: the
share of aircraft that reported low navigation accuracy in the same H3
resolution-4 cell on the same day, from [GPSJam](https://gpsjam.org/faq/)'s
daily file for 2024-03-22.

| Minute | Latitude | Altitude | Tracked signals | Top-3 C/N0 | AGC | Jamming score | Aircraft reporting low accuracy |
|---|---|---|---|---|---|---|---|
| 0 to 25 | 56.9 (Riga, ground) | 30 m | 28 to 35 | reference | reference | 0.17 to 0.30 | 0 % of 99 |
| 30 | 57.1 | 1 900 m | 34 | +1.0 dB | +0.6 dB | 0.21 | not looked up |
| 35 | 57.6 | 4 900 m | 33 | -0.4 dB | 0.0 dB | 0.26 | 6 % of 69 |
| **40** | **58.1** | 7 100 m | 23 | **-7.7 dB** | **-5.0 dB** | **0.97** | **18 % of 91** |
| **45** | **58.7** | 8 200 m | 25 | **-8.1 dB** | **-4.4 dB** | **0.78** | **15 % of 73** |
| **50** | **59.3** | 8 200 m | 20 | **-10.2 dB** | **-6.3 dB** | **0.97** | **24 % of 113** |
| **55** | **59.8** | 8 100 m | 21 | **-10.1 dB** | **-5.4 dB** | **0.94** | **20 % of 118** |
| 60 | 60.4 | 7 200 m | 30 | -3.3 dB | -3.3 dB | 0.59 | 3 % of 68 |
| 65 | 61.0 | 3 700 m | 32 | -3.0 dB | +0.3 dB | 0.21 | 0 % of 17 |
| 70 to 75 | 61.4 (Tampere) | under 1 500 m | 32 to 33 | -2 dB | +0.3 to +0.5 dB | 0.19 to 0.21 | 5 % of 21 |

The detector raised **one event: jamming, from minute 40.2 to minute 62.6**,
with reasons `AGC_DROP`, `BAND_SELECTIVE_LOSS`, `BAND_SELECTIVE`. No spoofing or
meaconing alarm at any point (spoofing score never above 0.29). No alarm in the
other 57 minutes. The reported fix accuracy went from 3.8 m to 9.9 m during the
event, and the fix was never lost.

The four cells inside the event are the four along the track where more than
10 % of aircraft reported low accuracy. GPSJam marks that level in red.

**What this shows.** The phone-side chain works on a real phone under what is
very probably real interference: the log format, the per-device baseline, the
AGC and C/N0 evidence, the thresholds from replay, and the event logic. It also
shows a phone seeing the same thing aircraft transponders report.

**What it does not show.**

* It is one flight and one phone. No rate follows from it.
* It is at 7 to 8 km altitude. That is the view the aircraft-based maps already
  have, and the opposite of the ground-level view SpoofNet is for. Whether
  that interference reached the surface below is unknown.
* Altitude and place are confounded. The AGC fell only above about 5 km, and
  the aircraft was above 5 km only over that stretch. A source inside the
  aircraft cannot be excluded from this log. The agreement with other
  aircraft, cell by cell, is the argument against it.
* The ADS-B figures are daily totals. They do not show that interference was
  present at 21:45 UTC, only that it was present in those cells that day.
* Cause is not established. Low accuracy reports and a noise-floor rise say
  "interference", not who or what.
* The clean parts of this log (before minute 37 and after minute 67) were among
  the data that widened the detector's normal ranges. The stretch with the
  event was not.

Background: the eastern Baltic was a documented interference area that spring;
Finnair turned back and then paused flights to Tartu over GPS interference in
late April 2024 (news reports, for example
[ERR](https://news.err.ee/1609325847/finnair-plane-aborts-landing-at-tartu-airport-due-to-gps-interference),
not re-read for this note).

## 3. What is still missing, in order

1. **A phone of our own.** The app in `android/` has not been built or run.
   Until it is, there are no baseline logs, no battery figure and no
   capability matrix.
2. **Ground-level logs under known interference.** Nothing public was found:

   | Source | What it is | Use |
   |---|---|---|
   | [FGI-JSDR Jammertest 2023](https://www.maanmittauslaitos.fi/en/node/17698) | Raw I/Q samples from the test, including spoofing | Needs a software receiver; not phone measurements |
   | [Tegedor et al., JRC, Jammertest 2025](https://publications.jrc.ec.europa.eu/repository/handle/JRC144749) | A research app (CrowdShield) using phone AGC, tested static, in a motorcade and airborne | Closest prior work; no public data or code listed |
   | [Zenodo 20092798](https://zenodo.org/records/20092798) | 454 sessions of 30 s on 285 phone models | Capability statistics only |

3. **Real spoofing.** No real spoofed phone log has been processed. Every
   spoofing figure in this project is replay.
4. **Ephemeris for more logs, GLONASS, ionosphere.** Only the ferry log ran the
   ephemeris-assisted checks. `spoofnet/io/rinex_nav.py` covers GPS, Galileo
   and BeiDou MEO; GLONASS and the ionosphere are not handled.

## How to get ground truth lawfully

Receiving is legal; transmitting is not, and nothing here involves it.

1. **Jammertest, Andøya, Norway.** The largest open GNSS resilience test, run
   by the Norwegian Public Roads Administration with other authorities. The
   2026 event ran 14 to 18 September with more than 300 participants from 28
   countries; applications closed on 6 April 2026
   ([GPS World](https://www.gpsworld.com/jammertest-2026-seeks-applications-for-gnss-resilience-demonstrations/),
   [Statens vegvesen](https://www.vegvesen.no/om-oss/presse/aktuelt/2026/09/-andoya-er-viktigere-enn-noen-gang/)).
   The published test plan gives times, powers and transmitter positions, so
   every log has ground truth. Next chance: the 2027 event, with the call
   expected in the first quarter.
2. **Other officially announced tests.** Aviation authorities publish notices
   for planned interference exercises. Log passively from a public, lawful,
   safe place inside the announced area and keep the notice with the log.
3. **Scheduled travel through documented areas.** The flight above is the
   pattern, and a ferry across the same water would give the sea-level view.
   Check local law first (`THREAT_MODEL.md` B3.1).

## Protocol for the next real session

* At least two phones, one with a second band, in Continuous mode, from 20
  minutes before to 20 minutes after.
* Note placement and handling by time.
* Keep the official notice and the GPSJam daily file for that date.
* Run the detector unchanged. Report events, devices and hours; detections
  against the schedule; false alarms outside it; time to detect.
* Only then refit anything, and report on a different session from the one
  used to refit.
