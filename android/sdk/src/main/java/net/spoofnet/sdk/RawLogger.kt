package net.spoofnet.sdk

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.GnssClock
import android.location.GnssMeasurement
import android.location.GnssMeasurementRequest
import android.location.GnssMeasurementsEvent
import android.location.GnssStatus
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Log
import androidx.core.content.ContextCompat
import java.util.concurrent.Executor

/**
 * Listens to GNSS measurements, GNSS status, gps and network fixes and the
 * motion sensors, all on one background thread, and fans each callback out to
 * the log file, the capability probe, the IMU summarizer and live listeners.
 *
 * Receive only: nothing here asks any radio to transmit.
 */
internal class RawLogger(
    context: Context,
    private val config: SpoofNetConfig,
    private val writer: LogWriter?,
    private val probe: CapabilityProbe,
    private val battery: BatteryMeter,
    private val listeners: List<LiveStatsListener>,
) {
    private val appContext = context.applicationContext
    private val locationManager = appContext.getSystemService(Context.LOCATION_SERVICE) as LocationManager
    private val sensorManager = appContext.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val imu = ImuSummarizer()

    private var thread: HandlerThread? = null
    private var handler: Handler? = null

    // Touched only on the logger thread.
    private var inOnPeriod = false
    private var stopping = false

    private val accelSensor: Sensor?
    private val accelUncalibrated: Boolean
    private val gyroSensor: Sensor?
    private val gyroUncalibrated: Boolean

    init {
        val uncalAccel = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER_UNCALIBRATED)
        accelUncalibrated = uncalAccel != null
        accelSensor = uncalAccel ?: sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        val uncalGyro = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE_UNCALIBRATED)
        gyroUncalibrated = uncalGyro != null
        gyroSensor = uncalGyro ?: sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
    }

    private val beginRunnable = Runnable { beginOnPeriod() }
    private val endRunnable = Runnable { endOnPeriod(scheduleNext = true) }
    private val batteryRunnable = object : Runnable {
        override fun run() {
            battery.sample()
            writer?.flush()
            handler?.postDelayed(this, BATTERY_INTERVAL_MS)
        }
    }

    fun start() {
        val fullTracking = config.fullTracking && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
        probe.setSessionInfo(
            config.mode,
            fullTracking,
            sensorLabel(accelSensor, accelUncalibrated),
            sensorLabel(gyroSensor, gyroUncalibrated),
        )
        val t = HandlerThread("SpoofNetLogger")
        t.start()
        val h = Handler(t.looper)
        thread = t
        handler = h
        h.post {
            battery.sample()
            beginOnPeriod()
        }
        h.postDelayed(batteryRunnable, BATTERY_INTERVAL_MS)
    }

    /** Blocks briefly so the closing records are on disk before the caller shares the file. */
    fun stop() {
        val h = handler ?: return
        val t = thread
        h.removeCallbacksAndMessages(null)
        h.post {
            stopping = true
            if (inOnPeriod) endOnPeriod(scheduleNext = false)
            battery.sample()
            writer?.writeLine(LogLines.snCap(probe.report().toJson().toString()))
            writer?.close()
        }
        t?.quitSafely()
        try {
            t?.join(STOP_JOIN_MS)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
        }
        handler = null
        thread = null
    }

    private fun hasFineLocation(): Boolean =
        ContextCompat.checkSelfPermission(appContext, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    private fun beginOnPeriod() {
        if (stopping) return
        val h = handler ?: return
        if (!hasFineLocation()) {
            Log.w(TAG, "Fine location permission missing; this on-period is skipped")
        } else {
            inOnPeriod = true
            writer?.writeLine(LogLines.snDuty(System.currentTimeMillis(), true))
            imu.reset()
            registerGnss(h)
            registerLocation(h)
            registerSensors(h)
        }
        if (config.mode.isDutyCycled) h.postDelayed(endRunnable, config.mode.onMillis)
    }

    private fun endOnPeriod(scheduleNext: Boolean) {
        if (inOnPeriod) {
            unregisterAll()
            imu.flush()?.let { writeImu(it) }
            writer?.writeLine(LogLines.snDuty(System.currentTimeMillis(), false))
            writer?.flush()
            inOnPeriod = false
        }
        if (scheduleNext && !stopping && config.mode.isDutyCycled) {
            handler?.postDelayed(beginRunnable, config.mode.offMillis)
        }
    }

    // Registration. Each function re-checks the permission right before the calls.

    @SuppressLint("MissingPermission")
    @Suppress("DEPRECATION")
    private fun registerGnss(h: Handler) {
        if (!hasFineLocation()) return
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val request = GnssMeasurementRequest.Builder()
                    .setFullTracking(config.fullTracking)
                    .build()
                val executor = Executor { r -> h.post(r) }
                locationManager.registerGnssMeasurementsCallback(request, executor, measurementCallback)
            } else {
                locationManager.registerGnssMeasurementsCallback(measurementCallback, h)
            }
            locationManager.registerGnssStatusCallback(statusCallback, h)
        } catch (e: SecurityException) {
            Log.w(TAG, "GNSS registration refused", e)
        } catch (e: IllegalArgumentException) {
            Log.w(TAG, "GNSS registration failed", e)
        }
    }

    @SuppressLint("MissingPermission")
    private fun registerLocation(h: Handler) {
        if (!hasFineLocation()) return
        // Separate listeners per provider: the gps chipset fix and the network fix are compared later,
        // and the fused provider is avoided because it would blend the two.
        requestProvider(LocationManager.GPS_PROVIDER, gpsListener, h)
        requestProvider(LocationManager.NETWORK_PROVIDER, networkListener, h)
    }

    @SuppressLint("MissingPermission")
    private fun requestProvider(provider: String, listener: LocationListener, h: Handler) {
        if (!hasFineLocation()) return
        if (!locationManager.allProviders.contains(provider)) {
            Log.i(TAG, "Provider $provider not present on this device")
            return
        }
        try {
            locationManager.requestLocationUpdates(provider, FIX_INTERVAL_MS, 0f, listener, h.looper)
        } catch (e: SecurityException) {
            Log.w(TAG, "Location updates refused for $provider", e)
        } catch (e: IllegalArgumentException) {
            Log.w(TAG, "Location updates failed for $provider", e)
        }
    }

    private fun registerSensors(h: Handler) {
        accelSensor?.let { sensorManager.registerListener(sensorListener, it, SENSOR_PERIOD_US, h) }
        gyroSensor?.let { sensorManager.registerListener(sensorListener, it, SENSOR_PERIOD_US, h) }
    }

    private fun unregisterAll() {
        try {
            locationManager.unregisterGnssMeasurementsCallback(measurementCallback)
            locationManager.unregisterGnssStatusCallback(statusCallback)
            locationManager.removeUpdates(gpsListener)
            locationManager.removeUpdates(networkListener)
        } catch (e: RuntimeException) {
            Log.w(TAG, "Unregistering location callbacks failed", e)
        }
        sensorManager.unregisterListener(sensorListener)
    }

    // Callbacks.

    private val measurementCallback = object : GnssMeasurementsEvent.Callback() {
        override fun onGnssMeasurementsReceived(eventArgs: GnssMeasurementsEvent) {
            onMeasurements(eventArgs)
        }

        @Suppress("OVERRIDE_DEPRECATION")
        override fun onStatusChanged(status: Int) {
            probe.onMeasurementStatus(status)
        }
    }

    private val statusCallback = object : GnssStatus.Callback() {
        override fun onSatelliteStatusChanged(status: GnssStatus) {
            onStatus(status)
        }
    }

    private val gpsListener = ProviderListener(LocationManager.GPS_PROVIDER)
    private val networkListener = ProviderListener(LocationManager.NETWORK_PROVIDER)

    private inner class ProviderListener(private val providerName: String) : LocationListener {
        override fun onLocationChanged(location: Location) {
            onFix(providerName, location)
        }

        // Overridden because the interface has no default bodies before API 30.
        @Deprecated("Required on API levels below 30")
        override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {
        }

        override fun onProviderEnabled(provider: String) {}

        override fun onProviderDisabled(provider: String) {}
    }

    private val sensorListener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            onSensor(event)
        }

        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
    }

    // Handlers, all on the logger thread.

    private fun onMeasurements(event: GnssMeasurementsEvent) {
        val utc = System.currentTimeMillis()
        probe.onMeasurementsEvent(event)
        val clock = clockValues(event.clock)

        val sats = HashSet<Long>()
        val cn0L1 = ArrayList<Double>()
        val cn0L5 = ArrayList<Double>()
        var agcL1: Double? = null
        var agcL5: Double? = null

        for (m in event.measurements) {
            val mv = measurementValues(m)
            writer?.writeLine(LogLines.raw(utc, clock, mv))
            sats.add(mv.constellationType.toLong() * 100_000L + mv.svid)
            when (GnssBands.bandOf(mv.carrierFrequencyHz?.toDouble())) {
                Band.L1 -> {
                    mv.cn0DbHz?.let { cn0L1.add(it) }
                    mv.agcDb?.let { agcL1 = it }
                }
                Band.L5 -> {
                    mv.cn0DbHz?.let { cn0L5.add(it) }
                    mv.agcDb?.let { agcL5 = it }
                }
                Band.OTHER -> {}
            }
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            for (agc in event.gnssAutomaticGainControls) {
                val level = agc.levelDb.toDouble()
                val freq = agc.carrierFrequencyHz.toLong()
                writer?.writeLine(LogLines.agc(utc, clock, level, freq, agc.constellationType))
                when (GnssBands.bandOf(freq.toDouble())) {
                    Band.L1 -> agcL1 = level
                    Band.L5 -> agcL5 = level
                    Band.OTHER -> {}
                }
            }
        }

        val stats = LiveStats(
            utcMillis = utc,
            satelliteCount = sats.size,
            medianCn0L1DbHz = GnssBands.median(cn0L1),
            medianCn0L5DbHz = GnssBands.median(cn0L5),
            agcL1Db = agcL1,
            agcL5Db = agcL5,
            hardwareClockDiscontinuityCount = clock.hardwareClockDiscontinuityCount,
        )
        for (listener in listeners) {
            try {
                listener.onLiveStats(stats)
            } catch (e: RuntimeException) {
                // A faulty host listener must not stop the logging thread.
                Log.w(TAG, "LiveStatsListener threw", e)
            }
        }
    }

    private fun onStatus(status: GnssStatus) {
        val w = writer ?: return
        val utc = System.currentTimeMillis()
        val n = status.satelliteCount
        for (k in 0 until n) {
            val freq = if (status.hasCarrierFrequencyHz(k)) status.getCarrierFrequencyHz(k) else null
            val baseband = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && status.hasBasebandCn0DbHz(k)) {
                status.getBasebandCn0DbHz(k)
            } else {
                null
            }
            w.writeLine(
                LogLines.status(
                    unixTimeMillis = utc,
                    signalCount = n,
                    signalIndex = k,
                    constellationType = status.getConstellationType(k),
                    svid = status.getSvid(k),
                    carrierFrequencyHz = freq,
                    cn0DbHz = status.getCn0DbHz(k),
                    azimuthDegrees = status.getAzimuthDegrees(k),
                    elevationDegrees = status.getElevationDegrees(k),
                    usedInFix = status.usedInFix(k),
                    hasAlmanacData = status.hasAlmanacData(k),
                    hasEphemerisData = status.hasEphemerisData(k),
                    basebandCn0DbHz = baseband,
                ),
            )
        }
    }

    private fun onFix(provider: String, loc: Location) {
        writer?.writeLine(
            LogLines.fix(
                provider = provider,
                latitudeDegrees = loc.latitude,
                longitudeDegrees = loc.longitude,
                altitudeMeters = if (loc.hasAltitude()) loc.altitude else null,
                speedMps = if (loc.hasSpeed()) loc.speed else null,
                accuracyMeters = if (loc.hasAccuracy()) loc.accuracy else null,
                bearingDegrees = if (loc.hasBearing()) loc.bearing else null,
                unixTimeMillis = loc.time,
                speedAccuracyMps = if (loc.hasSpeedAccuracy()) loc.speedAccuracyMetersPerSecond else null,
                bearingAccuracyDegrees = if (loc.hasBearingAccuracy()) loc.bearingAccuracyDegrees else null,
                elapsedRealtimeNanos = loc.elapsedRealtimeNanos,
                verticalAccuracyMeters = if (loc.hasVerticalAccuracy()) loc.verticalAccuracyMeters else null,
            ),
        )
    }

    private fun onSensor(event: SensorEvent) {
        val v = event.values
        if (v.size < 3) return
        val t = event.timestamp
        // Sensor timestamps share the elapsedRealtimeNanos base on current devices; UTC is derived from it.
        val utc = System.currentTimeMillis() -
            (SystemClock.elapsedRealtimeNanos() - t) / 1_000_000L
        val hasBias = v.size >= 6
        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER_UNCALIBRATED, Sensor.TYPE_ACCELEROMETER -> {
                val bx = if (hasBias) v[3] else 0f
                val by = if (hasBias) v[4] else 0f
                val bz = if (hasBias) v[5] else 0f
                if (config.logRawImu) {
                    writer?.writeLine(
                        LogLines.uncalAccel(
                            utc, t, v[0], v[1], v[2],
                            if (hasBias) bx else null, if (hasBias) by else null, if (hasBias) bz else null,
                        ),
                    )
                }
                val summary = imu.addAccel(
                    t,
                    (v[0] - bx).toDouble(),
                    (v[1] - by).toDouble(),
                    (v[2] - bz).toDouble(),
                )
                summary?.let { writeImu(it) }
            }
            Sensor.TYPE_GYROSCOPE_UNCALIBRATED, Sensor.TYPE_GYROSCOPE -> {
                val dx = if (hasBias) v[3] else 0f
                val dy = if (hasBias) v[4] else 0f
                val dz = if (hasBias) v[5] else 0f
                if (config.logRawImu) {
                    writer?.writeLine(
                        LogLines.uncalGyro(
                            utc, t, v[0], v[1], v[2],
                            if (hasBias) dx else null, if (hasBias) dy else null, if (hasBias) dz else null,
                        ),
                    )
                }
                imu.addGyro(t, (v[0] - dx).toDouble(), (v[1] - dy).toDouble(), (v[2] - dz).toDouble())
            }
        }
    }

    private fun writeImu(s: ImuSummary) {
        val utc = System.currentTimeMillis() -
            (SystemClock.elapsedRealtimeNanos() - s.endNanos) / 1_000_000L
        writer?.writeLine(LogLines.snImu(utc, s.endNanos, s))
    }

    // Extraction from framework objects into plain values.

    private fun clockValues(c: GnssClock): ClockValues = ClockValues(
        timeNanos = c.timeNanos,
        leapSecond = if (c.hasLeapSecond()) c.leapSecond else null,
        timeUncertaintyNanos = if (c.hasTimeUncertaintyNanos()) c.timeUncertaintyNanos else null,
        fullBiasNanos = if (c.hasFullBiasNanos()) c.fullBiasNanos else null,
        biasNanos = if (c.hasBiasNanos()) c.biasNanos else null,
        biasUncertaintyNanos = if (c.hasBiasUncertaintyNanos()) c.biasUncertaintyNanos else null,
        driftNanosPerSecond = if (c.hasDriftNanosPerSecond()) c.driftNanosPerSecond else null,
        driftUncertaintyNanosPerSecond =
            if (c.hasDriftUncertaintyNanosPerSecond()) c.driftUncertaintyNanosPerSecond else null,
        hardwareClockDiscontinuityCount = c.hardwareClockDiscontinuityCount,
        elapsedRealtimeNanos =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && c.hasElapsedRealtimeNanos()) {
                c.elapsedRealtimeNanos
            } else {
                null
            },
    )

    @Suppress("DEPRECATION")
    private fun measurementValues(m: GnssMeasurement): MeasurementValues {
        var baseband: Double? = null
        var fullIsb: Double? = null
        var fullIsbUnc: Double? = null
        var satIsb: Double? = null
        var satIsbUnc: Double? = null
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            if (m.hasBasebandCn0DbHz()) baseband = m.basebandCn0DbHz
            if (m.hasFullInterSignalBiasNanos()) fullIsb = m.fullInterSignalBiasNanos
            if (m.hasFullInterSignalBiasUncertaintyNanos()) fullIsbUnc = m.fullInterSignalBiasUncertaintyNanos
            if (m.hasSatelliteInterSignalBiasNanos()) satIsb = m.satelliteInterSignalBiasNanos
            if (m.hasSatelliteInterSignalBiasUncertaintyNanos()) satIsbUnc = m.satelliteInterSignalBiasUncertaintyNanos
        }
        var codeType: String? = null
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            if (m.hasCodeType()) codeType = m.codeType
        }
        return MeasurementValues(
            svid = m.svid,
            timeOffsetNanos = m.timeOffsetNanos,
            state = m.state,
            receivedSvTimeNanos = m.receivedSvTimeNanos,
            receivedSvTimeUncertaintyNanos = m.receivedSvTimeUncertaintyNanos,
            cn0DbHz = m.cn0DbHz,
            pseudorangeRateMetersPerSecond = m.pseudorangeRateMetersPerSecond,
            pseudorangeRateUncertaintyMetersPerSecond = m.pseudorangeRateUncertaintyMetersPerSecond,
            accumulatedDeltaRangeState = m.accumulatedDeltaRangeState,
            accumulatedDeltaRangeMeters = m.accumulatedDeltaRangeMeters,
            accumulatedDeltaRangeUncertaintyMeters = m.accumulatedDeltaRangeUncertaintyMeters,
            carrierFrequencyHz = if (m.hasCarrierFrequencyHz()) m.carrierFrequencyHz else null,
            carrierCycles = if (m.hasCarrierCycles()) m.carrierCycles else null,
            carrierPhase = if (m.hasCarrierPhase()) m.carrierPhase else null,
            carrierPhaseUncertainty = if (m.hasCarrierPhaseUncertainty()) m.carrierPhaseUncertainty else null,
            multipathIndicator = m.multipathIndicator,
            snrInDb = if (m.hasSnrInDb()) m.snrInDb else null,
            constellationType = m.constellationType,
            agcDb = if (m.hasAutomaticGainControlLevelDb()) m.automaticGainControlLevelDb else null,
            basebandCn0DbHz = baseband,
            fullInterSignalBiasNanos = fullIsb,
            fullInterSignalBiasUncertaintyNanos = fullIsbUnc,
            satelliteInterSignalBiasNanos = satIsb,
            satelliteInterSignalBiasUncertaintyNanos = satIsbUnc,
            codeType = codeType,
        )
    }

    private fun sensorLabel(sensor: Sensor?, uncalibrated: Boolean): String? = when {
        sensor == null -> null
        uncalibrated -> "uncalibrated"
        else -> "calibrated"
    }

    companion object {
        private const val TAG = "SpoofNetLogger"
        private const val SENSOR_PERIOD_US = 20_000 // 50 Hz
        private const val FIX_INTERVAL_MS = 1_000L
        private const val BATTERY_INTERVAL_MS = 60_000L
        private const val STOP_JOIN_MS = 1_500L
    }
}
