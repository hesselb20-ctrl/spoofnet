# Responsible disclosure and data for safety authorities

## Reporting a problem with SpoofNet

If you find a way to forge incidents, to learn anything about a contributor, or
to read data you should not see, report it privately before publishing.

* Contact: `security@<project domain>` (to be set when the project has a domain).
  Until then, open a private security advisory on the code host.
* Include what you did, what you saw, and how to reproduce it.
* We acknowledge within 5 working days and aim to fix or mitigate within 90 days.
* Good-faith research that does not transmit on GNSS bands, does not degrade the
  service and does not touch other people's data is welcome.

Testing with a transmitter is never acceptable. Transmitting on GNSS frequencies
is illegal almost everywhere and endangers aviation and shipping. No part of
SpoofNet needs it: every test signal is synthetic and lives in software.

## Incident data for aviation and maritime safety authorities

Safety authorities get incident data free of charge.

* What: incidents with type, time, affected area, confidence, device count,
  coverage, the evidence label (`replay` or `real`) and, for vetted authority
  accounts, the source estimate with its 95 % uncertainty ellipse.
* How: an API key with the `vetted` tier. The same API as customers, no fee.
* Who qualifies: civil aviation authorities, air navigation service providers,
  maritime administrations, coast guards, spectrum regulators and national
  CERTs. Requests are checked against an official address.
* What we ask in return: tell us when an incident we reported was confirmed or
  refuted. Ground truth is the scarcest thing this project has.

## What we will not provide to anyone

Contributor identities, device identifiers or movement tracks. They are not
collected, so they cannot be disclosed (`DESIGN.md` section 9).
