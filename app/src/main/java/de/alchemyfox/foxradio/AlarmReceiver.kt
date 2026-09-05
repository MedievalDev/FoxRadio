package de.alchemyfox.foxradio

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val source = intent.getStringExtra(Scheduler.EXTRA_SOURCE) ?: Scheduler.SOURCE_SLOT
        val prefs = Prefs(context)
        prefs.appendLog("Wecker ausgelöst ($source)")

        if (source == Scheduler.SOURCE_SLOT) {
            if (!prefs.scheduleEnabled) {
                prefs.appendLog("Sendeplan ist aus, Block übersprungen")
                return
            }
            Scheduler.sync(context)?.let { prefs.appendLog("Nächster Block: ${it.format(Schedule.FMT)}") }
        }

        PlaybackService.start(context, source)
    }
}
