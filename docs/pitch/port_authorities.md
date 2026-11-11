# SpoofNet for port authorities and harbour masters

## The problem you have

Jamming or spoofing in your approaches corrupts AIS positions and takes a reference away from pilots and tugs, where ships are closest together. You usually hear about it afterwards, from one crew. Today's interference maps are built from aircraft, and GPSJam itself warns that aircraft fly far above the ground, so its map may not match conditions at the surface ([GPSJam FAQ](https://gpsjam.org/faq/)).

## What SpoofNet gives you

SpoofNet is designed to map interference at ground and sea level from ordinary phones. It only listens.

- **A geofenced alert for your port and channels,** so you can decide when to warn traffic or ask pilots to cross-check positions.
- **An incident history for an investigation,** with time, type, confidence and coverage, for reviewing a near miss or answering a regulator.
- **A source estimate with an uncertainty ellipse,** for authorities only, when several devices saw one event, to support a referral to the radio regulator.

## What it cannot do

- Coverage exists only where contributors are, and today there are none. A quay with no phones nearby shows as "no data", never as clean.
- Ports are full of steel. Phones without AGC cannot tell strong wideband jamming from total blockage behind cranes or stacks on their own. Those cases are reported as "unknown loss".
- Nothing has been validated on real interference.

## Why you would pay

The buyer is the harbour master or the head of nautical safety. Where you act as a maritime safety authority, incident data is free. *Assumption:* a port would pay for geofence alerts and exports from its nautical safety budget. *Assumption:* ports will pay once it is validated. We have not tested this.

## The pilot we are asking for

You run the free app on the work phones of six pilot boats, tugs or patrol craft for eight weeks. VTS logs every GNSS report from ships and pilots. The pilot starts only after the app has passed its own field test.

We measure whether SpoofNet incidents match the VTS log in time and place, how often phones report "unknown loss" at known blockage spots, and how much of your area stays "no data".

**Stop condition.** If VTS logs three or more GNSS reports in areas our phones covered at the time and SpoofNet records none, we stop. We also stop if SpoofNet raises alerts on your geofence on two or more days that nobody else can support.

> **Status, 11 November 2026.** SpoofNet works in software replay. On real phone data it has been run on five public logs, one of them a flight through a documented interference area, where it raised one jamming event that matches the aircraft-based map. It has not been validated at ground or sea level on real interference, and the phone app has not yet been built or field-tested. Measured results, with what failed, are in the [technical validation note](technical_validation_note.md).
