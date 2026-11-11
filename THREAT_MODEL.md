# SpoofNet threat model

Two different things are modelled here:

* **Part A**: the interference SpoofNet is meant to detect, and what each kind
  can and cannot hide from a phone.
* **Part B**: attacks on SpoofNet itself, on its contributors and on people who
  rely on the map.

SpoofNet is passive. Nothing in this document, or anywhere in the repository,
describes how to build or operate a transmitter. Attack classes are described
only by what a receiver observes.

## Part A. Interference to detect

### A1. Classes

| Class | What the phone observes | Typical setting |
|---|---|---|
| Noise jamming, one band | Equal C/N0 loss on every L1/E1 signal, AGC falls on that band, L5/E5a unaffected or lost later | Privacy jammers in vehicles, drone defence |
| Noise jamming, all bands | Same on every band | Military electronic warfare, wide-area denial |
| Simple spoofing | One constellation jumps to a false position or time; flat C/N0; other constellations lose C/N0 | Low-cost software-radio spoofers |
| Multi-constellation spoofing | All L1 constellations agree on a false position | Area spoofing near sensitive sites, the "ships at an airport" pattern |
| Drag-off spoofing | Starts aligned with real signals, then position or time drifts away slowly | Targeted attack on a vehicle or a timing receiver |
| Time-only spoofing | Position kept, clock pushed | Attack on telecom or grid timing |
| Meaconing | Every signal delayed and re-sent from one point; all constellations consistent | Repeaters, deliberate replay |

### A2. Capability levels and what detects them

| Attacker capability | Blind checks | Checks that still work |
|---|---|---|
| Noise only | none | C/N0 drop and uniformity, AGC, satellite loss |
| Noise strong enough to kill all tracking | uniformity (nothing left to measure) | AGC where available; otherwise only `loss_unknown` plus other devices and place history |
| Consistent pseudoranges, flat power, time offset | pseudorange residuals | C/N0 shape, common-mode fading, clock step, other constellations, network position, IMU |
| All L1 constellations | cross-constellation | L5/E5a against L1, clock, network position, IMU, common-mode fading |
| All bands and constellations (or meaconing) | cross-constellation, cross-band, almanac | clock step, network position, IMU, common-mode fading, several devices pulled to one point |
| Aligned in time and position, shaped per-satellite power, slow drag | C/N0 shape, clock step, position jump | common-mode fading, IMU against Doppler, network position once the offset exceeds its accuracy, other devices |
| All of the above, at sea, against a phone with no IMU motion (anchored) | most single-device checks | common-mode fading; several devices; little else |

The last row is the honest floor of the design: a careful attacker against a
single stationary phone with no network position can stay hidden. SpoofNet's
answer is the network, and it only works where there are several devices.

### A3. Natural confusers

Tunnels, parking garages, urban canyons, forest, metal roofs, pockets, hands,
bags, phone cases, antenna detuning, receiver duty cycling, clock steering,
cold starts, ionospheric scintillation, solar radio bursts, and harmless
in-band emitters such as faulty active antennas and video links. The
false-alarm strategy in `DESIGN.md` section 6 is aimed at these. Solar radio
bursts and scintillation look like wide-area jamming to a network and need a
check against space-weather bulletins before an incident is published; that
check is an operator step today.

## Part B. Threats to the system

Assets: contributor privacy and safety; integrity of the incident data;
availability of alerts; the trust of users who read "no incident".

### B1. Forged or poisoned data

| # | Threat | Effect | Mitigation | Residual risk |
|---|---|---|---|---|
| B1.1 | Fake events posted to the API | False incident; reputational damage; false alarms for customers | Device attestation on upload; per-token and per-network rate limits; incidents need `K` distinct tokens and a summed tier weight; physical plausibility check (does the pattern of C/N0 loss fit one source?) | A funded attacker with many real phones in one place can still forge an incident. Customer alerts show device count and confidence. |
| B1.2 | Sybil tokens from one device | Fake `K` | Token derives from a device secret bound to attestation; one token per device, day and region | Rooted devices that pass attestation |
| B1.3 | Masking: flooding an area with "clean" coverage pings | Real incident looks contradicted | Clean reports cannot delete an incident; they only shrink the affected-area estimate, and only when they come from tier A or B devices | Area estimate can be distorted |
| B1.4 | Replaying old uploads | Stale incidents | Server-side time window; nonces in the attested upload | - |
| B1.5 | Tampered app or SDK build | Any of the above | Signed releases; server accepts only known signing certificates through attestation | Fleet partners embedding an old SDK |
| B1.6 | Poisoned detector configuration | Detection silently disabled | `config/detector.json` is bundled and signed with the app; remote updates are signed and versioned | Key compromise |

### B2. Contributor privacy

