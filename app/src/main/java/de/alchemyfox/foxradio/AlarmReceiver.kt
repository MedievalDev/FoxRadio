package de.alchemyfox.foxradio

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.os.Handler
import android.os.Looper

class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val source = intent.getStringExtra(Scheduler.EXTRA_SOURCE) ?: Scheduler.SOURCE_SLOT
        val prefs = Prefs(context)
        prefs.appendLog("Wecker ausgelöst ($source)")

        if (source != Scheduler.SOURCE_SLOT) {
            PlaybackService.start(context, source)
            return
        }

        if (!prefs.scheduleEnabled) {
            prefs.appendLog("Sendeplan ist aus, Block übersprungen")
            return
        }
        Scheduler.sync(context)?.let { prefs.appendLog("Nächster Block: ${it.format(Schedule.FMT)}") }

        if (!prefs.onlyWhenMusic) {
            PlaybackService.start(context, source)
            return
        }

        val am = context.getSystemService(AudioManager::class.java)
        if (am.isMusicActive) {
            PlaybackService.start(context, source)
            return
        }

        // Kurze Luecke zwischen zwei Songs? Nach 1,5 s noch einmal nachsehen.
        val pending = goAsync()
        Handler(Looper.getMainLooper()).postDelayed({
            try {
                if (am.isMusicActive) {
                    PlaybackService.start(context, source)
                } else {
                    prefs.appendLog("Keine Musik aktiv, Block übersprungen")
                }
            } finally {
                pending.finish()
            }
        }, RECHECK_DELAY_MS)
    }

    companion object {
        private const val RECHECK_DELAY_MS = 1500L
    }
}
