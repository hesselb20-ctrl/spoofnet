package net.spoofnet.sdk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Locale

class LogLinesTest {

    private fun column(header: String, line: String, name: String): String {
        val idx = header.split(",").indexOf(name)
        assertTrue("column $name missing from header", idx > 0)
        // Kotlin's split keeps trailing empty fields, which is what a reader sees.
        return line.split(",")[idx]
    }

    private fun columnCount(s: String): Int = s.split(",").size

    @Test
    fun headerLinesAreWrittenInOrder() {
        val h = LogLines.HEADER_LINES
        assertEquals(9, h.size)
        assertTrue(h[0].startsWith("# Raw,utcTimeMillis,TimeNanos,LeapSecond,"))
        assertTrue(h[0].endsWith(",CodeType,ChipsetElapsedRealtimeNanos"))
        assertTrue(h[1].startsWith("# Fix,Provider,"))
        assertTrue(h[2].startsWith("# Status,UnixTimeMillis,"))
        assertTrue(h[3].startsWith("# UncalAccel,"))
        assertTrue(h[4].startsWith("# UncalGyro,"))
        assertTrue(h[5].startsWith("# Agc,"))
        assertTrue(h[6].startsWith("# SnImu,"))
        assertTrue(h[7].startsWith("# SnBat,"))
        assertTrue(h[8].startsWith("# SnCap,"))
    }

    @Test
    fun rawLineMatchesHeaderColumnCountWhenEverythingIsMissing() {
        val line = LogLines.raw(1L, ClockValues(), MeasurementValues())
        assertTrue(line.startsWith("Raw,"))
        assertEquals(columnCount(LogLines.HEADER_RAW), columnCount(line))
    }

    @Test
    fun missingFieldsAreEmptyNotZero() {
        val line = LogLines.raw(
            1_700_000_000_000L,
            ClockValues(timeNanos = 5L, leapSecond = null, fullBiasNanos = -1_300_000_000_000_000_000L),
            MeasurementValues(svid = 12, cn0DbHz = 35.25, constellationType = 1, agcDb = null),
        )
        val h = LogLines.HEADER_RAW
        assertEquals("", column(h, line, "LeapSecond"))
        assertEquals("", column(h, line, "AgcDb"))
        assertEquals("", column(h, line, "CodeType"))
        assertEquals("", column(h, line, "ChipsetElapsedRealtimeNanos"))
        assertEquals("-1300000000000000000", column(h, line, "FullBiasNanos"))
        assertEquals("12", column(h, line, "Svid"))
        assertEquals("35.25", column(h, line, "Cn0DbHz"))
        assertTrue(line.contains(",,"))
    }

    @Test
    fun carrierFrequencyIsPlainDecimal() {
        val line = LogLines.raw(1L, ClockValues(), MeasurementValues(carrierFrequencyHz = 1176.45e6f))
        val v = column(LogLines.HEADER_RAW, line, "CarrierFrequencyHz")
        assertTrue("no exponent expected in $v", !v.contains('E'))
        assertEquals(1176.45e6, v.toDouble(), 100.0)
    }

    @Test
    fun numbersIgnoreTheDeviceLocale() {
        val saved = Locale.getDefault()
        try {
            Locale.setDefault(Locale.GERMANY)
            assertEquals("1.5", LogLines.d(1.5))
            assertEquals("-0.000123", LogLines.d(-0.000123))
            assertEquals("1234.57", LogLines.fixed(1234.5678, 2))
            assertEquals("2.25", LogLines.f(2.25f))

            val s = ImuSummary(endNanos = 9L, vibRmsMps2 = 0.5, accHMps2 = 0.25, yawRateRadPerSec = -0.125, tiltDeg = 1.5, sampleCount = 50)
            val line = LogLines.snImu(100L, 9L, s)
            assertEquals("SnImu,100,9,0.5000,0.2500,-0.12500,1.500,50", line)
        } finally {
            Locale.setDefault(saved)
        }
    }

