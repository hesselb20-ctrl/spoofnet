# SpoofNet for marine insurers and war-risk underwriters

## The problem you have

Jamming and spoofing put ships in the wrong place, which feeds groundings, collisions and disputes over whether a vessel entered a listed area. Today's interference maps are built from aircraft reports, and GPSJam itself warns that aircraft fly far above the ground, so its map may not match conditions at the surface ([GPSJam FAQ](https://gpsjam.org/faq/)).

## What SpoofNet gives you

SpoofNet is designed to map interference at sea level from phones carried on board. It only listens.

- **An incident history for a claim.** Incidents near a vessel's route and time, with type, confidence, device count and coverage, to judge whether a reported position anomaly is plausible.
- **Daily risk heatmaps for routes and sea areas,** for setting voyage conditions.
- **Geofenced alerts** for the straits and anchorages you watch, so you know when to contact an insured about routing.

## What it cannot do

- Coverage exists only where contributors are, and today there are none. A route without phones aboard shows as "no data", never as clean.
- At sea there is no network position to cross-check against, and a careful, slow drag-off attack on one ship can stay hidden. A quiet history guarantees nothing.
- Until it is validated on real interference, treat the output as supporting information, not evidence.

## Why you would pay

The buyer is the head of marine or war-risk underwriting, or the claims analytics team. *Assumption:* it comes from the budget for maritime data feeds. The reason is a ground-level record for pricing areas and checking claims. *Assumption:* underwriters will pay for that once it is validated. We have not tested this.

## The pilot we are asking for

You introduce one insured shipowner who runs the free app on crew phones on five vessels for eight weeks, on routes that aircraft maps show as affected. The bridge logs its own GNSS alarms. The pilot starts only after the app has passed its own field test.

We measure whether SpoofNet incidents match the bridge log in time and place, how much of each route is "no data", and whether your claims team can use the export in a mock claim file.

**Stop condition.** If the bridges log three or more GNSS alarms while our phones were running and SpoofNet records none, we stop. We also stop if SpoofNet reports incidents on two or more days that neither the bridge nor aircraft maps support.

> **Status, 11 November 2026.** SpoofNet works in software replay. On real phone data it has been run on five public logs, one of them a flight through a documented interference area, where it raised one jamming event that matches the aircraft-based map. It has not been validated at ground or sea level on real interference, and the phone app has not yet been built or field-tested. Measured results, with what failed, are in the [technical validation note](technical_validation_note.md).
