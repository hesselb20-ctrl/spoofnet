package net.spoofnet.sdk

import java.math.BigDecimal
import java.util.Locale

/**
 * Values of one GnssClock. A null field is one the device did not provide;
 * it is written as an empty column, never as zero, because zero is a valid
 * value for most of these fields.
 */
data class ClockValues(
    val timeNanos: Long = 0L,
    val leapSecond: Int? = null,
    val timeUncertaintyNanos: Double? = null,
    val fullBiasNanos: Long? = null,
    val biasNanos: Double? = null,
    val biasUncertaintyNanos: Double? = null,
    val driftNanosPerSecond: Double? = null,
    val driftUncertaintyNanosPerSecond: Double? = null,
    val hardwareClockDiscontinuityCount: Int = 0,
    val elapsedRealtimeNanos: Long? = null,
)

/** Values of one GnssMeasurement, with the same null convention as [ClockValues]. */
data class MeasurementValues(
    val svid: Int = 0,
    val timeOffsetNanos: Double? = null,
    val state: Int? = null,
    val receivedSvTimeNanos: Long? = null,
    val receivedSvTimeUncertaintyNanos: Long? = null,
    val cn0DbHz: Double? = null,
    val pseudorangeRateMetersPerSecond: Double? = null,
    val pseudorangeRateUncertaintyMetersPerSecond: Double? = null,
    val accumulatedDeltaRangeState: Int? = null,
    val accumulatedDeltaRangeMeters: Double? = null,
    val accumulatedDeltaRangeUncertaintyMeters: Double? = null,
    val carrierFrequencyHz: Float? = null,
    val carrierCycles: Long? = null,
    val carrierPhase: Double? = null,
    val carrierPhaseUncertainty: Double? = null,
    val multipathIndicator: Int? = null,
    val snrInDb: Double? = null,
    val constellationType: Int = 0,
    val agcDb: Double? = null,
    val basebandCn0DbHz: Double? = null,
    val fullInterSignalBiasNanos: Double? = null,
    val fullInterSignalBiasUncertaintyNanos: Double? = null,
    val satelliteInterSignalBiasNanos: Double? = null,
    val satelliteInterSignalBiasUncertaintyNanos: Double? = null,
    val codeType: String? = null,
)

/**
 * Formats log lines in the Google GnssLogger text format plus the SpoofNet
 * extension records. Kept free of Android imports so the exact output can be
 * unit tested on the JVM.
 *
 * Raw values are written as plain decimals with the shortest digits that
 * round-trip (no exponent, no locale), so a replay reads back exactly what the
 * chipset reported. Derived values use fixed decimals with Locale.US.
 */
object LogLines {

    const val HEADER_RAW = "# Raw,utcTimeMillis,TimeNanos,LeapSecond,TimeUncertaintyNanos,FullBiasNanos,BiasNanos,BiasUncertaintyNanos,DriftNanosPerSecond,DriftUncertaintyNanosPerSecond,HardwareClockDiscontinuityCount,Svid,TimeOffsetNanos,State,ReceivedSvTimeNanos,ReceivedSvTimeUncertaintyNanos,Cn0DbHz,PseudorangeRateMetersPerSecond,PseudorangeRateUncertaintyMetersPerSecond,AccumulatedDeltaRangeState,AccumulatedDeltaRangeMeters,AccumulatedDeltaRangeUncertaintyMeters,CarrierFrequencyHz,CarrierCycles,CarrierPhase,CarrierPhaseUncertainty,MultipathIndicator,SnrInDb,ConstellationType,AgcDb,BasebandCn0DbHz,FullInterSignalBiasNanos,FullInterSignalBiasUncertaintyNanos,SatelliteInterSignalBiasNanos,SatelliteInterSignalBiasUncertaintyNanos,CodeType,ChipsetElapsedRealtimeNanos"
    const val HEADER_FIX = "# Fix,Provider,LatitudeDegrees,LongitudeDegrees,AltitudeMeters,SpeedMps,AccuracyMeters,BearingDegrees,UnixTimeMillis,SpeedAccuracyMps,BearingAccuracyDegrees,elapsedRealtimeNanos,VerticalAccuracyMeters"
    const val HEADER_STATUS = "# Status,UnixTimeMillis,SignalCount,SignalIndex,ConstellationType,Svid,CarrierFrequencyHz,Cn0DbHz,AzimuthDegrees,ElevationDegrees,UsedInFix,HasAlmanacData,HasEphemerisData,BasebandCn0DbHz"
    const val HEADER_UNCAL_ACCEL = "# UncalAccel,utcTimeMillis,elapsedRealtimeNanos,UncalAccelXMps2,UncalAccelYMps2,UncalAccelZMps2,BiasXMps2,BiasYMps2,BiasZMps2"
    const val HEADER_UNCAL_GYRO = "# UncalGyro,utcTimeMillis,elapsedRealtimeNanos,UncalGyroXRadPerSec,UncalGyroYRadPerSec,UncalGyroZRadPerSec,DriftXRadPerSec,DriftYRadPerSec,DriftZRadPerSec"
    const val HEADER_AGC = "# Agc,utcTimeMillis,TimeNanos,LeapSecond,TimeUncertaintyNanos,FullBiasNanos,BiasNanos,BiasUncertaintyNanos,DriftNanosPerSecond,DriftUncertaintyNanosPerSecond,HardwareClockDiscontinuityCount,AgcDb,CarrierFrequencyHz,ConstellationType"
    const val HEADER_SN_IMU = "# SnImu,utcTimeMillis,elapsedRealtimeNanos,VibRmsMps2,AccHMps2,YawRateRadPerSec,TiltDeg,SampleCount"
    const val HEADER_SN_BAT = "# SnBat,utcTimeMillis,ChargeCounterUah,CapacityPercent,IsCharging,ScreenOn"
    const val HEADER_SN_CAP = "# SnCap,Json"