    @Test
    fun formattersMapNonFiniteAndNullToEmpty() {
        assertEquals("", LogLines.d(null))
        assertEquals("", LogLines.d(Double.NaN))
        assertEquals("", LogLines.d(Double.POSITIVE_INFINITY))
        assertEquals("", LogLines.f(Float.NaN))
        assertEquals("", LogLines.l(null))
        assertEquals("", LogLines.i(null))
        assertEquals("", LogLines.b(null))
        assertEquals("", LogLines.fixed(null, 3))
    }

    @Test
    fun plainDecimalsHaveNoExponent() {
        assertEquals("100", LogLines.d(100.0))
        assertEquals("0", LogLines.d(0.0))
        assertEquals("0", LogLines.d(-0.0))
        assertEquals("0.0000001", LogLines.d(1e-7))
        assertEquals("12345678901234", LogLines.d(1.2345678901234E13))
    }

    @Test
    fun imuLineWithoutGyroLeavesYawEmpty() {
        val s = ImuSummary(endNanos = 1L, vibRmsMps2 = 0.0, accHMps2 = 0.0, yawRateRadPerSec = null, tiltDeg = 0.0, sampleCount = 3)
        val line = LogLines.snImu(1L, 1L, s)
        assertEquals(columnCount(LogLines.HEADER_SN_IMU), columnCount(line))
        assertEquals("", column(LogLines.HEADER_SN_IMU, line, "YawRateRadPerSec"))
    }

    @Test
    fun otherRecordsMatchTheirHeaders() {
        val fix = LogLines.fix("gps", 52.1, 4.3, null, 1.5f, 3f, null, 10L, null, null, 99L, null)
        assertEquals(columnCount(LogLines.HEADER_FIX), columnCount(fix))
        assertEquals("", column(LogLines.HEADER_FIX, fix, "AltitudeMeters"))
        assertEquals("gps", column(LogLines.HEADER_FIX, fix, "Provider"))

        val status = LogLines.status(10L, 2, 0, 6, 11, 1575.42e6f, 40.5f, 120f, 45f, true, false, true, null)
        assertEquals(columnCount(LogLines.HEADER_STATUS), columnCount(status))
        assertEquals("1", column(LogLines.HEADER_STATUS, status, "UsedInFix"))
        assertEquals("0", column(LogLines.HEADER_STATUS, status, "HasAlmanacData"))
        val freq = column(LogLines.HEADER_STATUS, status, "CarrierFrequencyHz")
        assertTrue(!freq.contains('E'))
        assertEquals(1575.42e6, freq.toDouble(), 100.0)

        val agc = LogLines.agc(10L, ClockValues(), -3.5, 1_575_420_000L, 1)
        assertEquals(columnCount(LogLines.HEADER_AGC), columnCount(agc))

        val accel = LogLines.uncalAccel(1L, 2L, 0.1f, 0.2f, 9.8f, null, null, null)
        assertEquals(columnCount(LogLines.HEADER_UNCAL_ACCEL), columnCount(accel))

        val gyro = LogLines.uncalGyro(1L, 2L, 0.1f, 0.2f, 0.3f, 0.01f, 0.02f, 0.03f)
        assertEquals(columnCount(LogLines.HEADER_UNCAL_GYRO), columnCount(gyro))

        val bat = LogLines.snBat(1L, null, 80, false, true)
        assertEquals("SnBat,1,,80,0,1", bat)
    }

    @Test
    fun commentAndCapabilityLines() {
        assertEquals("# SnDuty,1700000000000,on", LogLines.snDuty(1_700_000_000_000L, true))
        assertEquals("# SnDuty,5,off", LogLines.snDuty(5L, false))
        assertEquals("SnCap,{\"a\":1, \"b\":2}", LogLines.snCap("{\"a\":1,\n\"b\":2}"))
    }

    @Test
    fun textFieldsCannotShiftColumns() {
        assertEquals("a;b", LogLines.text("a,b"))
        assertEquals("", LogLines.text(null))
    }
}
