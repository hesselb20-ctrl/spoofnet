# SpoofNet for Android (milestone 1)

An Android app and an embeddable SDK that passively log raw GNSS measurements
and report what the phone's GNSS hardware can do. This milestone is logging and
capability probing only; detectors arrive in a later milestone.

**Passive only.** The code registers listeners for GNSS measurements, GNSS
status, location fixes and motion sensors. It never transmits and never asks the
phone to transmit. Transmitting on GNSS frequencies is illegal almost everywhere,
and no SpoofNet test needs it: all interference used in development is synthetic,
in software replay.

## Layout

| Module | Package | What it is |
|---|---|---|
| `:sdk` | `net.spoofnet.sdk` | Android library: `SpoofNetSdk` facade, `RawLogger`, `CapabilityProbe` and `CapabilityReport`, `LogWriter` and `LogLines`, `ImuSummarizer`, `BatteryMeter`, `LoggingMode`, `ContributorToken` |
| `:app` | `net.spoofnet.app` | The SpoofNet app: opt-in, start/stop, mode picker, live values, capability report, manual export, battery summary. `LoggingService` is the foreground service that owns the session. |

Versions: Android Gradle Plugin 8.7.3, Kotlin 2.0.21, compileSdk and targetSdk 35,
minSdk 26, Java 17. Dependencies are `androidx.core:core-ktx`,
`androidx.appcompat:appcompat`, `com.google.android.material:material` and
JUnit 4 for tests. Nothing else.

## Build

There is no Gradle wrapper jar in the repository. Either:

* **Android Studio** (Ladybug 2024.2 or newer): *File > Open*, pick the `android/`
  folder. Studio offers to create the wrapper and downloads Gradle and the SDK
  platform it needs.
* **Command line**, with a local Gradle 8.9 or newer and `ANDROID_HOME` set:

  ```
  cd android
  gradle wrapper --gradle-version 8.10.2
  ./gradlew :sdk:testDebugUnitTest      # JVM unit tests
  ./gradlew :app:assembleDebug          # app/build/outputs/apk/debug/app-debug.apk
  ./gradlew :app:installDebug           # onto a connected phone
  ```

The SDK unit tests cover the pure classes: log line formatting (empty fields,
locale independence), `ImuSummarizer`, `CapabilityReport.tier()`, and
`ContributorToken` against a value computed independently in Python.

## Using the SDK in a host app

```kotlin
// After the host has been granted ACCESS_FINE_LOCATION:
val started = SpoofNetSdk.start(context, SpoofNetConfig(mode = LoggingMode.BALANCED))
SpoofNetSdk.addLiveStatsListener { stats -> /* background thread */ }
val report = SpoofNetSdk.capabilityReport()   // any time, also after stop
val file = SpoofNetSdk.currentLogFile()
SpoofNetSdk.stop()
```

The host declares the permissions; the SDK manifest declares none. For logging in
the background the host must run the session from its own foreground service of
type `location`, as `LoggingService` does. `SpoofNetSdk.trustState()` reports only
`UNKNOWN` or `LOGGING` in this milestone.

## Permissions

| Permission | Why |
|---|---|
| `ACCESS_FINE_LOCATION` (with `ACCESS_COARSE_LOCATION`) | Raw GNSS measurements and fixes. Requested first. Android 12+ needs both in one request; approximate location alone is not enough. |
| `POST_NOTIFICATIONS` | Android 13+, so the logging notification is visible. Requested second. Logging works without it. |
| `ACCESS_BACKGROUND_LOCATION` | Optional, requested later as a separate step with an explanation. The foreground service already keeps logging alive; some manufacturers still cut background location without it. |
| `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION` | The foreground service of type `location` (the second one is required on Android 14+). |

**There is no `INTERNET` permission.** Nothing is uploaded in this milestone, so
the app is unable to send data anywhere; it can be checked in the merged manifest
(`app/build/intermediates/merged_manifests/`). `allowBackup` is off, so logs are not
copied into cloud backups either.

## Logging modes

| Mode | Pattern | Use |
|---|---|---|
| `CONTINUOUS` | always on, 1 Hz | baseline collection, short sessions |
| `BALANCED` | 20 s on, 100 s off | all-day background logging |
| `SAVER` | 15 s every 5 minutes | coverage only |

Duty cycling registers and unregisters the GNSS callbacks, location updates and
sensors from a `Handler`. Every on and off boundary is written as a comment line
`# SnDuty,<utcTimeMillis>,<on|off>`, so analysis can tell a deliberate gap from a
loss of signal. Each on-period starts a cold measurement stream, so expect a
hardware clock discontinuity and ADR resets at every boundary in the duty-cycled
modes; the capability report records the mode for that reason.

On Android 12+ the GNSS measurement request asks for full tracking
(`GnssMeasurementRequest.setFullTracking(true)`), which stops the chipset from
duty-cycling internally. It costs battery and can be turned off with
`SpoofNetConfig(fullTracking = false)`.

## Log files

* Location: the app-specific external files directory,
  `/sdcard/Android/data/net.spoofnet.app/files/logs/` (falls back to internal
  storage if external storage is not mounted). No storage permission is needed and
  the files are removed when the app is uninstalled.
* Name: `spoofnet_<yyyyMMdd_HHmmss>_<model>.txt`, time in UTC.
* Format: Google GnssLogger text format, so existing tools and public datasets
  can be read the same way. Header lines start with `# <Record>,<fields>`; data
  lines start with the record name. `Raw`, `Fix`, `Status`, `Agc` (Android 13+),
  optional `UncalAccel`/`UncalGyro` (50 Hz, off by default), plus SpoofNet's
  `SnImu` (1 Hz motion summary), `SnBat` (once a minute), `SnCap` (one JSON line,
  the capability report, when the session stops) and `# SnDuty` comments.
