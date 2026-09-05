package de.alchemyfox.foxradio

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import java.time.DayOfWeek
import java.time.LocalTime
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Sendeschema: 07:00 Morning Show, danach stuendlich bis 16:00. */
object Schedule {
    val SLOT_HOURS: List<Int> = (7..16).toList()

    val FMT: DateTimeFormatter = DateTimeFormatter.ofPattern("EEE dd.MM. HH:mm", Locale.GERMAN)

    fun nextSlot(now: ZonedDateTime, weekdaysOnly: Boolean): ZonedDateTime {
        var day = now.toLocalDate()
        repeat(8) {
            val weekend = day.dayOfWeek == DayOfWeek.SATURDAY || day.dayOfWeek == DayOfWeek.SUNDAY
            if (!weekdaysOnly || !weekend) {
                for (hour in SLOT_HOURS) {
                    val candidate = ZonedDateTime.of(day, LocalTime.of(hour, 0), now.zone)
                    if (candidate.isAfter(now)) return candidate
                }
            }
            day = day.plusDays(1)
        }
        return ZonedDateTime.of(day, LocalTime.of(SLOT_HOURS.first(), 0), now.zone)
    }
}

/** Plant die Bloecke ueber den AlarmManager. */
object Scheduler {
    const val EXTRA_SOURCE = "source"
    const val SOURCE_SLOT = "slot"
    const val SOURCE_TEST = "test"

    private const val REQ_SLOT = 1
    private const val REQ_TEST = 2

    fun canScheduleExact(context: Context): Boolean {
        val am = context.getSystemService(AlarmManager::class.java)
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.S || am.canScheduleExactAlarms()
    }

    /**
     * Bringt den AlarmManager auf den Stand der Einstellungen: naechsten Slot planen
     * oder Planung aufheben. Gibt den geplanten Zeitpunkt zurueck, sonst null.
     */
    fun sync(context: Context): ZonedDateTime? {
        val prefs = Prefs(context)
        val am = context.getSystemService(AlarmManager::class.java)
        val pending = slotIntent(context)
        if (!prefs.scheduleEnabled) {
            am.cancel(pending)
            return null
        }
        val next = Schedule.nextSlot(ZonedDateTime.now(), prefs.weekdaysOnly)
        setExact(am, next.toInstant().toEpochMilli(), pending)
        return next
    }

    fun scheduleTest(context: Context, delayMillis: Long) {
        val am = context.getSystemService(AlarmManager::class.java)
        setExact(am, System.currentTimeMillis() + delayMillis, testIntent(context))
    }

    private fun setExact(am: AlarmManager, atMillis: Long, pending: PendingIntent) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && !am.canScheduleExactAlarms()) {
            // Ohne Berechtigung nur ungenau. Besser als gar nichts.
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, atMillis, pending)
        } else {
            am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, atMillis, pending)
        }
    }

    private fun slotIntent(context: Context): PendingIntent = PendingIntent.getBroadcast(
        context,
        REQ_SLOT,
        Intent(context, AlarmReceiver::class.java).putExtra(EXTRA_SOURCE, SOURCE_SLOT),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

    private fun testIntent(context: Context): PendingIntent = PendingIntent.getBroadcast(
        context,
        REQ_TEST,
        Intent(context, AlarmReceiver::class.java).putExtra(EXTRA_SOURCE, SOURCE_TEST),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )
}
