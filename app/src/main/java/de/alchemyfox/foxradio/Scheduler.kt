package de.alchemyfox.foxradio

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.os.Build
import java.time.Instant
import java.time.ZoneId
import java.time.DayOfWeek
import java.time.LocalTime
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Sendeschema. Die Sendezeiten kommen aus der geladenen Playlist (der PC legt
 * sie fest, z. B. 07:00, 07:30, 08:00, 08:30, 08:55 ...). Ohne Playlist gilt
 * der alte Standard: volle Stunden 07:00 bis 16:00.
 */
object Schedule {
    val DEFAULT_TIMES: List<LocalTime> = (7..16).map { LocalTime.of(it, 0) }

    val FMT: DateTimeFormatter = DateTimeFormatter.ofPattern("EEE dd.MM. HH:mm", Locale.GERMAN)

    /** Sendezeiten aus der Playlist, sortiert und ohne Doppelte, sonst Standard. */
    fun slotTimes(context: Context): List<LocalTime> {
        val blocks = Library(context).playlist()?.second ?: return DEFAULT_TIMES
        val times = blocks.mapNotNull { parseSlot(it.slot) }.distinct().sorted()
        return if (times.isEmpty()) DEFAULT_TIMES else times
    }

    fun parseSlot(slot: String): LocalTime? = runCatching { LocalTime.parse(slot.trim()) }.getOrNull()

    fun nextSlot(now: ZonedDateTime, weekdaysOnly: Boolean, times: List<LocalTime> = DEFAULT_TIMES): ZonedDateTime {
        var day = now.toLocalDate()
        repeat(8) {
            val weekend = day.dayOfWeek == DayOfWeek.SATURDAY || day.dayOfWeek == DayOfWeek.SUNDAY
            if (!weekdaysOnly || !weekend) {
                for (time in times) {
                    val candidate = ZonedDateTime.of(day, time, now.zone)
                    if (candidate.isAfter(now)) return candidate
                }
            }
            day = day.plusDays(1)
        }
        return ZonedDateTime.of(day, times.first(), now.zone)
    }
}

/** Plant die Bloecke ueber den AlarmManager. */
object Scheduler {
    const val EXTRA_SOURCE = "source"
    const val SOURCE_SLOT = "slot"
    const val SOURCE_TEST = "test"
    const val SOURCE_SYNC = "sync"
    const val SOURCE_SIM = "sim"

    private const val REQ_SLOT = 1
    private const val REQ_TEST = 2
    private const val REQ_SYNC = 3
    private const val REQ_SIM = 4

