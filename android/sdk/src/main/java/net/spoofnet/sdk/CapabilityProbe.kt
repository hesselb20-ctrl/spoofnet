package net.spoofnet.sdk

import android.content.Context
import android.location.GnssMeasurement
import android.location.GnssMeasurementsEvent
import android.location.LocationManager
import android.os.Build
import android.os.SystemClock
import java.util.TreeSet
import kotlin.math.abs
import kotlin.math.roundToLong

/**
 * Accumulates capability evidence from the same callbacks the logger sees.
 * Callbacks arrive on the logger thread while [report] may be called from the
 * UI thread, hence the synchronization.
 */
class CapabilityProbe(context: Context) {

    private val locationManager =
        context.applicationContext.getSystemService(Context.LOCATION_SERVICE) as LocationManager
    private val sessionStartUtcMillis = System.currentTimeMillis()

    private var measurementStatus: Int? = null
    private var eventCount = 0L
    private var measurementCount = 0L

    private var lastEventElapsedNanos = -1L
    private var intervalSumS = 0.0
    private var intervalCount = 0L

    private var agcPerMeasurement = false
    private var agcList = false
    private var agcMin: Double? = null
    private var agcMax: Double? = null
    private val agcDistinct = HashSet<Long>()

    private var dualFrequency = false
    private val carrierMhz = TreeSet<Double>()

    private var adrValidCount = 0L
    private var adrResetCount = 0L
    private var lastDiscontinuity: Int? = null
    private var discontinuityIncrements = 0

    private val constellations = TreeSet<Int>()
    private val lastCn0 = HashMap<Long, Double>()
    private var cn0MinStep: Double? = null

    private var fullTrackingRequested = false
    private var loggingMode: String? = null
    private var accelSensor: String? = null
    private var gyroSensor: String? = null

    @Synchronized
    fun setSessionInfo(mode: LoggingMode, fullTracking: Boolean, accel: String?, gyro: String?) {
        loggingMode = mode.name
        fullTrackingRequested = fullTracking
        accelSensor = accel
        gyroSensor = gyro
    }

    @Synchronized
    fun onMeasurementStatus(status: Int) {
        measurementStatus = status
    }

    @Suppress("DEPRECATION")
    @Synchronized
    fun onMeasurementsEvent(event: GnssMeasurementsEvent) {
        eventCount++
        val now = SystemClock.elapsedRealtimeNanos()
        if (lastEventElapsedNanos >= 0) {
            val dt = (now - lastEventElapsedNanos) / 1e9
            // Longer gaps are duty-cycle off periods or signal loss, not the measurement rate.
            if (dt > 0.0 && dt < 5.0) {
                intervalSumS += dt
                intervalCount++
            }
        }
        lastEventElapsedNanos = now

        val disc = event.clock.hardwareClockDiscontinuityCount
        val prev = lastDiscontinuity
        if (prev != null && disc != prev) discontinuityIncrements++
        lastDiscontinuity = disc

        for (m in event.measurements) {
            measurementCount++
            constellations.add(m.constellationType)

            val adr = m.accumulatedDeltaRangeState
            if ((adr and GnssMeasurement.ADR_STATE_VALID) != 0) adrValidCount++
            if ((adr and GnssMeasurement.ADR_STATE_RESET) != 0) adrResetCount++

            var freqHz = 0.0
            if (m.hasCarrierFrequencyHz()) {
                freqHz = m.carrierFrequencyHz.toDouble()
                if (GnssBands.isL5(freqHz)) dualFrequency = true
                if (carrierMhz.size < 32) carrierMhz.add((freqHz / 1e4).roundToLong() / 100.0)
            }

            if (m.hasAutomaticGainControlLevelDb()) {
                agcPerMeasurement = true
                addAgc(m.automaticGainControlLevelDb)
            }

            // Steps are taken per signal so that the spread between satellites is not mistaken for resolution.
            val key = m.constellationType.toLong() * 1_000_000_000L +
                m.svid.toLong() * 1_000_000L + (freqHz / 1e5).roundToLong()
            val cn0 = m.cn0DbHz
            val last = lastCn0.put(key, cn0)
            if (last != null) {
                val step = abs(cn0 - last)
                if (step > 1e-6) {
                    val cur = cn0MinStep
                    if (cur == null || step < cur) cn0MinStep = step
                }
            }
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            for (agc in event.gnssAutomaticGainControls) {
                agcList = true
                addAgc(agc.levelDb.toDouble())
            }
        }
    }

    private fun addAgc(v: Double) {
        if (v.isNaN() || v.isInfinite()) return
        val lo = agcMin
        val hi = agcMax
        if (lo == null || v < lo) agcMin = v
        if (hi == null || v > hi) agcMax = v
        if (agcDistinct.size < 10_000) agcDistinct.add((v * 1000.0).roundToLong())
    }

    @Synchronized
    fun report(): CapabilityReport {
        var hasMeasurements: Boolean? = null
        var hasNavMessages: Boolean? = null
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val caps = locationManager.gnssCapabilities
            hasMeasurements = caps.hasMeasurements()
            hasNavMessages = caps.hasNavigationMessages()
        }
        var hwName: String? = null
        var hwYear: Int? = null
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            hwName = locationManager.gnssHardwareModelName
            hwYear = locationManager.gnssYearOfHardware
        }
        return CapabilityReport(
            manufacturer = Build.MANUFACTURER ?: "",
            model = Build.MODEL ?: "",
            sdkInt = Build.VERSION.SDK_INT,
            gnssHardwareModelName = hwName,
            gnssYearOfHardware = hwYear,
            capabilityHasMeasurements = hasMeasurements,
            capabilityHasNavigationMessages = hasNavMessages,
            measurementCallbackStatus = measurementStatus,
            measurementEventCount = eventCount,
            measurementCount = measurementCount,
            measurementRateHz = if (intervalCount > 0 && intervalSumS > 0.0) intervalCount / intervalSumS else null,
            agcPerMeasurementSeen = agcPerMeasurement,
            agcListSeen = agcList,
            agcMinDb = agcMin,
            agcMaxDb = agcMax,
            agcDistinctCount = agcDistinct.size,
            dualFrequency = dualFrequency,
            carrierFrequenciesMhz = carrierMhz.toList(),
            adrValidShare = if (measurementCount > 0) adrValidCount.toDouble() / measurementCount else null,
            clockDiscontinuityIncrements = discontinuityIncrements,
            adrResetCount = adrResetCount,
            fullTrackingRequested = fullTrackingRequested,
            loggingMode = loggingMode,
            constellations = constellations.toList(),
            cn0MinStepDbHz = cn0MinStep,
            accelSensor = accelSensor,
            gyroSensor = gyroSensor,
            sessionStartUtcMillis = sessionStartUtcMillis,
            reportUtcMillis = System.currentTimeMillis(),
        )
    }
}
