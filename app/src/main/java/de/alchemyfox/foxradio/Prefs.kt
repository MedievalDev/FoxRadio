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

    /** Vor jedem echten Block das aktuelle Wetter per Android-Sprachausgabe ansagen. */
    var liveWeather: Boolean
        get() = sp.getBoolean(KEY_LIVE_WEATHER, true)
        set(value) = sp.edit().putBoolean(KEY_LIVE_WEATHER, value).apply()

    var weatherCache: String
        get() = sp.getString(KEY_WEATHER_CACHE, "") ?: ""
        set(value) = sp.edit().putString(KEY_WEATHER_CACHE, value).apply()

    var weatherCacheAt: Long
        get() = sp.getLong(KEY_WEATHER_CACHE_AT, 0L)
        set(value) = sp.edit().putLong(KEY_WEATHER_CACHE_AT, value).apply()

    var baseUrl: String
        get() = sp.getString(KEY_URL, "") ?: ""
        set(value) = sp.edit().putString(KEY_URL, value.trim().trimEnd('/')).apply()

    var authUser: String
        get() = sp.getString(KEY_USER, "") ?: ""
        set(value) = sp.edit().putString(KEY_USER, value.trim()).apply()

    var authPass: String
        get() = sp.getString(KEY_PASS, "") ?: ""
        set(value) = sp.edit().putString(KEY_PASS, value).apply()

    /** Simulation: Startzeit (0 = aus), Index des naechsten Blocks, Tag der Playlist. */
    var simStart: Long
        get() = sp.getLong(KEY_SIM_START, 0L)
        set(value) = sp.edit().putLong(KEY_SIM_START, value).apply()

    var simIndex: Int
        get() = sp.getInt(KEY_SIM_INDEX, 0)
        set(value) = sp.edit().putInt(KEY_SIM_INDEX, value).apply()

    var lastSync: String
        get() = sp.getString(KEY_LAST_SYNC, "") ?: ""
        set(value) = sp.edit().putString(KEY_LAST_SYNC, value).apply()

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
        private const val KEY_LIVE_WEATHER = "live_weather"
        private const val KEY_WEATHER_CACHE = "weather_cache"
        private const val KEY_WEATHER_CACHE_AT = "weather_cache_at"
        private const val KEY_URL = "base_url"
        private const val KEY_USER = "auth_user"
        private const val KEY_PASS = "auth_pass"
        private const val KEY_LAST_SYNC = "last_sync"
        private const val KEY_SIM_START = "sim_start"
        private const val KEY_SIM_INDEX = "sim_index"
        private const val KEY_LOG = "log"
        private const val MAX_LOG_LINES = 40
        private val LOG_FMT: DateTimeFormatter = DateTimeFormatter.ofPattern("dd.MM. HH:mm:ss")
    }
}
