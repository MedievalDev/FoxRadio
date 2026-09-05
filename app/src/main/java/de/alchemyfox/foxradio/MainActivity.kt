package de.alchemyfox.foxradio

import android.Manifest
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.widget.Button
import android.widget.RadioGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import java.time.ZonedDateTime

class MainActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private lateinit var statusText: TextView
    private lateinit var permText: TextView
    private lateinit var logText: TextView
    private lateinit var switchSchedule: SwitchCompat
    private lateinit var switchWeekdays: SwitchCompat

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)

        statusText = findViewById(R.id.statusText)
        permText = findViewById(R.id.permText)
        logText = findViewById(R.id.logText)
        switchSchedule = findViewById(R.id.switchSchedule)
        switchWeekdays = findViewById(R.id.switchWeekdays)

        findViewById<Button>(R.id.btnPlayNow).setOnClickListener {
            prefs.appendLog("Test: sofort")
            PlaybackService.start(this, "manuell")
            refresh()
        }

        findViewById<Button>(R.id.btnPlayIn2Min).setOnClickListener {
            Scheduler.scheduleTest(this, 2 * 60_000L)
            prefs.appendLog("Test in 2 Minuten geplant")
            Toast.makeText(this, "In 2 Minuten. Handy sperren, Musik laufen lassen.", Toast.LENGTH_LONG).show()
            refresh()
        }

        val modeGroup = findViewById<RadioGroup>(R.id.modeGroup)
        modeGroup.check(if (prefs.mode == InterruptMode.PAUSE) R.id.modePause else R.id.modeDuck)
        modeGroup.setOnCheckedChangeListener { _, checkedId ->
            prefs.mode = if (checkedId == R.id.modePause) InterruptMode.PAUSE else InterruptMode.DUCK
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

        findViewById<Button>(R.id.btnExactAlarm).setOnClickListener { openExactAlarmSettings() }
        findViewById<Button>(R.id.btnBattery).setOnClickListener { openBatterySettings() }
        findViewById<Button>(R.id.btnAutostart).setOnClickListener { openAutostartSettings() }
        findViewById<Button>(R.id.btnClearLog).setOnClickListener {
            prefs.clearLog()
            refresh()
        }

        requestNotificationPermission()
    }

    override fun onResume() {
        super.onResume()
        if (prefs.scheduleEnabled) Scheduler.sync(this)
        refresh()
    }

    private fun refresh() {
        val next = if (prefs.scheduleEnabled) {
            Schedule.nextSlot(ZonedDateTime.now(), prefs.weekdaysOnly)
        } else {
            null
        }
        statusText.text = buildString {
            append(
                if (next != null) getString(R.string.status_next_slot, next.format(Schedule.FMT))
                else getString(R.string.status_schedule_off)
            )
            if (!Scheduler.canScheduleExact(this@MainActivity)) {
                append('\n')
                append(getString(R.string.status_no_exact_alarm))
            }
        }

        val pm = getSystemService(PowerManager::class.java)
        permText.text = listOf(
            getString(R.string.perm_line_exact, okOrMissing(Scheduler.canScheduleExact(this))),
            getString(R.string.perm_line_battery, okOrMissing(pm.isIgnoringBatteryOptimizations(packageName))),
            getString(R.string.perm_line_notify, okOrMissing(NotificationManagerCompat.from(this).areNotificationsEnabled()))
        ).joinToString("\n")

        logText.text = prefs.log.lines().filter { it.isNotBlank() }.reversed().joinToString("\n")
    }

    private fun okOrMissing(ok: Boolean): String =
        getString(if (ok) R.string.perm_ok else R.string.perm_missing)

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
            Toast.makeText(this, "Auf dieser Android-Version nicht nötig.", Toast.LENGTH_SHORT).show()
            return
        }
        startSafely(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:$packageName")))
    }

    private fun openBatterySettings() {
        val direct = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))
        if (!startSafely(direct)) startSafely(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
    }

    private fun openAutostartSettings() {
        val miui = Intent().setComponent(
            ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity")
        )
        if (!startSafely(miui)) {
            Toast.makeText(this, R.string.autostart_not_found, Toast.LENGTH_LONG).show()
            startSafely(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        }
    }

    private fun startSafely(intent: Intent): Boolean = try {
        startActivity(intent)
        true
    } catch (e: Exception) {
        false
    }
}
