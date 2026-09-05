package de.alchemyfox.foxradio

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.math.roundToInt

/**
 * Live-Wetter fuer Ellwangen von Open-Meteo, als Satz fuer die Android-Sprachausgabe.
 *
 * Die Bloecke werden nachts gerendert, ihr Wetter waere tagsueber Stunden alt. Deshalb holt
 * das Handy das Wetter direkt vor dem Block und spricht es selbst. Ohne Netz (Funkloch in
 * der Halle) gilt der letzte Stand, wenn er nicht aelter als drei Stunden ist, sonst faellt
 * die Ansage aus.
 */
object Weather {

    private const val LAT = 48.9614
    private const val LON = 10.1317
    private const val PLACE = "Ellwangen"
    private const val TIMEOUT_MS = 8_000L
    private const val CACHE_MAX_AGE_MS = 3 * 60 * 60 * 1000L

    private val URL_TEXT = "https://api.open-meteo.com/v1/forecast?latitude=$LAT&longitude=$LON" +
        "&current=temperature_2m,weathercode&daily=temperature_2m_max,precipitation_probability_max" +
        "&timezone=Europe%2FBerlin&forecast_days=1"

    /** Gesprochener Wettersatz oder null, wenn nichts Brauchbares da ist. */
    suspend fun spoken(context: Context, log: (String) -> Unit): String? {
        val prefs = Prefs(context)
        val fresh = withTimeoutOrNull(TIMEOUT_MS) {
            withContext(Dispatchers.IO) { runCatching { fetch() }.getOrElse { log("Wetter: ${it.message}"); null } }
        }
        if (fresh != null) {
            prefs.weatherCache = fresh
            prefs.weatherCacheAt = System.currentTimeMillis()
            return fresh
        }
        val cached = prefs.weatherCache
        val age = System.currentTimeMillis() - prefs.weatherCacheAt
        return if (cached.isNotBlank() && age in 0..CACHE_MAX_AGE_MS) {
            log("Wetter aus dem Zwischenspeicher (${age / 60_000} min alt)")
            cached
        } else {
            log("Wetter nicht erreichbar, Ansage entfaellt")
            null
        }
    }

    private fun fetch(): String {
        val c = URL(URL_TEXT).openConnection() as HttpURLConnection
        c.connectTimeout = 6_000
        c.readTimeout = 6_000
        c.setRequestProperty("User-Agent", "FoxRadio Android")
        val body = c.inputStream.bufferedReader().use { it.readText() }
        val json = JSONObject(body)
        val current = json.getJSONObject("current")
        val daily = json.getJSONObject("daily")
        val temp = current.getDouble("temperature_2m").roundToInt()
        val code = current.getInt("weathercode")
        val tmax = daily.getJSONArray("temperature_2m_max").getDouble(0).roundToInt()
        val rain = daily.getJSONArray("precipitation_probability_max").optInt(0, -1)
        val text = describe(code)
        val sb = StringBuilder("Wetter in $PLACE: gerade $temp Grad und $text, heute bis $tmax Grad")
        if (rain >= 0) sb.append(", Regenwahrscheinlichkeit $rain Prozent")
        sb.append(".")
        return sb.toString()
    }

    private fun describe(code: Int): String = when (code) {
        0 -> "klar"
        1 -> "überwiegend klar"
        2 -> "teils bewölkt"
        3 -> "bedeckt"
        45, 48 -> "Nebel"
        51, 53, 55 -> "Nieselregen"
        56, 57 -> "gefrierender Nieselregen"
        61 -> "leichter Regen"
        63 -> "Regen"
        65 -> "starker Regen"
        66, 67 -> "gefrierender Regen"
        71 -> "leichter Schneefall"
        73 -> "Schneefall"
        75 -> "starker Schneefall"
        77 -> "Schneegriesel"
        80 -> "leichte Schauer"
        81 -> "Schauer"
        82 -> "heftige Schauer"
        85, 86 -> "Schneeschauer"
        95 -> "Gewitter"
        96, 99 -> "Gewitter mit Hagel"
        else -> "wechselhaft"
    }
}
