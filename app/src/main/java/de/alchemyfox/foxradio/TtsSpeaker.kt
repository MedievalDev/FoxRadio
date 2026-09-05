package de.alchemyfox.foxradio

import android.content.Context
import android.media.AudioAttributes
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeoutOrNull
import java.util.Locale

/** Spricht einen Text mit der Android-TTS-Stimme und wartet, bis er fertig ist. */
class TtsSpeaker(context: Context, private val attrs: AudioAttributes) {

    private val ready = CompletableDeferred<Boolean>()
    private val tts: TextToSpeech = TextToSpeech(context.applicationContext) { status ->
        ready.complete(status == TextToSpeech.SUCCESS)
    }

    suspend fun speak(text: String, log: (String) -> Unit) {
        val ok = withTimeoutOrNull(INIT_TIMEOUT_MS) { ready.await() } ?: false
        if (!ok) {
            log("TTS nicht verfügbar")
            return
        }
        val lang = tts.setLanguage(Locale.GERMANY)
        if (lang == TextToSpeech.LANG_MISSING_DATA || lang == TextToSpeech.LANG_NOT_SUPPORTED) {
            log("TTS: Deutsch fehlt ($lang)")
            return
        }
        tts.setAudioAttributes(attrs)

        val done = CompletableDeferred<Unit>()
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) {
                done.complete(Unit)
            }

            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) {
                done.complete(Unit)
            }

            override fun onError(utteranceId: String?, errorCode: Int) {
                log("TTS-Fehler $errorCode")
                done.complete(Unit)
            }
        })

        val result = tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "foxradio-${System.currentTimeMillis()}")
        if (result != TextToSpeech.SUCCESS) {
            log("TTS speak fehlgeschlagen ($result)")
            return
        }
        withTimeoutOrNull(SPEAK_TIMEOUT_MS) { done.await() } ?: log("TTS Timeout")
    }

    fun shutdown() {
        runCatching {
            tts.stop()
            tts.shutdown()
        }
    }

    companion object {
        private const val INIT_TIMEOUT_MS = 6_000L
        private const val SPEAK_TIMEOUT_MS = 30_000L
    }
}
