package net.spoofnet.sdk

import kotlin.math.atan2
import kotlin.math.sqrt

/**
 * One window of motion summary, the `SnImu` record of DESIGN.md section 5.1.
 *
 * [yawRateRadPerSec] is positive for counterclockwise rotation seen from above
 * (right-hand rule about the "up" direction that the accelerometer reports at
 * rest). It is null when no gyroscope sample fell into the window.
 */
data class ImuSummary(
    val endNanos: Long,
    val vibRmsMps2: Double,
    val accHMps2: Double,
    val yawRateRadPerSec: Double?,
    val tiltDeg: Double,
    val sampleCount: Int,
)

/**
 * Turns accelerometer and gyroscope samples (both in the device frame, with
 * timestamps on one clock) into 1 s summaries.
 *
 * Accelerometer samples drive the window clock: a summary is returned by the
 * [addAccel] call whose sample falls past the end of the current window.
 * [sampleCount] counts accelerometer samples.
 */
class ImuSummarizer(
    private val windowNanos: Long = 1_000_000_000L,
    /** About 2 s so that walking or driving motion does not leak into the gravity estimate. */
    private val gravityTauS: Double = 2.0,
    /** Baseline for the magnitude high-pass; vibration lives well above 2 Hz. */
    private val vibTauS: Double = 0.5,
    /** A longer gap means the sensors were off, so the filters no longer describe the phone. */
    private val maxGapNanos: Long = 500_000_000L,
) {
    private var hasGravity = false
    private var gx = 0.0
    private var gy = 0.0
    private var gz = 0.0
    private var magLp = 0.0
    private var lastAccelNanos = 0L

    private var hasWindow = false
    private var windowStart = 0L
    private var startGx = 0.0
    private var startGy = 0.0
    private var startGz = 0.0
    private var vibSumSq = 0.0
    private var accHSum = 0.0
    private var accelCount = 0
    private var yawSum = 0.0
    private var gyroCount = 0

    /** Drops all state without emitting, for example when sensors are re-registered. */
    fun reset() {
        hasGravity = false
        hasWindow = false
        clearWindow()
    }

    /** Emits the partial current window, if it holds samples, and resets. */
    fun flush(): ImuSummary? {
        val out = if (hasWindow && accelCount > 0) closeWindow() else null
        reset()
        return out
    }

    fun addAccel(tNanos: Long, x: Double, y: Double, z: Double): ImuSummary? {
        var out: ImuSummary? = null

        if (hasGravity && tNanos - lastAccelNanos > maxGapNanos) {
            out = flush()
        } else if (hasWindow && tNanos >= windowStart + windowNanos) {
            out = closeWindow()
            // After a short stall keep the windows aligned; otherwise restart at this sample.
            windowStart = if (tNanos < windowStart + 2 * windowNanos) windowStart + windowNanos else tNanos
            openWindow()
        }

        val mag = sqrt(x * x + y * y + z * z)
        if (!hasGravity) {
            gx = x; gy = y; gz = z
            magLp = mag
            hasGravity = true
        } else {
            val dt = (tNanos - lastAccelNanos) / 1e9
            if (dt > 0.0) {
                val a = dt / (gravityTauS + dt)
                gx += a * (x - gx)
                gy += a * (y - gy)
                gz += a * (z - gz)
                val bv = dt / (vibTauS + dt)
                magLp += bv * (mag - magLp)
            }
        }
        lastAccelNanos = tNanos

        if (!hasWindow) {
            windowStart = tNanos
            hasWindow = true
            openWindow()
        }

        val hp = mag - magLp
        vibSumSq += hp * hp

        val gn = sqrt(gx * gx + gy * gy + gz * gz)
        if (gn > 1e-6) {
            val ux = gx / gn
            val uy = gy / gn
            val uz = gz / gn
            val lx = x - gx
            val ly = y - gy
            val lz = z - gz
            val along = lx * ux + ly * uy + lz * uz
            val hx = lx - along * ux
            val hy = ly - along * uy
            val hz = lz - along * uz
            accHSum += sqrt(hx * hx + hy * hy + hz * hz)
        }
        accelCount++
        return out
    }

    fun addGyro(tNanos: Long, x: Double, y: Double, z: Double) {
        if (!hasGravity || !hasWindow) return
        val gn = sqrt(gx * gx + gy * gy + gz * gz)
        if (gn < 1e-6) return
        yawSum += (x * gx + y * gy + z * gz) / gn
        gyroCount++
    }

    private fun openWindow() {
        clearWindow()
        startGx = gx
        startGy = gy
        startGz = gz
    }

    private fun clearWindow() {
        vibSumSq = 0.0
        accHSum = 0.0
        accelCount = 0
        yawSum = 0.0
        gyroCount = 0
    }

    private fun closeWindow(): ImuSummary {
        val n = accelCount.coerceAtLeast(1)
        return ImuSummary(
            endNanos = lastAccelNanos,
            vibRmsMps2 = sqrt(vibSumSq / n),
            accHMps2 = accHSum / n,
            yawRateRadPerSec = if (gyroCount > 0) yawSum / gyroCount else null,
            tiltDeg = angleDeg(startGx, startGy, startGz, gx, gy, gz),
            sampleCount = accelCount,
        )
    }

    companion object {
        /** atan2 of cross and dot stays accurate for the tiny angles of a still phone, unlike acos. */
        fun angleDeg(ax: Double, ay: Double, az: Double, bx: Double, by: Double, bz: Double): Double {
            val cx = ay * bz - az * by
            val cy = az * bx - ax * bz
            val cz = ax * by - ay * bx
            val cross = sqrt(cx * cx + cy * cy + cz * cz)
            val dot = ax * bx + ay * by + az * bz
            return Math.toDegrees(atan2(cross, dot))
        }
    }
}
