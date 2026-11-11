package net.spoofnet.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import net.spoofnet.sdk.LoggingMode
import net.spoofnet.sdk.SpoofNetConfig
import net.spoofnet.sdk.SpoofNetSdk

/**
 * Owns the SDK session so logging survives the activity going away. A
 * location-type foreground service is what keeps GNSS callbacks flowing with
 * the screen off on current Android versions.
 */
class LoggingService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }

        val modeName = intent?.getStringExtra(EXTRA_MODE)
        val mode = LoggingMode.values().firstOrNull { it.name == modeName } ?: LoggingMode.CONTINUOUS

        createChannel()
        val notification = buildNotification()
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
        } catch (e: RuntimeException) {
            // Android 12+ refuses foreground starts from the background, and 14+ refuses a location
            // service without location permission. Either way there is nothing to run.
            Log.w(TAG, "Foreground start refused", e)
            stopSelf()
            return START_NOT_STICKY
        }

        if (!SpoofNetSdk.isRunning) {
            val started = SpoofNetSdk.start(applicationContext, SpoofNetConfig(mode = mode))
            if (!started) {
                stopSelf()
                return START_NOT_STICKY
            }
        }
        // Not sticky: a system restart would come from the background, where a location
        // foreground service is not allowed to start.
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        SpoofNetSdk.stop()
        super.onDestroy()
    }

    private fun createChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.notification_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        )
        channel.description = getString(R.string.notification_channel_description)
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification {
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        val openIntent = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), flags,
        )
        val stopIntent = PendingIntent.getService(
            this, 1, Intent(this, LoggingService::class.java).setAction(ACTION_STOP), flags,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_spoofnet)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(getString(R.string.notification_text))
            .setStyle(NotificationCompat.BigTextStyle().bigText(getString(R.string.notification_text)))
            .setOngoing(true)
            .setContentIntent(openIntent)
            .addAction(0, getString(R.string.notification_stop), stopIntent)
            .build()
    }

    companion object {
        private const val TAG = "SpoofNetService"
        private const val CHANNEL_ID = "logging"
        private const val NOTIFICATION_ID = 1
        private const val ACTION_STOP = "net.spoofnet.app.action.STOP"
        private const val EXTRA_MODE = "mode"

        fun startIntent(context: Context, mode: LoggingMode): Intent =
            Intent(context, LoggingService::class.java).putExtra(EXTRA_MODE, mode.name)
    }
}
