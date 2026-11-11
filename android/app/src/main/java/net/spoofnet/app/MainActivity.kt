package net.spoofnet.app

import android.Manifest
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.Button
import android.widget.RadioGroup
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import net.spoofnet.sdk.LiveStats
import net.spoofnet.sdk.LiveStatsListener
import net.spoofnet.sdk.LogWriter
import net.spoofnet.sdk.LoggingMode
import net.spoofnet.sdk.SpoofNetSdk
import net.spoofnet.sdk.TrustState
import java.io.File
import java.util.Locale

class MainActivity : AppCompatActivity() {

    private lateinit var prefs: SharedPreferences

    private lateinit var groupOptIn: View
    private lateinit var groupMain: View
    private lateinit var groupMode: RadioGroup
    private lateinit var buttonStart: Button
    private lateinit var buttonStop: Button
    private lateinit var buttonBackground: Button
    private lateinit var textStatus: TextView
    private lateinit var textLiveHint: TextView
    private lateinit var textSatellites: TextView
    private lateinit var textCn0L1: TextView
    private lateinit var textCn0L5: TextView
    private lateinit var textAgc: TextView
    private lateinit var textClock: TextView
    private lateinit var textBattery: TextView
    private lateinit var textFile: TextView

    private val uiHandler = Handler(Looper.getMainLooper())

    private val refresher = object : Runnable {
        override fun run() {
            refreshState()
            uiHandler.postDelayed(this, REFRESH_MS)
        }
    }

    private val statsListener = LiveStatsListener { stats ->
        runOnUiThread { showStats(stats) }
    }

