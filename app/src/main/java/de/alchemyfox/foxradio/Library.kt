package de.alchemyfox.foxradio

import android.content.Context
import org.json.JSONObject
import java.io.File

data class Block(val slot: String, val file: String, val kind: String, val durationS: Double, val title: String)

data class Article(
    val id: String,
    val slot: String,
    val rubric: String,
    val title: String,
    val teaser: String,
    val body: String,
    val sourceName: String,
    val sourceUrl: String,
    val image: String?,
    val audioFile: String?,
    val audioStartS: Double,
    val audioEndS: Double,
)

data class NightStatus(val ok: Boolean, val date: String, val message: String)

/** Liest die vom Nachtlauf hochgeladenen und von Sync gespeicherten Dateien. */
class Library(context: Context) {
    val root: File = File(context.filesDir, "radio").apply { mkdirs() }

    fun dayDir(date: String): File = File(root, date).apply { mkdirs() }

    fun playlist(): Pair<String, List<Block>>? {
        val json = readJson(File(root, "playlist.json")) ?: return null
        val date = json.optString("date")
        val arr = json.optJSONArray("blocks") ?: return date to emptyList()
        val blocks = (0 until arr.length()).map { i ->
            val b = arr.getJSONObject(i)
            Block(b.optString("slot"), b.optString("file"), b.optString("kind"), b.optDouble("duration_s", 0.0), b.optString("title"))
        }
        return date to blocks
    }

    fun articles(): Pair<String, List<Article>>? {
        val json = readJson(File(root, "articles.json")) ?: return null
        val date = json.optString("date")
        val arr = json.optJSONArray("articles") ?: return date to emptyList()
        val list = (0 until arr.length()).map { i ->
            val a = arr.getJSONObject(i)
            Article(
                id = a.optString("id"), slot = a.optString("slot"), rubric = a.optString("rubric"),
                title = a.optString("title"), teaser = a.optString("teaser"), body = a.optString("body"),
                sourceName = a.optString("source_name"), sourceUrl = a.optString("source_url"),
                image = a.optString("image").takeIf { it.isNotBlank() && it != "null" },
                audioFile = a.optString("audio_file").takeIf { it.isNotBlank() },
                audioStartS = a.optDouble("audio_start_s", 0.0), audioEndS = a.optDouble("audio_end_s", 0.0),
            )
        }
        return date to list
    }

    fun status(): NightStatus? {
        val json = readJson(File(root, "status.json")) ?: return null
        return NightStatus(json.optBoolean("ok", false), json.optString("date"), json.optString("message"))
    }

    /** Lokale Datei fuer einen Block des Tages, null wenn nicht vorgeladen. */
    fun blockFile(date: String, block: Block): File? =
        File(dayDir(date), block.file).takeIf { it.exists() && it.length() > 0 }

    fun articleById(id: String): Article? = articles()?.second?.firstOrNull { it.id == id }

    fun imageFile(date: String, article: Article): File? =
        article.image?.let { File(dayDir(date), it) }?.takeIf { it.exists() }

    fun audioFileFor(date: String, article: Article): File? =
        article.audioFile?.let { File(dayDir(date), it) }?.takeIf { it.exists() }

    private fun readJson(f: File): JSONObject? = runCatching {
        if (!f.exists()) null else JSONObject(f.readText())
    }.getOrNull()
}
