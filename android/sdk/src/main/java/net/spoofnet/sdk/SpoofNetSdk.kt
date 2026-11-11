package net.spoofnet.sdk

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import androidx.core.content.ContextCompat
import java.io.File
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList

/**
 * Entry point for host apps. One session at a time per process; the host
 * keeps it alive (the SpoofNet app does so from a foreground service).
 *
 * Passive only: the SDK listens to GNSS and motion sensors and writes a local
 * file. It opens no network connection in this milestone.
 */
object SpoofNetSdk {

    private const val TAG = "SpoofNetSdk"

    @Volatile
    private var running = false

    @Volatile
    private var latest: LiveStats? = null

    private val listeners = CopyOnWriteArrayList<LiveStatsListener>()
    private val latestStatsListener = LiveStatsListener { latest = it }

    private var logger: RawLogger? = null
    private var probe: CapabilityProbe? = null
    private var battery: BatteryMeter? = null
    private var writer: LogWriter? = null
    private var logFile: File? = null
    private var currentConfig: SpoofNetConfig? = null

    val isRunning: Boolean get() = running

    /**
     * Starts a session. Returns false without starting if ACCESS_FINE_LOCATION
     * is not granted or the log file cannot be created; the host should ask for
     * the permission first.
     */
    @Synchronized
    fun start(context: Context, config: SpoofNetConfig = SpoofNetConfig()): Boolean {
        if (running) return true
        val app = context.applicationContext
        if (ContextCompat.checkSelfPermission(app, Manifest.permission.ACCESS_FINE_LOCATION) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            Log.w(TAG, "ACCESS_FINE_LOCATION not granted; not starting")
            return false
        }
        val w = try {
            LogWriter.create(app, Build.MODEL ?: "unknown", System.currentTimeMillis())
        } catch (e: IOException) {
            Log.w(TAG, "Could not create log file", e)
            return false
        }
        val p = CapabilityProbe(app)
        val b = BatteryMeter(app, w)
        latest = null
        if (!listeners.contains(latestStatsListener)) listeners.add(latestStatsListener)
        val l = RawLogger(app, config, w, p, b, listeners)
        writer = w
        logFile = w.file
        probe = p
        battery = b
        logger = l
        currentConfig = config
        l.start()
        running = true
        return true
    }

    /** Stops the session and writes the closing capability record. Safe to call when not running. */
    @Synchronized
    fun stop() {
        if (!running) return
        running = false
        logger?.stop()
        logger = null
        writer = null
    }

    /**
     * UNKNOWN or LOGGING only. The detectors that can say TRUSTED, DEGRADED or
     * UNTRUSTED arrive in a later milestone; until then nothing here claims to
     * know whether GNSS can be trusted.
     */
    fun trustState(): TrustState = if (running) TrustState.LOGGING else TrustState.UNKNOWN

    /** Report of the current or most recent session, or null if no session ran in this process. */
    fun capabilityReport(): CapabilityReport? = probe?.report()

    fun batterySummary(): BatterySummary? = battery?.summary()

    fun latestLiveStats(): LiveStats? = latest

    fun currentMode(): LoggingMode? = currentConfig?.mode

    fun addLiveStatsListener(listener: LiveStatsListener) {
        if (!listeners.contains(listener)) listeners.add(listener)
    }

    fun removeLiveStatsListener(listener: LiveStatsListener) {
        listeners.remove(listener)
    }

    /**
     * The current session's file, flushed so it can be shared as it is, or the
     * previous session's file once stopped.
     */
    fun currentLogFile(): File? {
        writer?.flush()
        return logFile
    }
}
