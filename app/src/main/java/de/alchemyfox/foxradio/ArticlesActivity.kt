package de.alchemyfox.foxradio

import android.content.Intent
import android.content.res.ColorStateList
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class ArticlesActivity : AppCompatActivity() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_articles)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        val lib = Library(this)
        val (date, articles) = lib.articles() ?: ("" to emptyList())
        val list = findViewById<RecyclerView>(R.id.list)
        val empty = findViewById<TextView>(R.id.emptyText)
        empty.visibility = if (articles.isEmpty()) View.VISIBLE else View.GONE
        supportActionBar?.subtitle = date
        list.layoutManager = LinearLayoutManager(this)
        list.adapter = Adapter(date, articles, lib)
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private inner class Holder(v: View) : RecyclerView.ViewHolder(v) {
        val image: ImageView = v.findViewById(R.id.image)
        val dot: View = v.findViewById(R.id.rubricDot)
        val rubric: TextView = v.findViewById(R.id.rubric)
        val slot: TextView = v.findViewById(R.id.slot)
        val title: TextView = v.findViewById(R.id.title)
        val teaser: TextView = v.findViewById(R.id.teaser)
    }

    private inner class Adapter(val date: String, val items: List<Article>, val lib: Library) : RecyclerView.Adapter<Holder>() {
        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder =
            Holder(LayoutInflater.from(parent.context).inflate(R.layout.item_article, parent, false))

        override fun getItemCount(): Int = items.size

        override fun onBindViewHolder(h: Holder, position: Int) {
            val a = items[position]
            val color = ContextCompat.getColor(this@ArticlesActivity, Images.rubricColor(a.rubric))
            h.rubric.text = getString(Images.rubricLabel(a.rubric))
            h.rubric.setTextColor(color)
            h.dot.backgroundTintList = ColorStateList.valueOf(color)
            h.slot.text = a.slot
            h.title.text = a.title
            h.teaser.text = a.teaser
            h.image.visibility = View.GONE
            h.image.setImageBitmap(null)
            val file = lib.imageFile(date, a)
            if (file != null) {
                h.image.tag = a.id
                scope.launch {
                    val bmp = withContext(Dispatchers.IO) { Images.decode(file, 900) }
                    if (bmp != null && h.image.tag == a.id) {
                        h.image.setImageBitmap(bmp)
                        h.image.visibility = View.VISIBLE
                    }
                }
            }
            h.itemView.setOnClickListener {
                startActivity(Intent(this@ArticlesActivity, ArticleActivity::class.java).putExtra(ArticleActivity.EXTRA_ID, a.id))
            }
        }
    }
}
