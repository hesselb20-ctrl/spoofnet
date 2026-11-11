# Device capability matrix

A phone is listed here only after a real capability report from that phone
exists (the `SnCap` line the app writes when a logging session stops).

**No phone has been tested yet.** The app in `android/` has not been built or
run on a device, so this table is empty on purpose.

| Phone | Android | Chipset | Raw | AGC (changes) | Dual frequency | ADR valid | Duty cycling seen | C/N0 step | Tier | Report date |
|---|---|---|---|---|---|---|---|---|---|---|
| none yet | | | | | | | | | | |

## How a phone gets into the table

1. Install the app, opt in, log for at least 20 minutes under open sky in
   Continuous mode, then stop.
2. Share the log file. The last line starts with `SnCap,` and holds the report.
3. Run `python -m spoofnet.io.gnsslogger --capability <file>` to print the row.
4. Add the row with the date. Keep the raw log out of the repository.

Tiers are defined in `DESIGN.md` section 4. The simulator uses four generic
device archetypes (`spoofnet/sim/devices.py`). They are not real phones and are
not listed here.
