package de.alchemyfox.foxradio

import android.content.Context
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/** Holt playlist.json, articles.json, status.json und laedt Bloecke und Bilder vor. */
object Sync {

    class SyncException(msg: String) : Exception(msg)

    suspend fun run(context: Context): String = withContext(Dispatchers.IO) {
        val prefs = Prefs(context)
        val base = prefs.baseUrl
        if (base.isBlank()) throw SyncException("Keine Adresse eingetragen")
        val lib = Library(context)

        val playlistText = fetchText(prefs, "$base/playlist.json")
        val playlist = JSONObject(playlistText)
        val date = playlist.optString("date")
        if (date.isBlank()) throw SyncException("playlist.json ohne Datum")
        val dayDir = lib.dayDir(date)

        var files = 0
        val blocks = playlist.optJSONArray("blocks")
        if (blocks != null) {
            for (i in 0 until blocks.length()) {
                val name = blocks.getJSONObject(i).optString("file")
                if (name.isBlank()) continue
                val dest = File(dayDir, name)
                if (!dest.exists() || dest.length() == 0L) {
                    download(prefs, "$base/$date/$name", dest)
                    files++
                }
            }
        }

        val articlesText = runCatching { fetchText(prefs, "$base/articles.json") }.getOrNull()
        var images = 0
        if (articlesText != null) {
            val arr = JSONObject(articlesText).optJSONArray("articles")
            if (arr != null) {
                for (i in 0 until arr.length()) {
                    val img = arr.getJSONObject(i).optString("image")
                    if (img.isBlank() || img == "null") continue
                    val dest = File(dayDir, img)
                    if (!dest.exists()) {
                        runCatching { download(prefs, "$base/$date/$img", dest) }.onSuccess { images++ }
                    }
                }
            }
            File(lib.root, "articles.json").writeText(articlesText)
        }
        val statusText = runCatching { fetchText(prefs, "$base/status.json") }.getOrNull()
        if (statusText != null) File(lib.root, "status.json").writeText(statusText)
        File(lib.root, "playlist.json").writeText(playlistText)

        cleanup(lib.root, keep = 3)
        val stamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("dd.MM. HH:mm"))
        prefs.lastSync = "$stamp, Tag $date"
        "Tag $date: ${blocks?.length() ?: 0} Blöcke, $files neu geladen, $images Bilder"
    }

    private fun open(prefs: Prefs, url: String): HttpURLConnection {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 15_000
        c.readTimeout = 60_000
        if (prefs.authUser.isNotBlank()) {
            val token = Base64.encodeToString("${prefs.authUser}:${prefs.authPass}".toByteArray(), Base64.NO_WRAP)
            c.setRequestProperty("Authorization", "Basic $token")
        }
        c.setRequestProperty("User-Agent", "FoxRadio Android")
        return c
    }

    private fun fetchText(prefs: Prefs, url: String): String {
        val c = open(prefs, url)
        try {
            val code = c.responseCode
            if (code != 200) throw SyncException("HTTP $code für ${url.substringAfterLast('/')}")
            return c.inputStream.bufferedReader().use { it.readText() }
        } finally {
            c.disconnect()
        }
    }

    private fun download(prefs: Prefs, url: String, dest: File) {
        val c = open(prefs, url)
        try {
            val code = c.responseCode
            if (code != 200) throw SyncException("HTTP $code für ${dest.name}")
            dest.parentFile?.mkdirs()
            val tmp = File(dest.path + ".part")
            c.inputStream.use { input -> tmp.outputStream().use { input.copyTo(it) } }
            if (!tmp.renameTo(dest)) throw SyncException("Konnte ${dest.name} nicht speichern")
        } finally {
            c.disconnect()
        }
    }

    private fun cleanup(root: File, keep: Int) {
        val days = root.listFiles { f -> f.isDirectory && f.name.length == 10 }?.sortedBy { it.name } ?: return
        days.dropLast(keep).forEach { it.deleteRecursively() }
    }
}
