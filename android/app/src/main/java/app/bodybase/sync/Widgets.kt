package app.bodybase.sync

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.widget.RemoteViews
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Startbildschirm-Widgets: „BodyBase heute“ (4×2) und „Bereitschaft“ (2×2).
 * Die Daten holt ein kleiner Hintergrund-Auftrag (Netzwerk ist im Widget selbst nicht erlaubt) und legt sie ab;
 * gezeichnet wird immer aus dem abgelegten Stand, damit das Widget auch offline etwas zeigt.
 */
object Widgets {
    private const val CACHE = "widget_json"
    private const val CACHE_AT = "widget_at"
    const val ACTION_REFRESH = "app.bodybase.sync.WIDGET_REFRESH"

    fun requestUpdate(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<WidgetWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(ctx.applicationContext).enqueueUniqueWork("bodybase-widget", ExistingWorkPolicy.REPLACE, req)
    }

    fun store(ctx: Context, json: JSONObject) {
        ctx.getSharedPreferences("bodybase", Context.MODE_PRIVATE).edit()
            .putString(CACHE, json.toString()).putLong(CACHE_AT, System.currentTimeMillis()).apply()
    }

    private fun cached(ctx: Context): Pair<JSONObject?, Long> {
        val sp = ctx.getSharedPreferences("bodybase", Context.MODE_PRIVATE)
        val j = sp.getString(CACHE, null)?.let { runCatching { JSONObject(it) }.getOrNull() }
        return j to sp.getLong(CACHE_AT, 0L)
    }

    fun renderAll(ctx: Context) {
        val mgr = AppWidgetManager.getInstance(ctx)
        val (data, at) = cached(ctx)
        mgr.getAppWidgetIds(ComponentName(ctx, TodayWidget::class.java)).forEach { mgr.updateAppWidget(it, today(ctx, data, at)) }
        mgr.getAppWidgetIds(ComponentName(ctx, SmallWidget::class.java)).forEach { mgr.updateAppWidget(it, small(ctx, data)) }
    }

    /** Farbe wie in BodyBase: grün ab 67, gelb ab 34, sonst rot. */
    private fun scoreColor(v: Int?): Int = when {
        v == null -> Color.WHITE
        v >= 67 -> Color.parseColor("#4ADE80")
        v >= 34 -> Color.parseColor("#FBBF24")
        else -> Color.parseColor("#F87171")
    }

    private fun JSONObject?.score(key: String): Int? =
        this?.optJSONObject(key)?.let { o -> if (o.isNull("value")) null else o.optDouble("value").takeIf { !it.isNaN() }?.toInt() }

