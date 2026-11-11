package net.spoofnet.sdk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Random
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin

class ImuSummarizerTest {

    private val periodNanos = 20_000_000L // 50 Hz

    private fun run(
        seconds: Double,
        accel: (Double) -> DoubleArray,
        gyro: (Double) -> DoubleArray,
    ): List<ImuSummary> {
        val s = ImuSummarizer()
        val out = ArrayList<ImuSummary>()
        val n = (seconds * 50).toInt()
        for (k in 0 until n) {
            val t = k * periodNanos
            val ts = k * 0.02
            val a = accel(ts)
            s.addAccel(t, a[0], a[1], a[2])?.let { out.add(it) }
            val g = gyro(ts)
            s.addGyro(t, g[0], g[1], g[2])
        }
        return out
    }

    @Test
    fun stationaryPhoneGivesNearZeroMotion() {
        val rnd = Random(42)
        val out = run(
            10.0,
            { doubleArrayOf(0.05 + rnd.nextGaussian() * 0.01, -0.1 + rnd.nextGaussian() * 0.01, 9.8 + rnd.nextGaussian() * 0.01) },
            { doubleArrayOf(rnd.nextGaussian() * 0.001, rnd.nextGaussian() * 0.001, rnd.nextGaussian() * 0.001) },
        )
        assertEquals(9, out.size)
        for (s in out) {
            assertEquals(50, s.sampleCount)
            assertTrue("vib_rms ${s.vibRmsMps2}", s.vibRmsMps2 < 0.05)
            assertTrue("acc_h ${s.accHMps2}", s.accHMps2 < 0.05)
            val yaw = s.yawRateRadPerSec
            assertNotNull(yaw)
            assertTrue("yaw_rate $yaw", abs(yaw!!) < 0.005)
            assertTrue("tilt ${s.tiltDeg}", s.tiltDeg < 0.1)
        }
    }

    @Test
    fun rotationAboutGravityGivesYawRateEvenWhenPhoneIsTilted() {
        val th = Math.toRadians(30.0)
        val g = 9.81
        val rate = 0.5
        val out = run(
            5.0,
            { doubleArrayOf(0.0, g * sin(th), g * cos(th)) },
            { doubleArrayOf(0.0, rate * sin(th), rate * cos(th)) },
        )
        assertEquals(4, out.size)
        for (s in out) {
            assertEquals(rate, s.yawRateRadPerSec!!, 1e-6)
            assertEquals(0.0, s.tiltDeg, 1e-6)
        }
    }

    @Test
    fun yawRateIsSigned() {
        val out = run(
            3.0,
            { doubleArrayOf(0.0, 0.0, 9.81) },
            { doubleArrayOf(0.0, 0.0, -0.3) },
        )
        for (s in out) assertEquals(-0.3, s.yawRateRadPerSec!!, 1e-6)
    }

    @Test
    fun steadyTiltGivesExpectedTiltPerWindowAndNoYaw() {
        val w = Math.toRadians(3.0) // 3 degrees per second about the x axis
        val g = 9.81
        val out = run(
            20.0,
            { t -> doubleArrayOf(0.0, g * sin(w * t), g * cos(w * t)) },
            { doubleArrayOf(w, 0.0, 0.0) },
        )
        assertEquals(19, out.size)
        // The 2 s gravity filter needs a few time constants before it follows the tilt at full rate.
        for (s in out.subList(12, out.size)) {
            assertEquals(3.0, s.tiltDeg, 0.05)
        }
        // Rotation about a horizontal axis is not yaw.
        for (s in out) assertEquals(0.0, s.yawRateRadPerSec!!, 1e-3)
    }

    @Test
    fun gapEmitsPartialWindowAndRestarts() {
        val s = ImuSummarizer()
        for (k in 0 until 10) s.addAccel(k * periodNanos, 0.0, 0.0, 9.81)
        val partial = s.addAccel(5_000_000_000L, 0.0, 0.0, 9.81)
        assertNotNull(partial)
        assertEquals(10, partial!!.sampleCount)
        assertEquals(null, partial.yawRateRadPerSec)
        // The sample after the gap opened a fresh window on its own.
        assertEquals(1, s.flush()!!.sampleCount)
        assertEquals(null, s.flush())
    }
}
