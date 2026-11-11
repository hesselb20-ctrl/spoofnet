package net.spoofnet.sdk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ContributorTokenTest {

    private val secret = "spoofnet-test-secret".toByteArray(Charsets.UTF_8)
    private val cell = "851f0000fffffff"

    @Test
    fun matchesIndependentlyComputedValue() {
        // Reference computed with Python's hmac module: hmac.new(secret, b"20000|851f0000fffffff", sha256).digest()[:12].hex()
        assertEquals("4d6527761161e456731ed4bb", ContributorToken.token(secret, 20000L, cell))
    }

    @Test
    fun isDeterministicAnd96BitLowercaseHex() {
        val a = ContributorToken.token(secret, 20000L, cell)
        val b = ContributorToken.token(secret.copyOf(), 20000L, cell)
        assertEquals(a, b)
        assertEquals(24, a.length)
        assertTrue(a.matches(Regex("[0-9a-f]{24}")))
    }

    @Test
    fun changesWithDay() {
        val d0 = ContributorToken.token(secret, 20000L, cell)
        val d1 = ContributorToken.token(secret, 20001L, cell)
        assertNotEquals(d0, d1)
        assertEquals("3a7b15d6ef4def65e2a30093", d1)
    }

    @Test
    fun changesWithCell() {
        val c0 = ContributorToken.token(secret, 20000L, cell)
        val c1 = ContributorToken.token(secret, 20000L, "851e0000fffffff")
        assertNotEquals(c0, c1)
        assertEquals("ced513bf1df405f8335d4452", c1)
    }

    @Test
    fun changesWithSecret() {
        val other = "another-secret".toByteArray(Charsets.UTF_8)
        assertNotEquals(ContributorToken.token(secret, 20000L, cell), ContributorToken.token(other, 20000L, cell))
    }

    @Test(expected = IllegalArgumentException::class)
    fun emptySecretIsRejected() {
        ContributorToken.token(ByteArray(0), 20000L, cell)
    }

    @Test
    fun utcDayBoundaries() {
        assertEquals(0L, ContributorToken.utcDay(0L))
        assertEquals(0L, ContributorToken.utcDay(86_399_999L))
        assertEquals(1L, ContributorToken.utcDay(86_400_000L))
        assertEquals(-1L, ContributorToken.utcDay(-1L))
    }
}
