package de.alchemyfox.foxradio

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/** Foreground Service, der genau einen Block abspielt und sich danach beendet. */
class PlaybackService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var job: Job? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        ServiceCompat.startForeground(
            this,
            NOTIF_ID,
            buildNotification(),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
        )

        val prefs = Prefs(this)
        if (job?.isActive == true) {
            prefs.appendLog("Block läuft schon, zweiter Start ignoriert")
            return START_NOT_STICKY
        }

        val source = intent?.getStringExtra(EXTRA_SOURCE) ?: "unbekannt"
        val file = intent?.getStringExtra(EXTRA_FILE)
        acquireWakeLock()
        job = scope.launch {
            try {
                AudioEngine(this@PlaybackService).playBlock(source, file)
            } catch (t: Throwable) {
                prefs.appendLog("Fehler: ${t.javaClass.simpleName}: ${t.message}")
            } finally {
                releaseWakeLock()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        job?.cancel()
        scope.cancel()
        releaseWakeLock()
        super.onDestroy()
    }

    private fun acquireWakeLock() {
        val pm = getSystemService(PowerManager::class.java)
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "FoxRadio:Playback").apply {
            acquire(WAKELOCK_TIMEOUT_MS)
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
    }

    private fun buildNotification(): Notification {
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(getString(R.string.notif_text))
            .setContentIntent(open)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    companion object {
        const val CHANNEL_ID = "foxradio_playback"
        const val NOTIF_ID = 1
        const val EXTRA_SOURCE = "source"
        const val EXTRA_FILE = "file"
        private const val WAKELOCK_TIMEOUT_MS = 20 * 60_000L

        /** file = Pfad eines vorgeladenen Blocks, null = eingebauter Testblock. */
        fun start(context: Context, source: String, file: String?) {
            val intent = Intent(context, PlaybackService::class.java)
                .putExtra(EXTRA_SOURCE, source)
                .putExtra(EXTRA_FILE, file)
            try {
                ContextCompat.startForegroundService(context, intent)
            } catch (e: Exception) {
                Prefs(context).appendLog("Service-Start verweigert: ${e.javaClass.simpleName}")
            }
        }
    }
}
