package de.alchemyfox.foxradio

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.time.LocalTime
import kotlin.coroutines.resume
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Legt einen Block ueber die laufende Musik.
 *
 * PAUSE: Medienlautstaerke stufenweise runter, Audio Focus TRANSIENT holen (die andere App
 * pausiert), Lautstaerke zurueck, Block spielen, stumm schalten, Focus abgeben (Musik setzt
 * wieder ein), stufenweise einblenden.
 *
 * DUCK: Audio Focus TRANSIENT_MAY_DUCK holen (die andere App wird leiser), Block spielen,
 * Focus abgeben.
 */
class AudioEngine(private val context: Context) {

    private val am = context.getSystemService(AudioManager::class.java)
    private val prefs = Prefs(context)
    private val attrs = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_MEDIA)
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
        .build()

    /** file = vorgeladener Block (MP3), null = eingebauter Testblock (Chime + Uhrzeit). */
    suspend fun playBlock(source: String, file: String? = null) {
        val mode = prefs.mode
        val stream = AudioManager.STREAM_MUSIC
        val maxVol = am.getStreamMaxVolume(stream)
        val originalVol = am.getStreamVolume(stream)
        val musicWasPlaying = am.isMusicActive
        val blockVol = maxOf(originalVol, (maxVol * MIN_BLOCK_VOLUME_FRACTION).roundToInt())
        val fadeMusic = mode == InterruptMode.PAUSE && musicWasPlaying

        prefs.appendLog("Block startet ($source, ${mode.name}, Musik ${if (musicWasPlaying) "läuft" else "aus"}, Vol $originalVol/$maxVol)")

        // Wetter holen, solange die Musik noch laeuft - das Netz darf die Pause nicht verlaengern.
        val weather = if (file != null && prefs.liveWeather) Weather.spoken(context) { prefs.appendLog(it) } else null
        val tts = if (file == null || weather != null) TtsSpeaker(context, attrs) else null
        var volumeTouched = false
        var focus: AudioFocusRequest? = null
        try {
            if (fadeMusic) {
                fadeVolume(stream, originalVol, 0, FADE_OUT_MS)
                volumeTouched = true
            }

            focus = requestFocus(mode)
            if (focus == null) {
                prefs.appendLog("Kein Audio Focus, Block abgebrochen")
                return
            }
            delay(if (mode == InterruptMode.PAUSE) 300 else 150)

            if (volumeTouched || blockVol != originalVol) {
                am.setStreamVolume(stream, blockVol, 0)
                volumeTouched = true
            }

            if (file != null) {
                if (weather != null) {
                    tts?.speak(weather) { prefs.appendLog(it) }
                    delay(250)
                }
                playFile(file)
            } else {
                playChime()
                delay(200)
                tts?.speak(context.getString(R.string.tts_intro, spokenTime())) { prefs.appendLog(it) }
            }
            delay(300)
        } finally {
            withContext(NonCancellable) {
                tts?.shutdown()
                if (fadeMusic && volumeTouched) {
                    am.setStreamVolume(stream, 0, 0)
                    abandonFocus(focus)
                    delay(300)
                    fadeVolume(stream, 0, originalVol, FADE_IN_MS)
                } else {
                    abandonFocus(focus)
                    if (volumeTouched) am.setStreamVolume(stream, originalVol, 0)
                }
                prefs.appendLog("Block fertig")
            }
        }
    }

    private suspend fun fadeVolume(stream: Int, from: Int, to: Int, durationMs: Long) {
        val steps = abs(to - from)
        if (steps == 0) return
        val stepDelay = durationMs / steps
        val dir = if (to > from) 1 else -1
        var v = from
        repeat(steps) {
            v += dir
            am.setStreamVolume(stream, v, 0)
            delay(stepDelay)
        }
    }

    private fun requestFocus(mode: InterruptMode): AudioFocusRequest? {
        val gain = if (mode == InterruptMode.PAUSE) {
            AudioManager.AUDIOFOCUS_GAIN_TRANSIENT
        } else {
            AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK
        }
        val request = AudioFocusRequest.Builder(gain)
            .setAudioAttributes(attrs)
            .setWillPauseWhenDucked(false)
            .setAcceptsDelayedFocusGain(false)
            .setOnAudioFocusChangeListener(
                { change -> prefs.appendLog("Focus-Wechsel: $change") },
                Handler(Looper.getMainLooper())
            )
            .build()
        val result = am.requestAudioFocus(request)
        return if (result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
            prefs.appendLog("Audio Focus erhalten")
            request
        } else {
            prefs.appendLog("Audio Focus abgelehnt ($result)")
            null
        }
    }

    private fun abandonFocus(request: AudioFocusRequest?) {
        request?.let { am.abandonAudioFocusRequest(it) }
    }

    private suspend fun playChime() = playSource { player ->
        context.resources.openRawResourceFd(R.raw.chime).use { afd ->
            player.setDataSource(afd.fileDescriptor, afd.startOffset, afd.length)
        }
    }

    private suspend fun playFile(path: String) = playSource { player -> player.setDataSource(path) }

    private suspend fun playSource(setSource: (MediaPlayer) -> Unit) = suspendCancellableCoroutine<Unit> { cont ->
        val player = MediaPlayer()
        var finished = false
        fun finish() {
            if (finished) return
            finished = true
            runCatching { player.release() }
            if (cont.isActive) cont.resume(Unit)
        }
        try {
            player.setAudioAttributes(attrs)
            setSource(player)
            player.setOnCompletionListener { finish() }
            player.setOnErrorListener { _, what, extra ->
                prefs.appendLog("Chime-Fehler $what/$extra")
                finish()
                true
            }
            cont.invokeOnCancellation { finish() }
            player.prepare()
            player.start()
        } catch (e: Exception) {
            prefs.appendLog("Wiedergabe konnte nicht starten: ${e.message}")
            finish()
        }
    }

    private fun spokenTime(): String {
        val now = LocalTime.now()
        return if (now.minute == 0) "${now.hour} Uhr" else "${now.hour} Uhr ${now.minute}"
    }

    companion object {
        private const val FADE_OUT_MS = 1500L
        private const val FADE_IN_MS = 2000L
        private const val MIN_BLOCK_VOLUME_FRACTION = 0.35
    }
}