    // Step 1: precise location. COARSE is requested alongside because Android 12+ ignores a
    // FINE-only request; the user may still grant only approximate, which is not enough.
    private val locationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
            if (hasFineLocation()) {
                requestNotificationsThenStart()
            } else {
                Toast.makeText(this, R.string.status_need_fine, Toast.LENGTH_LONG).show()
            }
        }

    // Step 2: notifications on Android 13+. Logging starts whatever the answer; without the
    // permission the foreground service still runs, its notification is just hidden.
    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) {
            startLoggingService()
        }

    // Step 3, separate and optional: background location.
    private val backgroundPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) {
            refreshState()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE)

        groupOptIn = findViewById(R.id.group_optin)
        groupMain = findViewById(R.id.group_main)
        groupMode = findViewById(R.id.group_mode)
        buttonStart = findViewById(R.id.button_start)
        buttonStop = findViewById(R.id.button_stop)
        buttonBackground = findViewById(R.id.button_background)
        textStatus = findViewById(R.id.text_status)
        textLiveHint = findViewById(R.id.text_live_hint)
        textSatellites = findViewById(R.id.text_satellites)
        textCn0L1 = findViewById(R.id.text_cn0_l1)
        textCn0L5 = findViewById(R.id.text_cn0_l5)
        textAgc = findViewById(R.id.text_agc)
        textClock = findViewById(R.id.text_clock)
        textBattery = findViewById(R.id.text_battery)
        textFile = findViewById(R.id.text_file)

        findViewById<Button>(R.id.button_accept).setOnClickListener {
            prefs.edit().putBoolean(KEY_OPTED_IN, true).apply()
            showScreen()
        }
        buttonStart.setOnClickListener { onStartPressed() }
        buttonStop.setOnClickListener { onStopPressed() }
        buttonBackground.setOnClickListener { explainBackgroundLocation() }
        findViewById<Button>(R.id.button_capability).setOnClickListener { showCapabilityReport() }
        findViewById<Button>(R.id.button_share).setOnClickListener { shareLogFile() }

        groupMode.check(modeButtonId(savedMode()))
        groupMode.setOnCheckedChangeListener { _, checkedId ->
            prefs.edit().putString(KEY_MODE, modeForButton(checkedId).name).apply()
        }

        showScreen()
    }

    override fun onStart() {
        super.onStart()
        SpoofNetSdk.addLiveStatsListener(statsListener)
        SpoofNetSdk.latestLiveStats()?.let { showStats(it) }
        uiHandler.post(refresher)
    }

    override fun onStop() {
        SpoofNetSdk.removeLiveStatsListener(statsListener)
        uiHandler.removeCallbacks(refresher)
        super.onStop()
    }

    private fun showScreen() {
        val optedIn = prefs.getBoolean(KEY_OPTED_IN, false)
        groupOptIn.visibility = if (optedIn) View.GONE else View.VISIBLE
        groupMain.visibility = if (optedIn) View.VISIBLE else View.GONE
        refreshState()
    }

    // Permissions and start/stop.

    private fun hasPermission(permission: String): Boolean =
        ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED

    private fun hasFineLocation(): Boolean = hasPermission(Manifest.permission.ACCESS_FINE_LOCATION)

    private fun onStartPressed() {
        if (SpoofNetSdk.isRunning) return
        if (!hasFineLocation()) {
            locationPermissionLauncher.launch(
                arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION),
            )
            return
        }
        requestNotificationsThenStart()
    }

    private fun requestNotificationsThenStart() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            !hasPermission(Manifest.permission.POST_NOTIFICATIONS)
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            startLoggingService()
        }
    }

    private fun startLoggingService() {
        if (!hasFineLocation()) {
            Toast.makeText(this, R.string.status_need_fine, Toast.LENGTH_LONG).show()
            return
        }
        ContextCompat.startForegroundService(this, LoggingService.startIntent(this, selectedMode()))
        // The service starts the SDK asynchronously; check back shortly.
        uiHandler.postDelayed({
            refreshState()
            if (!SpoofNetSdk.isRunning) {
                Toast.makeText(this, R.string.status_start_failed, Toast.LENGTH_LONG).show()
            }
        }, START_CHECK_MS)
    }

    private fun onStopPressed() {
        stopService(Intent(this, LoggingService::class.java))
        uiHandler.postDelayed({ refreshState() }, STOP_CHECK_MS)
    }

    private fun explainBackgroundLocation() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.background_title)
            .setMessage(R.string.background_body)
            .setPositiveButton(R.string.background_continue) { _, _ ->
                backgroundPermissionLauncher.launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
            }
            .setNegativeButton(R.string.background_not_now, null)
            .show()
    }

    // Mode picker.

    private fun savedMode(): LoggingMode {
        val name = prefs.getString(KEY_MODE, null)
        return LoggingMode.values().firstOrNull { it.name == name } ?: LoggingMode.CONTINUOUS
    }

    private fun selectedMode(): LoggingMode = modeForButton(groupMode.checkedRadioButtonId)

    private fun modeForButton(id: Int): LoggingMode = when (id) {
        R.id.mode_balanced -> LoggingMode.BALANCED
        R.id.mode_saver -> LoggingMode.SAVER
        else -> LoggingMode.CONTINUOUS
    }

    private fun modeButtonId(mode: LoggingMode): Int = when (mode) {
        LoggingMode.CONTINUOUS -> R.id.mode_continuous
        LoggingMode.BALANCED -> R.id.mode_balanced
        LoggingMode.SAVER -> R.id.mode_saver
    }

    // Display.

    private fun refreshState() {
        val running = SpoofNetSdk.isRunning
        buttonStart.isEnabled = !running
        buttonStop.isEnabled = running
        for (k in 0 until groupMode.childCount) groupMode.getChildAt(k).isEnabled = !running

        // Neutral wording on purpose: until the detectors exist the app makes no trust claim.
        textStatus.text = when (SpoofNetSdk.trustState()) {
            TrustState.LOGGING -> getString(
                R.string.status_logging,
                (SpoofNetSdk.currentMode() ?: selectedMode()).name.lowercase(Locale.US),
            )
            else -> getString(R.string.status_idle)
        }

        val showBackground = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
            hasFineLocation() &&
            !hasPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
        buttonBackground.visibility = if (showBackground) View.VISIBLE else View.GONE

        showBattery()
        val file = SpoofNetSdk.currentLogFile() ?: latestLogFile()
        textFile.text = if (file != null) getString(R.string.file_current, file.name) else getString(R.string.file_none)
    }

    private fun showStats(s: LiveStats) {
        textLiveHint.visibility = View.GONE
        textSatellites.text = getString(R.string.live_satellites, s.satelliteCount.toString())
        textCn0L1.text = getString(R.string.live_cn0_l1, dbHz(s.medianCn0L1DbHz))
        textCn0L5.text = getString(R.string.live_cn0_l5, dbHz(s.medianCn0L5DbHz))
        textAgc.text = getString(R.string.live_agc, db(s.agcL1Db), db(s.agcL5Db))
        textClock.text = getString(R.string.live_clock, s.hardwareClockDiscontinuityCount.toString())
    }

    private fun showBattery() {
        val b = SpoofNetSdk.batterySummary()
        if (b == null) {
            textBattery.setText(R.string.battery_none)
            return
        }
        val parts = StringBuilder()
        parts.append(
            getString(
                R.string.battery_summary,
                String.format(Locale.US, "%.2f", b.hours),
                b.mahUsed?.let { String.format(Locale.US, "%.0f", it) } ?: getString(R.string.value_none),
                b.percentUsed?.let { String.format(Locale.US, "%.1f", it) } ?: getString(R.string.value_none),
                b.percentPerDay?.let { String.format(Locale.US, "%.1f", it) } ?: getString(R.string.value_none),
            ),
        )
        if (b.percentPerDay == null) parts.append('\n').append(getString(R.string.battery_too_short))
        if (b.chargedDuringSession) parts.append('\n').append(getString(R.string.battery_invalid))
        textBattery.text = parts.toString()
    }

    private fun dbHz(v: Double?): String =
        if (v == null) getString(R.string.value_none)
        else getString(R.string.unit_dbhz, String.format(Locale.US, "%.1f", v))

    private fun db(v: Double?): String =
        if (v == null) getString(R.string.value_none)
        else getString(R.string.unit_db, String.format(Locale.US, "%.1f", v))

    private fun showCapabilityReport() {
        val report = SpoofNetSdk.capabilityReport()
        val message = if (report == null) {
            getString(R.string.capability_none)
        } else {
            getString(R.string.capability_tier, report.tier().name) + "\n\n" + report.toJson().toString(2)
        }
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.capability_title)
            .setMessage(message)
            .setPositiveButton(R.string.dialog_close, null)
            .show()
    }

    // Export. Manual only: the user picks where the file goes.

    private fun latestLogFile(): File? =
        LogWriter.logDirectory(this).listFiles()
            ?.filter { it.isFile && it.name.startsWith("spoofnet_") }
            ?.maxByOrNull { it.lastModified() }

    private fun shareLogFile() {
        val file = SpoofNetSdk.currentLogFile() ?: latestLogFile()
        if (file == null || !file.exists()) {
            Toast.makeText(this, R.string.file_none, Toast.LENGTH_SHORT).show()
            return
        }
        try {
            val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
            val send = Intent(Intent.ACTION_SEND).apply {
                type = "text/plain"
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(send, getString(R.string.share_chooser_title)))
        } catch (e: IllegalArgumentException) {
            Toast.makeText(this, R.string.share_failed, Toast.LENGTH_SHORT).show()
        }
    }

    companion object {
        private const val PREFS = "spoofnet"
        private const val KEY_OPTED_IN = "opted_in"
        private const val KEY_MODE = "mode"
        private const val REFRESH_MS = 5_000L
        private const val START_CHECK_MS = 1_500L
        private const val STOP_CHECK_MS = 2_000L
    }
}