    val HEADER_LINES: List<String> = listOf(
        HEADER_RAW, HEADER_FIX, HEADER_STATUS, HEADER_UNCAL_ACCEL, HEADER_UNCAL_GYRO,
        HEADER_AGC, HEADER_SN_IMU, HEADER_SN_BAT, HEADER_SN_CAP,
    )

    fun raw(utcMillis: Long, c: ClockValues, m: MeasurementValues): String = join(
        "Raw",
        l(utcMillis), l(c.timeNanos), i(c.leapSecond), d(c.timeUncertaintyNanos),
        l(c.fullBiasNanos), d(c.biasNanos), d(c.biasUncertaintyNanos),
        d(c.driftNanosPerSecond), d(c.driftUncertaintyNanosPerSecond),
        i(c.hardwareClockDiscontinuityCount),
        i(m.svid), d(m.timeOffsetNanos), i(m.state), l(m.receivedSvTimeNanos),
        l(m.receivedSvTimeUncertaintyNanos), d(m.cn0DbHz),
        d(m.pseudorangeRateMetersPerSecond), d(m.pseudorangeRateUncertaintyMetersPerSecond),
        i(m.accumulatedDeltaRangeState), d(m.accumulatedDeltaRangeMeters),
        d(m.accumulatedDeltaRangeUncertaintyMeters),
        f(m.carrierFrequencyHz), l(m.carrierCycles), d(m.carrierPhase), d(m.carrierPhaseUncertainty),
        i(m.multipathIndicator), d(m.snrInDb), i(m.constellationType), d(m.agcDb),
        d(m.basebandCn0DbHz), d(m.fullInterSignalBiasNanos), d(m.fullInterSignalBiasUncertaintyNanos),
        d(m.satelliteInterSignalBiasNanos), d(m.satelliteInterSignalBiasUncertaintyNanos),
        text(m.codeType), l(c.elapsedRealtimeNanos),
    )

    fun agc(
        utcMillis: Long,
        c: ClockValues,
        agcDb: Double?,
        carrierFrequencyHz: Long?,
        constellationType: Int,
    ): String = join(
        "Agc",
        l(utcMillis), l(c.timeNanos), i(c.leapSecond), d(c.timeUncertaintyNanos),
        l(c.fullBiasNanos), d(c.biasNanos), d(c.biasUncertaintyNanos),
        d(c.driftNanosPerSecond), d(c.driftUncertaintyNanosPerSecond),
        i(c.hardwareClockDiscontinuityCount),
        d(agcDb), l(carrierFrequencyHz), i(constellationType),
    )

    fun fix(
        provider: String,
        latitudeDegrees: Double,
        longitudeDegrees: Double,
        altitudeMeters: Double?,
        speedMps: Float?,
        accuracyMeters: Float?,
        bearingDegrees: Float?,
        unixTimeMillis: Long,
        speedAccuracyMps: Float?,
        bearingAccuracyDegrees: Float?,
        elapsedRealtimeNanos: Long?,
        verticalAccuracyMeters: Float?,
    ): String = join(
        "Fix",
        text(provider), d(latitudeDegrees), d(longitudeDegrees), d(altitudeMeters),
        f(speedMps), f(accuracyMeters), f(bearingDegrees), l(unixTimeMillis),
        f(speedAccuracyMps), f(bearingAccuracyDegrees), l(elapsedRealtimeNanos),
        f(verticalAccuracyMeters),
    )

