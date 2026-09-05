package de.alchemyfox.foxradio

import android.app.Notification
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/** Kurzer Foreground Service, der die Tagesdateien vom Webspace holt. */
class SyncService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var job: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        ServiceCompat.startForeground(this, NOTIF_ID, buildNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        val prefs = Prefs(this)
        if (job?.isActive == true) return START_NOT_STICKY
        job = scope.launch {
            try {
                prefs.appendLog("Sync: " + Sync.run(this@SyncService))
            } catch (t: Throwable) {
                prefs.appendLog("Sync fehlgeschlagen: ${t.message ?: t.javaClass.simpleName}")
            } finally {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        job?.cancel()
        scope.cancel()
        super.onDestroy()
    }

    private fun buildNotification(): Notification =
        NotificationCompat.Builder(this, PlaybackService.CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(getString(R.string.notif_sync))
            .setOngoing(true)
            .setSilent(true)
            .build()

    companion object {
        const val NOTIF_ID = 2

        fun start(context: Context) {
            try {
                ContextCompat.startForegroundService(context, Intent(context, SyncService::class.java))
            } catch (e: Exception) {
                Prefs(context).appendLog("Sync-Start verweigert: ${e.javaClass.simpleName}")
            }
        }
    }
}
