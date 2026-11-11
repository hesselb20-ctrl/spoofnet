# SpoofNet for telecom operators and other users of GNSS timing

## The problem you have

Many cell sites and data centres take their time reference from GNSS. Jamming sends them into holdover; time spoofing can push them off quietly. Today's interference maps are built from aircraft, and GPSJam itself warns that aircraft fly far above the ground, so its map may not match what a rooftop antenna sees ([GPSJam FAQ](https://gpsjam.org/faq/)).

## What SpoofNet gives you

SpoofNet is designed to detect jamming and spoofing, including attacks on time alone, on ordinary Android phones. It only listens.

- **A geofenced alert around your sites,** so your operations centre can check that site's timing early.
- **An incident history for a site and time window,** for root-cause analysis: outside interference, or a failing antenna or receiver.
- **Source estimates with an uncertainty ellipse,** for vetted customers only, when several devices saw one event, to support a report to the radio regulator.

## What it cannot do

- SpoofNet sees what phones see, not what your timing receiver sees. An alert is a reason to check a site, not a measurement of it.
- A careful, slow drag-off attack can stay hidden from a single phone, so detection depends on several devices nearby. Today there are no contributors at all. A site with no phones nearby shows as "no data", never as clean.
- Phones inside a data hall see too little sky to monitor it.

## Why you would pay

The buyer is the head of synchronisation engineering or network assurance. *Assumption:* the money comes from the budget for timing monitoring. The reason is an outside view of interference, which no timing receiver can give about itself. *Assumption:* this is worth paying for once validated. We have not tested this.

## The pilot we are asking for

You run the free app, or the SDK in your field app, on the phones of 30 field engineers for eight weeks in one region. You share site-level timing alarms for that region. The pilot starts only after the app has passed its own field test.

We measure whether SpoofNet incidents line up in time and place with those alarms, and how much of the region stays "no data".

**Stop condition.** If your sites log three or more timing alarms your engineers attribute to interference, where our phones were present, and SpoofNet records none, we stop. We also stop if SpoofNet raises alerts on two or more days at sites whose timing receivers saw nothing.

> **Status, 11 November 2026.** SpoofNet works in software replay. On real phone data it has been run on five public logs, one of them a flight through a documented interference area, where it raised one jamming event that matches the aircraft-based map. It has not been validated at ground or sea level on real interference, and the phone app has not yet been built or field-tested. Measured results, with what failed, are in the [technical validation note](technical_validation_note.md).
