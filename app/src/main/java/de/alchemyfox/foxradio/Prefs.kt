package de.alchemyfox.foxradio

import android.content.Context
import android.content.SharedPreferences
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

enum class InterruptMode { PAUSE, DUCK }

/** Einstellungen und ein kleines Protokoll, damit man am Handy sieht, ob der Wecker gefeuert hat. */
class Prefs(context: Context) {
    private val sp: SharedPreferences =
        context.applicationContext.getSharedPreferences("foxradio", Context.MODE_PRIVATE)

    var mode: InterruptMode
        get() = runCatching { InterruptMode.valueOf(sp.getString(KEY_MODE, "") ?: "") }
            .getOrDefault(InterruptMode.PAUSE)
        set(value) = sp.edit().putString(KEY_MODE, value.name).apply()

    var scheduleEnabled: Boolean
        get() = sp.getBoolean(KEY_SCHEDULE, false)
        set(value) = sp.edit().putBoolean(KEY_SCHEDULE, value).apply()

    var weekdaysOnly: Boolean
        get() = sp.getBoolean(KEY_WEEKDAYS, true)
        set(value) = sp.edit().putBoolean(KEY_WEEKDAYS, value).apply()

    /** Sendeplan-Bloecke nur spielen, wenn gerade Musik laeuft. Test-Buttons spielen immer. */
    var onlyWhenMusic: Boolean
        get() = sp.getBoolean(KEY_ONLY_MUSIC, true)
        set(value) = sp.edit().putBoolean(KEY_ONLY_MUSIC, value).apply()

    val log: String
        get() = sp.getString(KEY_LOG, "") ?: ""

    fun appendLog(line: String) {
        val stamp = LocalDateTime.now().format(LOG_FMT)
        val lines = (log.lines().filter { it.isNotBlank() } + "$stamp $line").takeLast(MAX_LOG_LINES)
        sp.edit().putString(KEY_LOG, lines.joinToString("\n")).apply()
    }

    fun clearLog() = sp.edit().remove(KEY_LOG).apply()

    companion object {
        private const val KEY_MODE = "mode"
        private const val KEY_SCHEDULE = "schedule_enabled"
        private const val KEY_WEEKDAYS = "weekdays_only"
        private const val KEY_ONLY_MUSIC = "only_when_music"
        private const val KEY_LOG = "log"
        private const val MAX_LOG_LINES = 40
        private val LOG_FMT: DateTimeFormatter = DateTimeFormatter.ofPattern("dd.MM. HH:mm:ss")
    }
}
