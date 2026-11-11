# SpoofNet for precision agriculture: RTK farms, contractors and co-operatives

## The problem you have

When GNSS is jammed, an RTK-guided tractor loses its fix and the driver stops or steers by hand, often inside a narrow sowing or spraying window. You rarely know whether the receiver, the correction link or interference was to blame. Today's interference maps are built from aircraft, and GPSJam itself warns that aircraft fly far above the ground, so its map may not match what a receiver in a field sees ([GPSJam FAQ](https://gpsjam.org/faq/)).

## What SpoofNet gives you

SpoofNet is designed to detect interference on ordinary Android phones. It only listens.

- **A geofenced alert for your fields,** so you can decide whether to start an RTK job now or switch to work that needs no guidance.
- **An incident history for a field and a date,** to tell interference from an equipment fault before you call the dealer.
- **A daily risk map for your area,** showing whether trouble keeps coming back.

## What it cannot do

- Coverage exists only where contributors are, and rural areas have few phones. Today there are none. A field nobody works with the app shows as "no data", never as clean.
- SpoofNet does not see your correction link or tractor receiver, so their faults will not show.
- Phones without AGC cannot tell strong wideband jamming from total blockage, such as a phone face down under a metal roof, on their own.

## Why you would pay

The buyer is the contractor owner, a farm operations manager, or a co-operative's precision farming lead. *Assumption:* the money comes from the budget for RTK correction subscriptions. The reason is knowing when interference stops RTK work. *Assumption:* this is worth paying for once validated. We have not tested this.

## The pilot we are asking for

You mount phones running the free app in ten tractor cabs for six weeks of one season. Drivers log every RTK dropout and its suspected cause. The pilot starts only after the app has passed its own field test.

We measure whether SpoofNet incidents match the dropouts in time and place, and how much of your area stays "no data".

**Stop condition.** If drivers log three or more dropouts that neither receiver logs nor dealer can explain, with our phones running in those cabs, and SpoofNet records none, we stop. We also stop if SpoofNet raises alerts on your fields on two or more days with no dropout on any tractor.

> **Status, 11 November 2026.** SpoofNet works in software replay. On real phone data it has been run on five public logs, one of them a flight through a documented interference area, where it raised one jamming event that matches the aircraft-based map. It has not been validated at ground or sea level on real interference, and the phone app has not yet been built or field-tested. Measured results, with what failed, are in the [technical validation note](technical_validation_note.md).
