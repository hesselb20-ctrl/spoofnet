package net.spoofnet.sdk

/**
 * How much of the time the GNSS receiver and motion sensors are on.
 * Measurements are 1 Hz in every mode; the modes only differ in the on/off
 * pattern, which is written to the log as `# SnDuty` lines.
 */
enum class LoggingMode(val onMillis: Long, val offMillis: Long) {
    /** Always on. */
    CONTINUOUS(0L, 0L),

    /** 20 s on, 100 s off. */
    BALANCED(20_000L, 100_000L),

    /** 15 s on every 5 minutes. */
    SAVER(15_000L, 285_000L),
    ;

    val isDutyCycled: Boolean get() = offMillis > 0L
}

/** Settings for one logging session. */
data class SpoofNetConfig(
    val mode: LoggingMode = LoggingMode.CONTINUOUS,
    /** The 1 Hz SnImu summary is what the detectors use; raw 50 Hz lines are only for analysis. */
    val logRawImu: Boolean = false,
    /** Asks the chipset not to duty-cycle tracking internally (API 31+); costs battery. */
    val fullTracking: Boolean = true,
)
