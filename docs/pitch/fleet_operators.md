# SpoofNet for road and maritime fleet operators

## The problem you have

When GNSS is jammed or spoofed, your trucks, taxis, ferries and fishing boats report wrong positions or none. Dispatch makes bad calls, and drivers get blamed for gaps they did not cause. Today's interference maps are built from aircraft, and GPSJam itself warns that aircraft fly far above the ground, so its map may not match what a receiver on a road or deck sees ([GPSJam FAQ](https://gpsjam.org/faq/)).

## What SpoofNet gives you

SpoofNet is designed to detect interference on ordinary Android phones. It only listens. It comes as an SDK for the driver or crew app you already run.

- **A trust indicator on each device,** so a driver or skipper knows when to stop relying on GPS.
- **Geofenced alerts for depots, routes and fishing grounds,** so dispatch can decide whether to reroute or pause position-based automation.
- **An incident history for a dispute,** showing whether interference was recorded nearby at that time.

Detection runs on the phone, and no tracks leave it.

## What it cannot do

- Coverage exists only where contributors are, and today there are none. At the start your fleet would be your only coverage. Elsewhere shows as "no data", never as clean.
- Phones without AGC cannot tell strong wideband jamming from total blockage, such as a tunnel, on their own. Some Android phones also pause background GNSS.
- At sea there is no network position to cross-check against, which weakens spoofing checks on ferries and fishing boats.

## Why you would pay

The buyer is the head of fleet operations or fleet safety. *Assumption:* the money comes from the telematics budget. The reason is better dispatch decisions and disputes settled with a record. *Assumption:* this saves more than it costs, and operators will pay once it is validated. We have not tested this.

## The pilot we are asking for

You add the SDK to the app in one depot of 20 vehicles, or on six vessels, for eight weeks. Dispatch logs every position problem. The pilot starts only after the SDK has passed its own field test.

We measure whether SpoofNet incidents match the dispatch log, how often phones report "unknown loss" in tunnels, and the battery cost.

**Stop condition.** If dispatch logs three or more interference-type position problems while our SDK was running and SpoofNet records none, we stop. We also stop if drivers judge a "do not rely on GPS" warning false on two or more days.

> **Status, 11 November 2026.** SpoofNet works in software replay. On real phone data it has been run on five public logs, one of them a flight through a documented interference area, where it raised one jamming event that matches the aircraft-based map. It has not been validated at ground or sea level on real interference, and the phone app has not yet been built or field-tested. Measured results, with what failed, are in the [technical validation note](technical_validation_note.md).
