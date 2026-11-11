package net.spoofnet.sdk

import kotlin.math.abs

/**
 * One GNSS measurement epoch, reduced to what a status screen shows. Values
 * are null when the epoch had no signal in that band or the phone does not
 * report the quantity.
 */
data class LiveStats(
    val utcMillis: Long,
    /** Distinct satellites (constellation and svid), so an L1 and L5 signal from one satellite count once. */
    val satelliteCount: Int,
    val medianCn0L1DbHz: Double?,
    val medianCn0L5DbHz: Double?,
    val agcL1Db: Double?,
    val agcL5Db: Double?,
    val hardwareClockDiscontinuityCount: Int,
)

/** Called on the SDK's background thread; post to the main thread before touching views. */
fun interface LiveStatsListener {
    fun onLiveStats(stats: LiveStats)
}

/**
 * Detector output state. Only UNKNOWN and LOGGING are reported in this
 * milestone; the detectors that would justify TRUSTED, DEGRADED or UNTRUSTED
 * arrive in a later milestone.
 */
enum class TrustState {
    UNKNOWN,
    LOGGING,
    TRUSTED,
    DEGRADED,
    UNTRUSTED,
}

enum class Band { L1, L5, OTHER }

/** Band grouping of DESIGN.md section 5.1. */
object GnssBands {
    const val L5_HZ = 1176.45e6
    const val L5_TOLERANCE_HZ = 20e6
    private const val L1_LOW_HZ = 1550e6
    private const val L1_HIGH_HZ = 1610e6

    /**
     * A missing carrier frequency is treated as L1: phones that do not report it
     * are single-frequency L1 receivers.
     */
    fun bandOf(carrierFrequencyHz: Double?): Band {
        if (carrierFrequencyHz == null || carrierFrequencyHz <= 0.0) return Band.L1
        if (abs(carrierFrequencyHz - L5_HZ) <= L5_TOLERANCE_HZ) return Band.L5
        if (carrierFrequencyHz in L1_LOW_HZ..L1_HIGH_HZ) return Band.L1
        return Band.OTHER
    }

    fun isL5(carrierFrequencyHz: Double): Boolean = abs(carrierFrequencyHz - L5_HZ) <= L5_TOLERANCE_HZ

    fun median(values: List<Double>): Double? {
        if (values.isEmpty()) return null
        val s = values.sorted()
        val mid = s.size / 2
        return if (s.size % 2 == 1) s[mid] else (s[mid - 1] + s[mid]) / 2.0
    }
}
