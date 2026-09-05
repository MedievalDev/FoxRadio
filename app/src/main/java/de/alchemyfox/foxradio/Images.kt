package de.alchemyfox.foxradio

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import java.io.File

object Images {
    /** Dekodiert ein Bild verkleinert, damit Listen nicht den Speicher sprengen. */
    fun decode(file: File, maxWidth: Int = 1200): Bitmap? = runCatching {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, bounds)
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= maxWidth) sample *= 2
        BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
    }.getOrNull()

    fun rubricLabel(rubric: String): Int = when (rubric) {
        "gaming" -> R.string.rubric_gaming
        "dev" -> R.string.rubric_dev
        "anthropic" -> R.string.rubric_anthropic
        "indie" -> R.string.rubric_indie
        else -> R.string.rubric_dev
    }

    fun rubricColor(rubric: String): Int = when (rubric) {
        "gaming" -> R.color.rubric_gaming
        "dev" -> R.color.rubric_dev
        "anthropic" -> R.color.rubric_anthropic
        "indie" -> R.color.rubric_indie
        else -> R.color.fox_gray
    }
}
