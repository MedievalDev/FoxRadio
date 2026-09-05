package de.alchemyfox.foxradio

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import java.time.LocalTime

class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val source = intent.getStringExtra(Scheduler.EXTRA_SOURCE) ?: Scheduler.SOURCE_SLOT
        val prefs = Prefs(context)
        prefs.appendLog("Wecker ausgelöst ($source)")

        if (source == Scheduler.SOURCE_SIM) {
            Simulation.onAlarm(context)
            return
        }
        if (source == Scheduler.SOURCE_SYNC) {
            Scheduler.sync(context)
            SyncService.start(context)
            return
        }
        if (source != Scheduler.SOURCE_SLOT) {
            PlaybackService.start(context, source, null)
            return
        }

        if (!prefs.scheduleEnabled) {
            prefs.appendLog("Sendeplan ist aus, Block übersprungen")
            return
        }
        Scheduler.sync(context)?.let { prefs.appendLog("Nächster Block: ${it.format(Schedule.FMT)}") }

        if (Simulation.isActive(prefs)) {
            prefs.appendLog("Simulation läuft, regulärer Block übersprungen")
            return
        }

        val file = blockForNow(context) ?: return

        if (!prefs.onlyWhenMusic) {
            PlaybackService.start(context, source, file)
            return
        }
        val am = context.getSystemService(AudioManager::class.java)
        if (am.isMusicActive) {
            PlaybackService.start(context, source, file)
            return
        }
        // Kurze Luecke zwischen zwei Songs? Nach 1,5 s noch einmal nachsehen.
        val pending = goAsync()
        Handler(Looper.getMainLooper()).postDelayed({
            try {
                if (am.isMusicActive) {
                    PlaybackService.start(context, source, file)
                } else {
                    prefs.appendLog("Keine Musik aktiv, Block übersprungen")
                }
            } finally {
                pending.finish()
            }
        }, RECHECK_DELAY_MS)
    }

    /** Pfad der vorgeladenen Block-Datei fuer die aktuelle volle Stunde, sonst null mit Logeintrag. */
    private fun blockForNow(context: Context): String? {
        val prefs = Prefs(context)
        val lib = Library(context)
        val now = LocalTime.now()
        val slot = now.format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"))
        val (date, blocks) = lib.playlist() ?: run {
            prefs.appendLog("Keine Playlist geladen, Block um $slot übersprungen")
            return null
        }
        val today = java.time.LocalDate.now().toString()
        if (date != today) {
            prefs.appendLog("Playlist ist von $date, nicht von heute. Block um $slot übersprungen")
            return null
        }
        // Der Wecker feuert zur Sendezeit; den Block mit der naechstliegenden Zeit nehmen (max. 10 Minuten daneben).
        val block = blocks
            .mapNotNull { b -> Schedule.parseSlot(b.slot)?.let { t -> b to Math.abs(java.time.Duration.between(t, now).toMinutes()) } }
            .filter { it.second <= 10 }
            .minByOrNull { it.second }?.first ?: run {
            prefs.appendLog("Kein Block für $slot in der Playlist")
            return null
        }
        val file = lib.blockFile(date, block) ?: run {
            prefs.appendLog("Block $slot nicht vorgeladen (${block.file})")
            return null
        }
        return file.absolutePath
    }

    companion object {
        private const val RECHECK_DELAY_MS = 1500L
    }
}