| # | Threat | Mitigation | Residual risk |
|---|---|---|---|
| B2.1 | Server operator or breach reconstructs someone's movements | No tracks are collected. Tokens change every day and every H3 res 5 region, so records cannot be chained. Stored cells are coarsened to res 8. | Within one day and one region, a contributor's event cells are linkable. A person who triggers events at home and at work in the same region on the same day shows a two-point pattern. Coverage pings are res 7 only. |
| B2.2 | Public map reveals a single contributor | Public cells are res 6, `K >= 3`, quantised to 5 minutes and delayed | Very sparse areas show nothing at all, which costs coverage |
| B2.3 | Network observer links uploads by IP address | TLS; uploads batched with jitter; the server does not log IP addresses beyond rate limiting, held 24 h | The hosting provider still sees IP addresses |
| B2.4 | Fleet customer uses the SDK to track its own drivers | The SDK gives the host app the trust indicator and events for that device only, the same data the driver sees. It does not add tracking the host app could not already do with location permission. | Out of scope: the host app has location permission anyway |
| B2.5 | Exported validation logs contain full tracks | Export is manual, off by default, with a warning. Validation logs are stored outside the repository and never published raw. | Human error |
| B2.6 | Rare device model identifies a contributor | Uploads carry the tier only. The model name is sent once, separately and without a token, only if the user opts in to the public device matrix. | - |

### B3. Contributor safety and legal exposure

| # | Threat | Mitigation |
|---|---|---|
| B3.1 | In some countries, recording interference near military sites can be treated as intelligence gathering | `no_collection` regions disable logging in the app. The region list is a legal decision taken before launch in each market. The app explains this at opt-in. |
| B3.2 | A contributor is tempted to drive towards interference to "map" it | The app never rewards proximity, never shows a live direction to a source, and says so. Source estimates are not shown in the public app. |
| B3.3 | A user tests the app with a jammer | The app, the documentation and the validation notes state that transmitting is illegal and that no SpoofNet testing requires it. All test signals are synthetic and in software. |

### B4. Misuse of the output

| # | Threat | Mitigation | Residual risk |
|---|---|---|---|
| B4.1 | An interferer uses the map as a feedback loop: "was I detected, how far did I reach?" | Public delay and coarse cells; no public source estimate; no public per-device detail; thresholds are not shown in the app | A patient attacker still learns whether an area is covered. This is inherent in publishing coverage honestly, and the "no data" layer is kept because the alternative, implying safety, is worse. |
| B4.2 | Someone uses the coverage layer to choose where to interfere unobserved | Same as above | Same |
| B4.3 | A reader takes "no incident" as "safe" | The map and API never say "clean". They say "no incident detected" with the coverage level, and "no data" where coverage is below the minimum. Alerts include the coverage of the geofence. | Readers who ignore the legend |
| B4.4 | Precise source locations near sensitive sites are published where that is restricted | Region rules; precise estimates only to vetted customers and authorities; default is never to publish precise estimates | Wrong region configuration |
| B4.5 | Insurers or operators treat a replay-validated detector as field-proven | Evidence labels (`replay`, `real`) on every number, incident and export | - |
| B4.6 | A false incident diverts ships or grounds drones | Confidence, device count and evidence label on every alert; customers set their own confidence threshold | - |

### B5. Availability

| # | Threat | Mitigation |
|---|---|---|
| B5.1 | Wide-area jamming also degrades mobile data (shared timing, or deliberate) | Events are queued on the device and uploaded later with their original times; the incident appears late but is not lost. Time to detect is reported for the online case and stated as such. |
| B5.2 | API overload | Static public map served from cached tiles of aggregated data; ingest rate-limited per token |
| B5.3 | Battery drain makes users uninstall | Duty-cycled logging modes; battery cost is a tracked metric measured on real phones |

### B6. Device-level evasion

| # | Threat | Mitigation |
|---|---|---|
| B6.1 | Interference ramps up slowly so baselines adapt to it | Baselines freeze while any sub-score is elevated; the per-device elevation model is a long-term quantile and cannot be moved by minutes of data; the per-place table needs repeat visits on different days |
| B6.2 | Interference is always present at one place, so the place baseline learns it as a "tunnel" | Server-side place baselines compare a cell with its neighbours and with AGC-equipped devices; a cell that is "always bad" while AGC is low is flagged for review, not silenced |
| B6.3 | Spoofer mimics a hardware clock discontinuity | The counter comes from the phone's own hardware abstraction layer, not from the signal, so it cannot be set over the air |
| B6.4 | Network position is itself wrong or polluted | It is one input among several with a bounded weight; a mismatch alone does not open an event |

## Assumptions

* The phone's operating system and GNSS chipset report measurements honestly.
  A compromised phone is out of scope.
* Attestation raises the cost of forged uploads; it does not make them
  impossible.
* The simulator's attack models cover the classes in A1. Attack behaviour
  outside those classes is untested until real data exists.