    private fun openApp(ctx: Context): PendingIntent {
        val base = Prefs(ctx).url.substringBefore("/api/").ifBlank { null }
        val intent = if (base != null) Intent(Intent.ACTION_VIEW, Uri.parse(base)) else Intent(ctx, MainActivity::class.java)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return PendingIntent.getActivity(ctx, 1, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    private fun openHabits(ctx: Context): PendingIntent {
        val base = Prefs(ctx).url.substringBefore("/api/")
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse("$base/habits")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return PendingIntent.getActivity(ctx, 2, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    private fun refresh(ctx: Context): PendingIntent {
        val intent = Intent(ctx, TodayWidget::class.java).setAction(ACTION_REFRESH)
        return PendingIntent.getBroadcast(ctx, 3, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    private fun minutes(m: Int): String = "${m / 60}:${"%02d".format(m % 60)} h"

    fun today(ctx: Context, d: JSONObject?, at: Long): RemoteViews {
        val v = RemoteViews(ctx.packageName, R.layout.widget_today)
        v.setOnClickPendingIntent(R.id.root, openApp(ctx))
        v.setOnClickPendingIntent(R.id.refresh, refresh(ctx))
        if (d == null) {
            v.setTextViewText(R.id.habits, if (Prefs(ctx).url.isBlank()) "In der App Adresse und Schlüssel eintragen" else "Wird geladen …")
            return v
        }
        val r = d.score("readiness")
        val s = d.score("sleep")
        val l = d.score("load")
        v.setTextViewText(R.id.readiness_value, r?.toString() ?: "–")
        v.setTextColor(R.id.readiness_value, scoreColor(r))
        v.setTextViewText(R.id.sleep_value, s?.toString() ?: "–")
        v.setTextColor(R.id.sleep_value, scoreColor(s))
        v.setTextViewText(R.id.load_value, l?.toString() ?: "–")
        val target = d.optJSONObject("load")?.optJSONArray("target")
        v.setTextViewText(R.id.load_sub, if (target != null && target.length() == 2) "Ziel ${target.optInt(0)}–${target.optInt(1)}" else "")
        v.setTextViewText(R.id.readiness_sub, if (d.optJSONObject("readiness")?.optString("day") != d.optString("day")) "von gestern" else "")
        val need = d.optInt("sleep_need", 0)
        v.setTextViewText(R.id.sleep_sub, if (need > 0) "heute ${minutes(need)}" else "")
        val steps = d.optInt("steps", 0)
        val goal = d.optInt("steps_goal", 8000).coerceAtLeast(1)
        v.setTextViewText(R.id.steps, "${"%,d".format(Locale.GERMANY, steps)} Schritte")
        v.setProgressBar(R.id.steps_bar, 100, (steps * 100 / goal).coerceIn(0, 100), false)
        val open = d.optInt("habits_open_count", 0)
        val names = d.optJSONArray("habits_open")
        val list = (0 until (names?.length() ?: 0)).joinToString(", ") { names!!.optString(it) }
        v.setTextViewText(R.id.habits, if (open == 0) "✓ Alle Gewohnheiten erledigt" else "○ $open offen: $list")
        v.setOnClickPendingIntent(R.id.habits, openHabits(ctx))
        v.setTextViewText(R.id.updated, if (at > 0) SimpleDateFormat("HH:mm", Locale.GERMANY).format(Date(at)) else "")
        return v
    }

    fun small(ctx: Context, d: JSONObject?): RemoteViews {
        val v = RemoteViews(ctx.packageName, R.layout.widget_small)
        v.setOnClickPendingIntent(R.id.root, openApp(ctx))
        val r = d.score("readiness")
        v.setTextViewText(R.id.readiness_value, r?.toString() ?: "–")
        v.setTextColor(R.id.readiness_value, scoreColor(r))
        val s = d.score("sleep")
        val l = d.score("load")
        v.setTextViewText(R.id.small_sub, if (d == null) "Wird geladen …" else "Schlaf ${s ?: "–"} · Last ${l ?: "–"}")
        return v
    }
}

class WidgetWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val prefs = Prefs(applicationContext)
        if (prefs.url.isBlank() || prefs.key.isBlank()) {
            Widgets.renderAll(applicationContext)
            return Result.success()
        }
        return try {
            Widgets.store(applicationContext, Api(prefs.url, prefs.key).widget())
            Widgets.renderAll(applicationContext)
            Result.success()
        } catch (e: Exception) {
            Widgets.renderAll(applicationContext) // alter Stand bleibt sichtbar
            if (runAttemptCount < 2) Result.retry() else Result.failure()
        }
    }
}

open class BaseWidget : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) {
        Widgets.renderAll(ctx)
        Widgets.requestUpdate(ctx)
    }

    override fun onReceive(ctx: Context, intent: Intent) {
        super.onReceive(ctx, intent)
        if (intent.action == Widgets.ACTION_REFRESH) {
            Widgets.requestUpdate(ctx)
            Sync.startNow(ctx) // gleich auch die neuesten Daten vom Handy schicken
        }
    }
}

class TodayWidget : BaseWidget()

class SmallWidget : BaseWidget()
