package de.alchemyfox.foxradio

import android.Manifest
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.google.android.material.button.MaterialButtonToggleGroup
import com.google.android.material.materialswitch.MaterialSwitch
import java.time.Duration
import java.time.ZonedDateTime

class MainActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private lateinit var statusLabel: TextView
    private lateinit var statusTime: TextView
    private lateinit var statusCountdown: TextView
    private lateinit var statusWarning: TextView
    private lateinit var modeGroup: MaterialButtonToggleGroup
    private lateinit var modeHint: TextView
    private lateinit var switchSchedule: MaterialSwitch
    private lateinit var switchWeekdays: MaterialSwitch
    private lateinit var switchOnlyMusic: MaterialSwitch
    private lateinit var switchLiveWeather: MaterialSwitch
    private lateinit var dotExact: View
    private lateinit var dotBattery: View
    private lateinit var dotNotify: View
    private lateinit var dotAutostart: View
    private lateinit var logText: TextView
    private lateinit var todayText: TextView
    private lateinit var todayStatus: TextView

    private val handler = Handler(Looper.getMainLooper())
    private val ticker = object : Runnable {
        override fun run() {
            refresh()
            handler.postDelayed(this, TICK_MS)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)

        statusLabel = findViewById(R.id.statusLabel)
        statusTime = findViewById(R.id.statusTime)
        statusCountdown = findViewById(R.id.statusCountdown)
        statusWarning = findViewById(R.id.statusWarning)
        modeGroup = findViewById(R.id.modeGroup)
        modeHint = findViewById(R.id.modeHint)
        switchSchedule = findViewById(R.id.switchSchedule)
        switchWeekdays = findViewById(R.id.switchWeekdays)
        switchOnlyMusic = findViewById(R.id.switchOnlyMusic)
        switchLiveWeather = findViewById(R.id.switchLiveWeather)
        dotExact = findViewById(R.id.dotExact)
        dotBattery = findViewById(R.id.dotBattery)
        dotNotify = findViewById(R.id.dotNotify)
        dotAutostart = findViewById(R.id.dotAutostart)
        logText = findViewById(R.id.logText)
        todayText = findViewById(R.id.todayText)
        todayStatus = findViewById(R.id.todayStatus)

        findViewById<View>(R.id.btnPlayNow).setOnClickListener {
            prefs.appendLog("Test: sofort")
            PlaybackService.start(this, "manuell", null)
            refresh()
        }

        findViewById<View>(R.id.btnPlayIn2Min).setOnClickListener {
            Scheduler.scheduleTest(this, 2 * 60_000L)
            prefs.appendLog("Test in 2 Minuten geplant")
            Toast.makeText(this, R.string.toast_test_scheduled, Toast.LENGTH_LONG).show()
            refresh()
        }

        modeGroup.check(if (prefs.mode == InterruptMode.PAUSE) R.id.modePause else R.id.modeDuck)
        updateModeHint()
        modeGroup.addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (!isChecked) return@addOnButtonCheckedListener
            prefs.mode = if (checkedId == R.id.modePause) InterruptMode.PAUSE else InterruptMode.DUCK
            updateModeHint()
        }

        switchSchedule.isChecked = prefs.scheduleEnabled
        switchSchedule.setOnCheckedChangeListener { _, checked ->
            prefs.scheduleEnabled = checked
            val next = Scheduler.sync(this)
            prefs.appendLog(
                if (next != null) "Sendeplan an, nächster Block ${next.format(Schedule.FMT)}"
                else "Sendeplan aus"
            )
            refresh()
        }

        switchWeekdays.isChecked = prefs.weekdaysOnly
        switchWeekdays.setOnCheckedChangeListener { _, checked ->
            prefs.weekdaysOnly = checked
            Scheduler.sync(this)
            refresh()
        }

        switchOnlyMusic.isChecked = prefs.onlyWhenMusic
        switchOnlyMusic.setOnCheckedChangeListener { _, checked ->
            prefs.onlyWhenMusic = checked
            prefs.appendLog(if (checked) "Blöcke nur bei laufender Musik" else "Blöcke auch ohne Musik")
        }

        switchLiveWeather.isChecked = prefs.liveWeather
        switchLiveWeather.setOnCheckedChangeListener { _, checked ->
            prefs.liveWeather = checked
            prefs.appendLog(if (checked) "Live-Wetter vor jedem Block an" else "Live-Wetter aus")
        }

        findViewById<View>(R.id.btnArticles).setOnClickListener {
            startActivity(Intent(this, ArticlesActivity::class.java))
        }
        findViewById<View>(R.id.btnSync).setOnClickListener {
            if (prefs.baseUrl.isBlank()) {
                Toast.makeText(this, R.string.today_none, Toast.LENGTH_LONG).show()
            } else {
                prefs.appendLog("Sync: manuell gestartet")
                SyncService.start(this)
                Toast.makeText(this, R.string.toast_sync_started, Toast.LENGTH_SHORT).show()
                refresh()
            }
        }

        findViewById<View>(R.id.btnPlayBlockNow).setOnClickListener { playTodayBlockNow() }
        findViewById<View>(R.id.btnSimulation).setOnClickListener {
            if (Simulation.isActive(prefs)) {
                Simulation.stop(this, "manuell beendet")
            } else if (Simulation.start(this) == null) {
                Toast.makeText(this, R.string.toast_no_block, Toast.LENGTH_LONG).show()
            }
            refresh()
        }

        val editUrl = findViewById<EditText>(R.id.editUrl)
        val editUser = findViewById<EditText>(R.id.editUser)
        val editPass = findViewById<EditText>(R.id.editPass)
        editUrl.setText(prefs.baseUrl)
        editUser.setText(prefs.authUser)
        editPass.setText(prefs.authPass)
        findViewById<View>(R.id.btnSaveConnection).setOnClickListener {
            prefs.baseUrl = editUrl.text.toString()
            prefs.authUser = editUser.text.toString()
            prefs.authPass = editPass.text.toString()
            editUrl.setText(prefs.baseUrl)
            Toast.makeText(this, R.string.toast_saved, Toast.LENGTH_SHORT).show()
        }

        findViewById<View>(R.id.btnExactAlarm).setOnClickListener { openExactAlarmSettings() }
        findViewById<View>(R.id.btnBattery).setOnClickListener { openBatterySettings() }
        findViewById<View>(R.id.btnNotify).setOnClickListener { openNotificationSettings() }
        findViewById<View>(R.id.btnAutostart).setOnClickListener { openAutostartSettings() }
        findViewById<View>(R.id.btnClearLog).setOnClickListener {
            prefs.clearLog()
            refresh()
        }

        val versionName = runCatching {
            packageManager.getPackageInfo(packageName, 0).versionName
        }.getOrNull() ?: "?"
        findViewById<TextView>(R.id.versionText).text = getString(R.string.version_fmt, versionName)

        requestNotificationPermission()
    }

    override fun onResume() {
        super.onResume()
        if (prefs.scheduleEnabled) Scheduler.sync(this)
        handler.removeCallbacks(ticker)
        handler.post(ticker)
    }

    override fun onPause() {
        handler.removeCallbacks(ticker)
        super.onPause()
    }

    private fun refresh() {
        val now = ZonedDateTime.now()
        val next = if (prefs.scheduleEnabled) Schedule.nextSlot(now, prefs.weekdaysOnly) else null
        if (next != null) {
            statusLabel.setText(R.string.status_label_next)
            statusTime.text = next.format(Schedule.FMT)
            statusCountdown.text = countdownText(Duration.between(now, next))
        } else {
            statusLabel.setText(R.string.status_label_off)
            statusTime.setText(R.string.status_off_time)
            statusCountdown.setText(R.string.status_off_hint)
        }

        val exactOk = Scheduler.canScheduleExact(this)
        statusWarning.visibility = if (exactOk || next == null) View.GONE else View.VISIBLE

        val pm = getSystemService(PowerManager::class.java)
        setDot(dotExact, exactOk)
        setDot(dotBattery, pm.isIgnoringBatteryOptimizations(packageName))
        setDot(dotNotify, NotificationManagerCompat.from(this).areNotificationsEnabled())
        setDot(dotAutostart, null)

        refreshToday()

        val lines = prefs.log.lines().filter { it.isNotBlank() }.reversed()
        logText.text = if (lines.isEmpty()) getString(R.string.log_empty) else lines.joinToString("\n")
    }

    /** Spielt einen geladenen Block sofort ueber den Overlay-Weg, ohne auf den Slot zu warten. */
    private fun playTodayBlockNow() {
        val lib = Library(this)
        val (date, blocks) = lib.playlist() ?: run {
            Toast.makeText(this, R.string.toast_no_block, Toast.LENGTH_LONG).show()
            return
        }
        val hour = java.time.LocalTime.now().hour
        val slotNow = String.format(java.util.Locale.ROOT, "%02d:00", hour)
        val block = blocks.firstOrNull { it.slot == slotNow && lib.blockFile(date, it) != null }
            ?: blocks.lastOrNull { it.slot <= slotNow && lib.blockFile(date, it) != null }
            ?: blocks.firstOrNull { lib.blockFile(date, it) != null }
        val file = block?.let { lib.blockFile(date, it) }
        if (block == null || file == null) {
            Toast.makeText(this, R.string.toast_no_block, Toast.LENGTH_LONG).show()
            return
        }
        prefs.appendLog("Manuell: Block ${block.slot} vom $date")
        PlaybackService.start(this, "manuell", file.absolutePath)
        refresh()
    }

    private fun refreshToday() {
        val lib = Library(this)
        val playlist = lib.playlist()
        val simButton = findViewById<com.google.android.material.button.MaterialButton>(R.id.btnSimulation)
        val simStatus = findViewById<TextView>(R.id.simStatus)
        val simNext = Simulation.nextTime(this)
        if (simNext != null && playlist != null) {
            simButton.setText(R.string.btn_simulation_stop)
            simStatus.text = getString(R.string.sim_status, prefs.simIndex + 1, playlist.second.size, simNext.format(Schedule.FMT))
            simStatus.visibility = View.VISIBLE
        } else {
            simButton.setText(R.string.btn_simulation_start)
            simStatus.visibility = View.GONE
        }
        val articles = lib.articles()?.second ?: emptyList()
        if (playlist == null) {
            todayText.setText(R.string.today_none)
        } else {
            todayText.text = getString(R.string.today_summary, playlist.first, playlist.second.size, articles.size)
        }
        val status = lib.status()
        val parts = mutableListOf<String>()
        if (status != null) {
            parts += getString(if (status.ok) R.string.today_status_ok else R.string.today_status_fail, status.message)
        }
        if (prefs.lastSync.isNotBlank()) parts += getString(R.string.today_last_sync, prefs.lastSync)
        todayStatus.text = parts.joinToString("\n")
        todayStatus.visibility = if (parts.isEmpty()) View.GONE else View.VISIBLE
    }

    private fun countdownText(d: Duration): String {
        val totalMinutes = d.toMinutes()
        val days = totalMinutes / (24 * 60)
        val hours = (totalMinutes % (24 * 60)) / 60
        val minutes = totalMinutes % 60
        return when {
            days > 0 -> getString(R.string.countdown_days, days, hours)
            hours > 0 -> getString(R.string.countdown_hours, hours, minutes)
            minutes > 0 -> getString(R.string.countdown_minutes, minutes)
            else -> getString(R.string.countdown_soon)
        }
    }

    /** ok = true gruen, false rot, null grau (nicht pruefbar). */
    private fun setDot(dot: View, ok: Boolean?) {
        val color = when (ok) {
            true -> R.color.fox_green
            false -> R.color.fox_red
            null -> R.color.fox_gray
        }
        dot.backgroundTintList = ColorStateList.valueOf(ContextCompat.getColor(this, color))
    }

    private fun updateModeHint() {
        modeHint.setText(
            if (prefs.mode == InterruptMode.PAUSE) R.string.mode_pause_hint else R.string.mode_duck_hint
        )
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
        if (!granted) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    private fun openExactAlarmSettings() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            Toast.makeText(this, R.string.exact_alarm_not_needed, Toast.LENGTH_SHORT).show()
            return
        }
        startSafely(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:$packageName")))
    }

    private fun openBatterySettings() {
        val direct = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))
        if (!startSafely(direct)) startSafely(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
    }

    private fun openNotificationSettings() {
        val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
        if (!startSafely(intent)) openAppDetails()
    }

    private fun openAutostartSettings() {
        val miui = Intent().setComponent(
            ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity")
        )
        if (!startSafely(miui)) {
            Toast.makeText(this, R.string.autostart_not_found, Toast.LENGTH_LONG).show()
            openAppDetails()
        }
    }

    private fun openAppDetails() {
        startSafely(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
    }

    private fun startSafely(intent: Intent): Boolean = try {
        startActivity(intent)
        true
    } catch (e: Exception) {
        false
    }

    companion object {
        private const val TICK_MS = 30_000L
    }
}
