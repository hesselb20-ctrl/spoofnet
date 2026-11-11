package net.spoofnet.sdk

import android.content.Context
import android.os.SystemClock
import android.util.Log
import java.io.BufferedWriter
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.OutputStreamWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * One text log per session, in app-specific storage so no storage permission
 * is needed and the files go away when the app is uninstalled.
 */
class LogWriter private constructor(val file: File) {

    private val out = BufferedWriter(OutputStreamWriter(FileOutputStream(file), Charsets.UTF_8), 64 * 1024)
    private var closed = false
    private var failed = false
    private var lastFlushElapsed = SystemClock.elapsedRealtime()

    init {
        for (header in LogLines.HEADER_LINES) writeLine(header)
        flush()
    }

    @Synchronized
    fun writeLine(line: String) {
        if (closed || failed) return
        try {
            out.write(line)
            out.write("\n")
            // Bounded loss if the process is killed, without a flush per line.
            val now = SystemClock.elapsedRealtime()
            if (now - lastFlushElapsed >= FLUSH_INTERVAL_MS) {
                out.flush()
                lastFlushElapsed = now
            }
        } catch (e: IOException) {
            // A full disk must not crash the host app; stop writing and say so once.
            failed = true
            Log.w(TAG, "Log write failed, logging to file stopped", e)
        }
    }

    @Synchronized
    fun flush() {
        if (closed || failed) return
        try {
            out.flush()
            lastFlushElapsed = SystemClock.elapsedRealtime()
        } catch (e: IOException) {
            failed = true
            Log.w(TAG, "Log flush failed", e)
        }
    }

    @Synchronized
    fun close() {
        if (closed) return
        closed = true
        try {
            out.close()
        } catch (e: IOException) {
            Log.w(TAG, "Log close failed", e)
        }
    }

    companion object {
        private const val TAG = "SpoofNetLog"
        private const val FLUSH_INTERVAL_MS = 5_000L

        /** Where session logs live; external app-specific storage if mounted, internal otherwise. */
        fun logDirectory(context: Context): File {
            val dir = context.getExternalFilesDir("logs") ?: File(context.filesDir, "logs")
            if (!dir.exists()) dir.mkdirs()
            return dir
        }

        /** UTC in the name so files from phones in different time zones sort together. */
        fun fileName(model: String, utcMillis: Long): String {
            val fmt = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US)
            fmt.timeZone = TimeZone.getTimeZone("UTC")
            val safeModel = model.replace(Regex("[^A-Za-z0-9-]"), "-").ifEmpty { "unknown" }
            return "spoofnet_" + fmt.format(Date(utcMillis)) + "_" + safeModel + ".txt"
        }

        @Throws(IOException::class)
        fun create(context: Context, model: String, utcMillis: Long): LogWriter {
            val file = File(logDirectory(context), fileName(model, utcMillis))
            return LogWriter(file)
        }
    }
}
