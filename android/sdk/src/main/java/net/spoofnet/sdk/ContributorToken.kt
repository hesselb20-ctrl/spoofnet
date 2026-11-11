package net.spoofnet.sdk

import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Unlinkable contributor token, DESIGN.md section 9: the server can count
 * distinct contributors in a place on a day, but cannot link one device across
 * days or across distant places. The secret never leaves the phone.
 */
object ContributorToken {

    private const val ALGORITHM = "HmacSHA256"
    private const val TOKEN_BYTES = 12
    private const val HEX = "0123456789abcdef"

    /** Lowercase hex of the first 96 bits of HMAC-SHA256(deviceSecret, "<utcDay>|<res5Cell>"). */
    fun token(deviceSecret: ByteArray, utcDay: Long, res5Cell: String): String {
        require(deviceSecret.isNotEmpty()) { "deviceSecret must not be empty" }
        val mac = Mac.getInstance(ALGORITHM)
        mac.init(SecretKeySpec(deviceSecret, ALGORITHM))
        val digest = mac.doFinal("$utcDay|$res5Cell".toByteArray(Charsets.UTF_8))
        // Hex by hand: String.format would follow the default locale's digits.
        val sb = StringBuilder(TOKEN_BYTES * 2)
        for (k in 0 until TOKEN_BYTES) {
            val v = digest[k].toInt() and 0xFF
            sb.append(HEX[v ushr 4]).append(HEX[v and 0x0F])
        }
        return sb.toString()
    }

    /** Days since 1970-01-01 UTC, the day number that goes into the token. */
    fun utcDay(utcMillis: Long): Long = Math.floorDiv(utcMillis, 86_400_000L)

    /** A fresh 256-bit secret. Storing it is the host's job; uploading arrives in a later milestone. */
    fun newDeviceSecret(): ByteArray {
        val secret = ByteArray(32)
        SecureRandom().nextBytes(secret)
        return secret
    }
}
