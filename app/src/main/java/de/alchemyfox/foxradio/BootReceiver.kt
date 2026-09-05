package de.alchemyfox.foxradio

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Nach Neustart, App-Update, Zeitumstellung oder Berechtigungswechsel neu planen. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val prefs = Prefs(context)
        val action = intent.action?.substringAfterLast('.') ?: "?"
        val next = Scheduler.sync(context)
        prefs.appendLog(
            if (next != null) "System ($action): neu geplant für ${next.format(Schedule.FMT)}"
            else "System ($action): Sendeplan aus"
        )
    }
}