    fun status(
        unixTimeMillis: Long,
        signalCount: Int,
        signalIndex: Int,
        constellationType: Int,
        svid: Int,
        carrierFrequencyHz: Float?,
        cn0DbHz: Float?,
        azimuthDegrees: Float?,
        elevationDegrees: Float?,
        usedInFix: Boolean,
        hasAlmanacData: Boolean,
        hasEphemerisData: Boolean,
        basebandCn0DbHz: Float?,
    ): String = join(
        "Status",
        l(unixTimeMillis), i(signalCount), i(signalIndex), i(constellationType), i(svid),
        f(carrierFrequencyHz), f(cn0DbHz), f(azimuthDegrees), f(elevationDegrees),
        b(usedInFix), b(hasAlmanacData), b(hasEphemerisData), f(basebandCn0DbHz),
    )

    /** Bias fields are null when the calibrated sensor had to stand in for the uncalibrated one. */
    fun uncalAccel(
        utcMillis: Long, elapsedRealtimeNanos: Long,
        x: Float, y: Float, z: Float,
        biasX: Float?, biasY: Float?, biasZ: Float?,
    ): String = join(
        "UncalAccel", l(utcMillis), l(elapsedRealtimeNanos),
        f(x), f(y), f(z), f(biasX), f(biasY), f(biasZ),
    )

    fun uncalGyro(
        utcMillis: Long, elapsedRealtimeNanos: Long,
        x: Float, y: Float, z: Float,
        driftX: Float?, driftY: Float?, driftZ: Float?,
    ): String = join(
        "UncalGyro", l(utcMillis), l(elapsedRealtimeNanos),
        f(x), f(y), f(z), f(driftX), f(driftY), f(driftZ),
    )

    fun snImu(utcMillis: Long, elapsedRealtimeNanos: Long, s: ImuSummary): String = join(
        "SnImu", l(utcMillis), l(elapsedRealtimeNanos),
        fixed(s.vibRmsMps2, 4), fixed(s.accHMps2, 4), fixed(s.yawRateRadPerSec, 5),
        fixed(s.tiltDeg, 3), i(s.sampleCount),
    )

    fun snBat(
        utcMillis: Long,
        chargeCounterUah: Int?,
        capacityPercent: Int?,
        isCharging: Boolean?,
        screenOn: Boolean?,
    ): String = join(
        "SnBat", l(utcMillis), i(chargeCounterUah), i(capacityPercent), b(isCharging), b(screenOn),
    )

    /** The JSON goes after the first comma as-is; readers split SnCap lines once, not per comma. */
    fun snCap(json: String): String = "SnCap," + json.replace('\n', ' ').replace('\r', ' ')

    /**
     * Written as a comment so GnssLogger readers skip it, while SpoofNet's reader
     * uses it to tell a deliberate duty-cycle gap from a loss of signal.
     */
    fun snDuty(utcMillis: Long, on: Boolean): String =
        "# SnDuty," + l(utcMillis) + "," + (if (on) "on" else "off")

    // Field formatters. Every one maps "not provided" to an empty string.

    fun d(v: Double?): String =
        if (v == null || v.isNaN() || v.isInfinite()) "" else plain(java.lang.Double.toString(v))

    fun f(v: Float?): String =
        if (v == null || v.isNaN() || v.isInfinite()) "" else plain(java.lang.Float.toString(v))

    fun l(v: Long?): String = v?.toString() ?: ""

    fun i(v: Int?): String = v?.toString() ?: ""

    fun b(v: Boolean?): String = when (v) {
        null -> ""
        true -> "1"
        false -> "0"
    }

    fun fixed(v: Double?, decimals: Int): String =
        if (v == null || v.isNaN() || v.isInfinite()) "" else String.format(Locale.US, "%." + decimals + "f", v)

    /** A comma inside a text field would shift every later column. */
    fun text(v: String?): String = v?.replace(',', ';')?.replace('\n', ' ') ?: ""

    private fun plain(shortest: String): String =
        BigDecimal(shortest).stripTrailingZeros().toPlainString()

    private fun join(record: String, vararg fields: String): String {
        val sb = StringBuilder(record.length + fields.size * 12)
        sb.append(record)
        for (field in fields) {
            sb.append(',').append(field)
        }
        return sb.toString()
    }
}
