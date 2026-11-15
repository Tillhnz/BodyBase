package app.bodybase.sync

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.os.Process
import org.json.JSONObject
import java.time.Duration
import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.TreeMap

/**
 * Bildschirmzeit aus der Android-Nutzungsstatistik: Zeit, in der der Bildschirm an war, je Stunde.
 * Braucht die Sonderfreigabe „Zugriff auf Nutzungsdaten“ (Einstellungen), keine Health-Connect-Berechtigung.
 */
object ScreenTime {
    const val KEY = "screen_time"

    fun granted(ctx: Context): Boolean {
        val ops = ctx.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName)
        return mode == AppOpsManager.MODE_ALLOWED
    }

    /** Minuten mit eingeschaltetem Bildschirm je Stunde zwischen from und to. */
    fun hourly(ctx: Context, from: Instant, to: Instant): List<JSONObject> {
        val usm = ctx.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val start = from.truncatedTo(ChronoUnit.HOURS)
        // etwas früher anfangen, um zu wissen, ob der Bildschirm am Anfang schon an war
        val events = usm.queryEvents(start.minus(Duration.ofHours(6)).toEpochMilli(), to.toEpochMilli())
        val perHour = TreeMap<Instant, Double>()
        var onSince: Instant? = null
        val e = UsageEvents.Event()

        fun add(a: Instant, b: Instant) {
            var x = maxOf(a, start)
            val end = minOf(b, to)
            while (x.isBefore(end)) {
                val h = x.truncatedTo(ChronoUnit.HOURS)
                val next = minOf(h.plus(Duration.ofHours(1)), end)
                perHour.merge(h, Duration.between(x, next).toMillis() / 60000.0, Double::plus)
                x = next
            }
        }

        while (events.hasNextEvent()) {
            events.getNextEvent(e)
            val t = Instant.ofEpochMilli(e.timeStamp)
            when (e.eventType) {
                UsageEvents.Event.SCREEN_INTERACTIVE -> if (onSince == null) onSince = t
                UsageEvents.Event.SCREEN_NON_INTERACTIVE -> {
                    onSince?.let { if (Duration.between(it, t) < Duration.ofHours(12)) add(it, t) }
                    onSince = null
                }
            }
        }
        onSince?.let { add(it, to) } // Bildschirm ist gerade an
        // Nur abgeschlossene Stunden (und die laufende) senden; leere Stunden mit 0, damit alte Werte ersetzt werden
        val out = ArrayList<JSONObject>()
        var h = start
        while (h.isBefore(to)) {
            val v = perHour[h] ?: 0.0
            out += JSONObject().put("start_time", h.toString()).put("end_time", h.plus(Duration.ofHours(1)).toString())
                .put("minutes", Math.round(minOf(60.0, v) * 10.0) / 10.0)
            h = h.plus(Duration.ofHours(1))
        }
        return out
    }
}
