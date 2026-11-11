package net.spoofnet.sdk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CapabilityReportTest {

    private val changingAgc = CapabilityReport(
        measurementCount = 100,
        agcPerMeasurementSeen = true,
        agcMinDb = -2.0,
        agcMaxDb = 1.5,
        agcDistinctCount = 12,
    )

    @Test
    fun noMeasurementsIsTierDEvenIfOtherFlagsAreSet() {
        val r = changingAgc.copy(measurementCount = 0, dualFrequency = true)
        assertFalse(r.rawMeasurements)
        assertEquals(Tier.D, r.tier())
    }

    @Test
    fun capabilityFlagAloneDoesNotCountAsRaw() {
        val r = CapabilityReport(capabilityHasMeasurements = true, measurementCount = 0)
        assertEquals(Tier.D, r.tier())
    }

    @Test
    fun rawOnlyIsTierC() {
        assertEquals(Tier.C, CapabilityReport(measurementCount = 10).tier())
    }

    @Test
    fun constantAgcDoesNotCount() {
        val r = CapabilityReport(
            measurementCount = 10,
            agcPerMeasurementSeen = true,
            agcMinDb = 0.0,
            agcMaxDb = 0.0,
            agcDistinctCount = 1,
        )
        assertTrue(r.agcAvailable)
        assertFalse(r.agcChanges)
        assertEquals(Tier.C, r.tier())
    }

    @Test
    fun rawWithWorkingAgcIsTierB() {
        assertTrue(changingAgc.workingAgc)
        assertEquals(Tier.B, changingAgc.tier())
    }

    @Test
    fun rawWithDualFrequencyIsTierB() {
        assertEquals(Tier.B, CapabilityReport(measurementCount = 10, dualFrequency = true).tier())
    }

    @Test
    fun agcListAloneCountsAsAgc() {
        val r = CapabilityReport(
            measurementCount = 10,
            agcListSeen = true,
            agcMinDb = 1.0,
            agcMaxDb = 3.0,
            agcDistinctCount = 5,
            dualFrequency = true,
        )
        assertEquals(Tier.A, r.tier())
    }

    @Test
    fun rawWithWorkingAgcAndDualFrequencyIsTierA() {
        assertEquals(Tier.A, changingAgc.copy(dualFrequency = true).tier())
    }

    @Test
    fun tierWeightsMatchDesign() {
        assertEquals(1.0, Tier.A.weight, 0.0)
        assertEquals(0.7, Tier.B.weight, 0.0)
        assertEquals(0.4, Tier.C.weight, 0.0)
        assertEquals(0.15, Tier.D.weight, 0.0)
    }

    @Test
    fun bandGrouping() {
        assertEquals(Band.L5, GnssBands.bandOf(1176.45e6))
        assertEquals(Band.L5, GnssBands.bandOf(1190e6))
        assertEquals(Band.L1, GnssBands.bandOf(1575.42e6))
        assertEquals(Band.L1, GnssBands.bandOf(1602e6))
        assertEquals(Band.L1, GnssBands.bandOf(1561.098e6))
        assertEquals(Band.L1, GnssBands.bandOf(null))
        assertEquals(Band.OTHER, GnssBands.bandOf(1207.14e6))
        assertEquals(2.5, GnssBands.median(listOf(4.0, 1.0, 2.0, 3.0))!!, 0.0)
        assertEquals(null, GnssBands.median(emptyList()))
    }
}
