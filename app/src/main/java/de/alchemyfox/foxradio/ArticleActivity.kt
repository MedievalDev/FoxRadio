package de.alchemyfox.foxradio

import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.android.material.button.MaterialButton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/** Eine Meldung lesen und den passenden Abschnitt des Blocks nachhören. */
class ArticleActivity : AppCompatActivity() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val handler = Handler(Looper.getMainLooper())
    private var player: MediaPlayer? = null
    private var focus: AudioFocusRequest? = null
    private lateinit var btnPlay: MaterialButton
    private var article: Article? = null
    private var audio: File? = null

    private val attrs = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_MEDIA)
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
        .build()

    private val stopWatcher = object : Runnable {
        override fun run() {
            val p = player ?: return
            val a = article ?: return
            val endMs = (a.audioEndS * 1000).toInt()
            if (endMs > 0 && p.isPlaying && p.currentPosition >= endMs) {
                stopPlayback()
            } else {
                handler.postDelayed(this, 200)
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_article)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        val lib = Library(this)
        val id = intent.getStringExtra(EXTRA_ID) ?: ""
        val (date, _) = lib.articles() ?: ("" to emptyList())
        val a = lib.articleById(id)
        if (a == null) {
            finish()
            return
        }
        article = a
        audio = lib.audioFileFor(date, a)

        val rubric = findViewById<TextView>(R.id.rubric)
        rubric.text = getString(Images.rubricLabel(a.rubric))
        rubric.setTextColor(ContextCompat.getColor(this, Images.rubricColor(a.rubric)))
        findViewById<TextView>(R.id.title).text = a.title
        findViewById<TextView>(R.id.meta).text = "${a.slot} · " + getString(R.string.article_source, a.sourceName)
        findViewById<TextView>(R.id.body).text = a.body

        val image = findViewById<ImageView>(R.id.image)
        lib.imageFile(date, a)?.let { file ->
            scope.launch {
                val bmp = withContext(Dispatchers.IO) { Images.decode(file, 1200) }
                if (bmp != null) {
                    image.setImageBitmap(bmp)
                    image.visibility = View.VISIBLE
                }
            }
        }

        btnPlay = findViewById(R.id.btnPlay)
        val secs = (a.audioEndS - a.audioStartS).toInt().coerceAtLeast(1)
        btnPlay.text = getString(R.string.btn_play_segment, "${secs}s")
        btnPlay.isEnabled = audio != null
        if (audio == null) btnPlay.text = getString(R.string.audio_missing)
        btnPlay.setOnClickListener { if (player?.isPlaying == true) stopPlayback() else startPlayback() }

        val source = findViewById<MaterialButton>(R.id.btnSource)
        source.visibility = if (a.sourceUrl.isBlank()) View.GONE else View.VISIBLE
        source.setOnClickListener {
            runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(a.sourceUrl))) }
                .onFailure { Toast.makeText(this, a.sourceUrl, Toast.LENGTH_LONG).show() }
        }
    }

    private fun startPlayback() {
        val a = article ?: return
        val file = audio ?: return
        val am = getSystemService(AudioManager::class.java)
        val req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(attrs)
            .setOnAudioFocusChangeListener({ change -> if (change < 0) stopPlayback() }, handler)
            .build()
        if (am.requestAudioFocus(req) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) return
        focus = req
        try {
            val p = MediaPlayer()
            p.setAudioAttributes(attrs)
            p.setDataSource(file.path)
            p.prepare()
            p.seekTo((a.audioStartS * 1000).toInt())
            p.setOnCompletionListener { stopPlayback() }
            p.start()
            player = p
            btnPlay.text = getString(R.string.btn_stop_segment)
            handler.post(stopWatcher)
        } catch (e: Exception) {
            Toast.makeText(this, e.message ?: "Fehler", Toast.LENGTH_SHORT).show()
            stopPlayback()
        }
    }

    private fun stopPlayback() {
        handler.removeCallbacks(stopWatcher)
        player?.let { runCatching { it.stop() }; it.release() }
        player = null
        focus?.let { getSystemService(AudioManager::class.java).abandonAudioFocusRequest(it) }
        focus = null
        val a = article ?: return
        val secs = (a.audioEndS - a.audioStartS).toInt().coerceAtLeast(1)
        btnPlay.text = getString(R.string.btn_play_segment, "${secs}s")
    }

    override fun onPause() {
        stopPlayback()
        super.onPause()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }

    companion object {
        const val EXTRA_ID = "article_id"
    }
}
