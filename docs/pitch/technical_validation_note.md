# SpoofNet: technical validation note

11 November 2026. For the engineer or analyst who has to judge the one-pager.
Full detail: [REPORT.md](../../REPORT.md) and
[docs/validation/real_world.md](../validation/real_world.md).

## What you are being asked to believe, and what supports it

| Claim | Evidence | Strength |
|---|---|---|
| An ordinary phone's raw GNSS measurements show interference | A public log of a flight over the eastern Baltic: signal strength fell 8 to 10 dB and receiver gain 4 to 6 dB over exactly the map cells where 15 to 24 % of aircraft reported low accuracy that day, and nowhere else | Real data, but one phone, one flight, at 8 km altitude |
| Our detector turns that into an alarm without tuning on it | Same log: one jamming event, minute 40 to 63, no other alarm in 79 minutes; thresholds came from software replay | Real data, one case |
| It stays quiet on normal phone use | 4 false alarms in 1 286 simulated hours across 14 environments (0.003 per hour). No alarm on 2.8 hours of four real clean logs, after those logs were used to harden it | Replay; the real figure is too small to prove anything |
| It finds spoofing | 200 of 200 simulated consistent-pseudorange attacks. Meaconing 81 %, time-only 67 %, slow drag-off 49 % | Replay only. No real spoofing seen |
| It finds jamming | About half per phone: 87 % on phones with working AGC and a second band, 16 % on phones with neither | Replay. Below our own target of 95 % |
| Several phones together locate a source | Median error 280 m with 10 to 40 phones; incident raised in a median of 6 seconds | Replay only |
| Contributors cannot be tracked | By construction: detection on the phone, events and coarse cells uploaded, tokens that change daily and by region, public cells of about 36 km2 with at least three contributors | Design, with unit tests; not audited |

## Method in five lines

1. A simulator produces what a phone reports second by second, for four phone
   types in 14 everyday settings. It was recalibrated against five real phone
   logs after the first version proved far too clean.
2. Synthetic jamming, spoofing and meaconing are injected in software. Nothing
   is ever transmitted.
3. The detector's weights are fitted on one set of scenarios, its thresholds
   chosen on a second, and the results reported from a third.
4. Every quantity's "normal range" is the wider of its simulated and its real
   clean range.
5. The same code then runs on recorded real logs.

## What failed, in plain terms

* The first detector, tuned on the simulator alone, raised a **continuous false
  spoofing alarm on a real ferry log**. Fixing that cost about ten points of
  jamming detection.
* Three motion-sensor checks worked in simulation and were useless on real
  phones. They are switched off.
* On **phones without AGC**, jamming looks like a roof. We report that case as
  "unknown loss" rather than guess.
* The **uncertainty ellipses are too small**: the true source is inside the
  "95 %" ellipse 79 % of the time.
* A **slow, careful spoofing attack** on a single phone is found half the time.
* The **phone app has not been built or run**. Battery cost is unknown.

## What a pilot would establish

A pilot with your own records beside ours is the first test that can fail in
public. It would give, for the first time:

* false alarms per real device-hour (300 hours are the minimum to check 0.01);
* whether events we report line up with disruptions you logged;
* how much of your area has enough phones to say anything at all;
* battery cost on your devices.

Until then, treat SpoofNet output as a lead to check, not as evidence.

## Limits that will not go away

* No contributors, no coverage. Areas without phones are shown as "no data".
* One phone alone can be fooled by a patient attacker. The answer is several
  phones, which needs density.
* At sea there is no network position to cross-check against.
* A phone sees what a phone sees. It does not measure your receiver.
