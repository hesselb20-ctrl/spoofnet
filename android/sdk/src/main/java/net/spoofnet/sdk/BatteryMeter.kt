package net.spoofnet.sdk

import android.content.Context
import android.os.BatteryManager
import android.os.PowerManager

data class BatterySample(
    val utcMillis: Long,
    /** Microampere-hours; null where the phone does not report a charge counter. */
    val chargeCounterUah: Int?,
    val capacityPercent: Int?,
    val charging: Boolean,
    val screenOn: Boolean,
)

/**
 * Battery cost of one session. [valid] is false if the phone was charging at
 * any sample, because then the drain cannot be read off the counter.
 */
data class BatterySummary(
    val hours: Double,
    val mahUsed: Double?,
    val percentUsed: Double?,
    /** Extrapolated to 24 h; null for sessions under 15 minutes, which are too short to extrapolate. */
    val percentPerDay: Double?,
    val chargedDuringSession: Boolean,
    val valid: Boolean,
    val screenOnShare: Double,
    val sampleCount: Int,
) {
    companion object {
        private const val MIN_HOURS_FOR_RATE = 0.25

        fun from(samples: List<BatterySample>): BatterySummary? {
            if (samples.size < 2) return null
            val first = samples.first()
            val last = samples.last()
            val hours = (last.utcMillis - first.utcMillis) / 3_600_000.0
            val charged = samples.any { it.charging }

            val c0 = first.chargeCounterUah
            val c1 = last.chargeCounterUah
            val mah = if (c0 != null && c1 != null) (c0 - c1) / 1000.0 else null

            val p0 = first.capacityPercent
            val p1 = last.capacityPercent
            // The charge counter has far finer resolution than the 1 % capacity steps, so it wins when present.
            val pct: Double? = when {
                mah != null && p0 != null && p0 > 0 && c0 != null -> {
                    val fullMah = c0 / 1000.0 / (p0 / 100.0)
                    if (fullMah > 0.0) mah / fullMah * 100.0 else null
                }
                p0 != null && p1 != null -> (p0 - p1).toDouble()
                else -> null
            }
            val perDay = if (pct != null && hours >= MIN_HOURS_FOR_RATE) pct / hours * 24.0 else null
            val screenShare = samples.count { it.screenOn }.toDouble() / samples.size

            return BatterySummary(
                hours = hours,
                mahUsed = mah,
                percentUsed = pct,
                percentPerDay = perDay,
                chargedDuringSession = charged,
                valid = !charged && pct != null,
                screenOnShare = screenShare,
                sampleCount = samples.size,
            )
        }
    }
}

/** Samples the battery on the logger thread and writes SnBat lines. */
class BatteryMeter(context: Context, private val writer: LogWriter?) {

    private val batteryManager =
        context.applicationContext.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
    private val powerManager =
        context.applicationContext.getSystemService(Context.POWER_SERVICE) as PowerManager
    private val samples = ArrayList<BatterySample>()

    @Synchronized
    fun sample() {
        val utc = System.currentTimeMillis()
        // Unsupported properties come back as Integer.MIN_VALUE or 0 depending on the device.
        val charge = batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER)
            .takeIf { it > 0 }
        val capacity = batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
            .takeIf { it in 0..100 }
        val charging = batteryManager.isCharging
        val screenOn = powerManager.isInteractive
        samples.add(BatterySample(utc, charge, capacity, charging, screenOn))
        writer?.writeLine(LogLines.snBat(utc, charge, capacity, charging, screenOn))
    }

    @Synchronized
    fun summary(): BatterySummary? = BatterySummary.from(samples)
}