* A field the phone does not provide is empty (two adjacent commas). Numbers never
  use the phone's locale: raw values are plain decimals with the shortest digits
  that read back exactly, derived values use fixed decimals with `Locale.US`.
* `Fix` lines carry the provider name as Android reports it, `gps` or `network`.
  The fused provider is never used.
* If the phone has no uncalibrated accelerometer or gyroscope, the calibrated
  sensor is used, its samples go into `UncalAccel`/`UncalGyro` with empty bias
  columns, and the capability report says `calibrated`.

### Exporting a file

Raw logs never leave the phone on their own. To export one, tap **Share current
log file**: the Android share sheet opens with the file (through a
`FileProvider`), and you choose where it goes. Alternatively, with USB debugging:

```
adb pull /sdcard/Android/data/net.spoofnet.app/files/logs/
```

A log contains positions. Share it only with people you trust.

## Collecting a baseline log

Baselines are clean recordings that later tell the detectors what "normal" looks
like for a phone model in a kind of place. Use **Continuous** mode, start logging,
and wait until the satellite count is stable (one to two minutes after a cold
start). Record at least 20 minutes per session. Note the time, place type and how
the phone was carried; that goes into the validation notes, not the app.

| Environment | How |
|---|---|
| Open sky | Phone flat and still, screen up, away from buildings and trees (a field or a rooftop). This is the reference for C/N0 and AGC. |
| Urban canyon | Walk a street with tall buildings on both sides, phone in hand, then in a pocket. Expect multipath, lower C/N0 and frequent signal loss. |
| Car | Phone in a holder near the windscreen, a mix of town, motorway and a tunnel or underpass if there is one on the route. The tunnel is a natural signal loss the detectors must not call jamming. |
| Boat | Phone on deck or near a window with sky view. Note that there is often no network position at sea. |

Only record where it is lawful and safe. The app does not point you towards
interference and does not reward getting closer to it; do not go looking for it.
In some countries recording interference near military sites may be restricted,
and the person logging is responsible for local law.

## Measuring battery cost

`BatteryMeter` reads `BATTERY_PROPERTY_CHARGE_COUNTER` (microampere-hours),
`BATTERY_PROPERTY_CAPACITY` (percent), the charging state and the screen state at
start, once a minute, and at stop, into `SnBat` lines. The app shows a session
summary: hours, mAh used, percent used and percent per day extrapolated from the
session. Percent is computed from the charge counter when the phone reports one
(much finer than the 1 % capacity steps), otherwise from capacity.

For a figure worth reporting (DESIGN.md section 13: below 5 % per day, stretch 2 %):

1. Charge to about 90 %, unplug, and leave the phone unplugged for the whole run;
   the summary is marked invalid if the phone charged at any point.
2. Run each mode for at least 8 hours, screen off, with the same apps and radio
   settings as the comparison run.
3. Record one run with logging stopped as the idle baseline. The cost of logging
   is the difference between the two per-day figures.
4. Report the phone model, Android version, mode and both runs. Some phones
   report the charge counter in the wrong unit or not at all; check that the mAh
   figure is plausible for the battery size.

Sessions shorter than 15 minutes show no per-day figure.

## Status

**This code has not yet been compiled or run on a device.** It was written
without a JDK, Gradle or the Android SDK available. On the first build, check:

1. Gradle sync succeeds with AGP 8.7.3 and Kotlin 2.0.21, and `kotlinOptions`
   is accepted (it is deprecated in later Kotlin versions).
2. The SDK unit tests pass: `./gradlew :sdk:testDebugUnitTest`.
3. These framework calls compile with the stated types and API guards:
   `LocationManager.registerGnssMeasurementsCallback(GnssMeasurementRequest, Executor, Callback)`
   and `GnssMeasurementRequest.Builder().setFullTracking()` (API 31);
   `LocationManager.getGnssCapabilities()` with `hasMeasurements()` and
   `hasNavigationMessages()` (API 31);
   `GnssMeasurementsEvent.getGnssAutomaticGainControls()` and
   `GnssAutomaticGainControl.getLevelDb()` / `getCarrierFrequencyHz()` /
   `getConstellationType()` (API 33);
   the `LocationListener` overrides (`onStatusChanged` must stay for API < 30).
4. Lint: no `MissingPermission` or `NewApi` errors (`./gradlew lint`).
5. On a phone: the opt-in shows once; the permission order is precise location,
   then notifications (Android 13+), then background location only from its own
   button; the notification appears and logging continues with the screen off.
6. The log file opens, has the header lines, `Raw` lines have the same number of
   columns as the `# Raw` header, `# SnDuty` lines appear at on/off boundaries in
   Balanced and Saver modes, and an `SnCap` line is the last line after stop.
7. Sensor timestamps are assumed to share the `elapsedRealtimeNanos` base; check
   that `SnImu` UTC times line up with `Raw` UTC times within a second.
8. The capability report on a dual-frequency phone shows `dual_frequency: true`
   and a carrier list containing about 1176.45 MHz; on a phone with AGC it shows
   AGC values that change when the phone is moved from open sky to indoors.
9. Share opens the share sheet and the receiving app can read the file.
10. Battery figures are plausible against the phone's battery settings screen.