    /** Tagesdateien werden vor dem ersten Block geholt. */
    private val SYNC_TIME: LocalTime = LocalTime.of(6, 45)

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
        val syncPending = syncIntent(context)
        if (!prefs.scheduleEnabled) {
            am.cancel(pending)
            am.cancel(syncPending)
            return null
        }
        val now = ZonedDateTime.now()
        val next = Schedule.nextSlot(now, prefs.weekdaysOnly, Schedule.slotTimes(context))
        setExact(am, next.toInstant().toEpochMilli(), pending)
        var sync = ZonedDateTime.of(next.toLocalDate(), SYNC_TIME, now.zone)
        if (!sync.isAfter(now)) sync = ZonedDateTime.of(now.toLocalDate().plusDays(1), SYNC_TIME, now.zone)
        setExact(am, sync.toInstant().toEpochMilli(), syncPending)
        return next
    }

    fun scheduleTest(context: Context, delayMillis: Long) {
        val am = context.getSystemService(AlarmManager::class.java)
        setExact(am, System.currentTimeMillis() + delayMillis, testIntent(context))
    }

    fun setExactAt(context: Context, atMillis: Long, pending: PendingIntent) =
        setExact(context.getSystemService(AlarmManager::class.java), atMillis, pending)

    fun simIntent(context: Context): PendingIntent = PendingIntent.getBroadcast(
        context,
        REQ_SIM,
        Intent(context, AlarmReceiver::class.java).putExtra(EXTRA_SOURCE, SOURCE_SIM),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

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

    private fun syncIntent(context: Context): PendingIntent = PendingIntent.getBroadcast(
        context,
        REQ_SYNC,
        Intent(context, AlarmReceiver::class.java).putExtra(EXTRA_SOURCE, SOURCE_SYNC),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

    private fun testIntent(context: Context): PendingIntent = PendingIntent.getBroadcast(
        context,
        REQ_TEST,
        Intent(context, AlarmReceiver::class.java).putExtra(EXTRA_SOURCE, SOURCE_TEST),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )
}


/**
 * Simulation: Beim Start spielt sofort der erste Block der geladenen Playlist
 * (so als waere es 07:00), danach jede Stunde der naechste, bis die Playlist
 * durch ist oder der naechste Termin nach 20:00 laege. Danach wieder normal.
 * Waehrend der Simulation werden regulaere Slot-Wecker uebersprungen.
 */
object Simulation {
    private val LAST: LocalTime = LocalTime.of(20, 0)

    fun isActive(prefs: Prefs): Boolean = prefs.simStart > 0L

    /** Liefert den Tag der Playlist oder null, wenn nichts geladen ist. */
    fun start(context: Context): String? {
        val prefs = Prefs(context)
        val lib = Library(context)
        val (date, blocks) = lib.playlist() ?: return null
        if (blocks.isEmpty()) return null
        prefs.simStart = System.currentTimeMillis()
        prefs.simIndex = 0
        prefs.appendLog("Simulation gestartet: ${blocks.size} Blöcke vom $date, ab jetzt stündlich")
        playIndex(context, prefs, lib, date, blocks, 0, checkMusic = false)
        scheduleNext(context, prefs, blocks.size)
        return date
    }

    fun stop(context: Context, reason: String) {
        val prefs = Prefs(context)
        context.getSystemService(AlarmManager::class.java).cancel(Scheduler.simIntent(context))
        prefs.simStart = 0L
        prefs.simIndex = 0
        prefs.appendLog("Simulation beendet: $reason")
        Scheduler.sync(context)
    }

    /** Zeitpunkt des naechsten Simulationsblocks, null wenn keine Simulation laeuft. */
    fun nextTime(context: Context): ZonedDateTime? {
        val prefs = Prefs(context)
        if (!isActive(prefs)) return null
        return Instant.ofEpochMilli(prefs.simStart).atZone(ZoneId.systemDefault()).plusHours(prefs.simIndex.toLong())
    }

    /** Vom Wecker aufgerufen. */
    fun onAlarm(context: Context) {
        val prefs = Prefs(context)
        if (!isActive(prefs)) return
        val lib = Library(context)
        val (date, blocks) = lib.playlist() ?: run {
            stop(context, "keine Playlist mehr")
            return
        }
        val idx = prefs.simIndex
        if (idx >= blocks.size) {
            stop(context, "alle Blöcke gespielt")
            return
        }
        playIndex(context, prefs, lib, date, blocks, idx, checkMusic = prefs.onlyWhenMusic)
        scheduleNext(context, prefs, blocks.size)
    }

    private fun playIndex(context: Context, prefs: Prefs, lib: Library, date: String, blocks: List<Block>, idx: Int, checkMusic: Boolean) {
        val block = blocks[idx]
        prefs.simIndex = idx + 1
        val file = lib.blockFile(date, block)
        if (file == null) {
            prefs.appendLog("Simulation: Block ${block.slot} nicht vorgeladen, übersprungen")
            return
        }
        if (checkMusic && !context.getSystemService(AudioManager::class.java).isMusicActive) {
            prefs.appendLog("Simulation: keine Musik aktiv, Block ${block.slot} übersprungen")
            return
        }
        prefs.appendLog("Simulation: Block ${block.slot} (${idx + 1}/${blocks.size})")
        PlaybackService.start(context, "simulation", file.absolutePath)
    }

    private fun scheduleNext(context: Context, prefs: Prefs, total: Int) {
        if (prefs.simIndex >= total) {
            stop(context, "alle Blöcke gespielt")
            return
        }
        val next = nextTime(context) ?: return
        val now = ZonedDateTime.now()
        if (next.toLocalDate() != now.toLocalDate() || next.toLocalTime().isAfter(LAST)) {
            stop(context, "20 Uhr erreicht")
            return
        }
        Scheduler.setExactAt(context, next.toInstant().toEpochMilli(), Scheduler.simIntent(context))
        prefs.appendLog("Simulation: nächster Block ${next.format(Schedule.FMT)}")
    }
}
