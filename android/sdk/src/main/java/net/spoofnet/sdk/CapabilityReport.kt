package net.spoofnet.sdk

import org.json.JSONArray
import org.json.JSONObject

/** Device quality tier and the weight the server gives it, DESIGN.md section 4. */
enum class Tier(val weight: Double) {
    A(1.0),
    B(0.7),
    C(0.4),
    D(0.15),
}

/**
 * What this phone's GNSS hardware showed it can do during one logging session.
 * Every field is evidence that was observed, not what the device claims, except
 * the `capability*` fields which come from GnssCapabilities and are kept so the
 * two can be compared.
 */
data class CapabilityReport(
    val manufacturer: String = "",
    val model: String = "",
    val sdkInt: Int = 0,
    val gnssHardwareModelName: String? = null,
    val gnssYearOfHardware: Int? = null,
    /** GnssCapabilities.hasMeasurements(); null below API 31. */
    val capabilityHasMeasurements: Boolean? = null,
    /** GnssCapabilities.hasNavigationMessages(); null below API 31. */
    val capabilityHasNavigationMessages: Boolean? = null,
    /** Last GnssMeasurementsEvent.Callback status, null if none was reported. */
    val measurementCallbackStatus: Int? = null,
    val measurementEventCount: Long = 0L,
    val measurementCount: Long = 0L,
    val measurementRateHz: Double? = null,
    val agcPerMeasurementSeen: Boolean = false,
    val agcListSeen: Boolean = false,
    val agcMinDb: Double? = null,
    val agcMaxDb: Double? = null,
    val agcDistinctCount: Int = 0,
    val dualFrequency: Boolean = false,
    val carrierFrequenciesMhz: List<Double> = emptyList(),
    val adrValidShare: Double? = null,
    val clockDiscontinuityIncrements: Int = 0,
    val adrResetCount: Long = 0L,
    val fullTrackingRequested: Boolean = false,
    /** Name of the LoggingMode; a duty-cycled mode causes discontinuities of its own. */
    val loggingMode: String? = null,
    val constellations: List<Int> = emptyList(),
    val cn0MinStepDbHz: Double? = null,
    val accelSensor: String? = null,
    val gyroSensor: String? = null,
    val sessionStartUtcMillis: Long = 0L,
    val reportUtcMillis: Long = 0L,
) {
    /** Confirmed by data, not by the capability flag, because some phones claim support and deliver nothing. */
    val rawMeasurements: Boolean get() = measurementCount > 0

    val agcAvailable: Boolean get() = agcPerMeasurementSeen || agcListSeen

    /** A constant AGC value carries no information about interference, so it does not count as working. */
    val agcChanges: Boolean
        get() {
            val lo = agcMinDb ?: return false
            val hi = agcMaxDb ?: return false
            return agcDistinctCount >= 2 && hi > lo
        }

    val workingAgc: Boolean get() = agcAvailable && agcChanges

    fun tier(): Tier = when {
        !rawMeasurements -> Tier.D
        workingAgc && dualFrequency -> Tier.A
        workingAgc || dualFrequency -> Tier.B
        else -> Tier.C
    }

    fun toJson(): JSONObject {
        val o = JSONObject()
        o.put("schema", 1)
        o.put("tier", tier().name)
        o.put("tier_weight", tier().weight)
        o.put("manufacturer", manufacturer)
        o.put("model", model)
        o.put("sdk_int", sdkInt)
        o.put("gnss_hardware_model_name", gnssHardwareModelName ?: JSONObject.NULL)
        o.put("gnss_year_of_hardware", gnssYearOfHardware ?: JSONObject.NULL)
        o.put("capability_has_measurements", capabilityHasMeasurements ?: JSONObject.NULL)
        o.put("capability_has_navigation_messages", capabilityHasNavigationMessages ?: JSONObject.NULL)
        o.put("measurement_callback_status", measurementCallbackStatus ?: JSONObject.NULL)
        o.put("raw_measurements", rawMeasurements)
        o.put("measurement_event_count", measurementEventCount)
        o.put("measurement_count", measurementCount)
        o.put("measurement_rate_hz", finiteOrNull(measurementRateHz))
        o.put("agc_per_measurement", agcPerMeasurementSeen)
        o.put("agc_list", agcListSeen)
        o.put("agc_min_db", finiteOrNull(agcMinDb))
        o.put("agc_max_db", finiteOrNull(agcMaxDb))
        o.put("agc_distinct_count", agcDistinctCount)
        o.put("agc_changes", agcChanges)
        o.put("working_agc", workingAgc)
        o.put("dual_frequency", dualFrequency)
        o.put("carrier_frequencies_mhz", JSONArray(carrierFrequenciesMhz))
        o.put("adr_valid_share", finiteOrNull(adrValidShare))
        o.put("clock_discontinuity_increments", clockDiscontinuityIncrements)
        o.put("adr_reset_count", adrResetCount)
        o.put("full_tracking_requested", fullTrackingRequested)
        o.put("logging_mode", loggingMode ?: JSONObject.NULL)
        o.put("constellations", JSONArray(constellations.map { constellationName(it) }))
        o.put("cn0_min_step_db_hz", finiteOrNull(cn0MinStepDbHz))
        o.put("accel_sensor", accelSensor ?: JSONObject.NULL)
        o.put("gyro_sensor", gyroSensor ?: JSONObject.NULL)
        o.put("session_start_utc_millis", sessionStartUtcMillis)
        o.put("report_utc_millis", reportUtcMillis)
        return o
    }

    companion object {
        /** Names match the GnssStatus.CONSTELLATION_* constants so the mapping cannot drift. */
        fun constellationName(type: Int): String = when (type) {
            1 -> "GPS"
            2 -> "SBAS"
            3 -> "GLONASS"
            4 -> "QZSS"
            5 -> "BEIDOU"
            6 -> "GALILEO"
            7 -> "IRNSS"
            else -> "UNKNOWN_$type"
        }

        private fun finiteOrNull(v: Double?): Any =
            if (v == null || v.isNaN() || v.isInfinite()) JSONObject.NULL else v
    }
}
