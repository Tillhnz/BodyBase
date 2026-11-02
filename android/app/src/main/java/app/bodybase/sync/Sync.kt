package app.bodybase.sync

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.concurrent.TimeUnit

class SyncError(message: String, val retry: Boolean) : Exception(message)

/** Verbindung zu BodyBase: POST zum Senden, GET als Verbindungstest. */
class Api(base: String, private val key: String) {
    val endpoint = normalize(base)

    companion object {
        fun normalize(input: String): String {
            var s = input.trim().trimEnd('/')
            if (s.isEmpty()) return s
            if (!s.startsWith("http://") && !s.startsWith("https://")) s = "https://$s"
            if (!s.contains("/api/ingest/")) s = "$s/api/ingest/health-connect"
            return s
        }
    }

    private class Res(val code: Int, val body: String)

    private fun call(method: String, json: String?): Res {
        if (endpoint.isEmpty()) throw SyncError("Bitte die Adresse deines BodyBase eintragen.", retry = false)
        val conn = try {
            URL(endpoint).openConnection() as HttpURLConnection
        } catch (e: Exception) {
            throw SyncError("Ungültige Adresse: $endpoint", retry = false)
        }
        try {
            conn.requestMethod = method
            conn.connectTimeout = 15_000
            conn.readTimeout = 90_000
            conn.setRequestProperty("X-API-Key", key)
            conn.setRequestProperty("Accept", "application/json")
            conn.setRequestProperty("User-Agent", "BodyBaseSync/${BuildConfig.VERSION_NAME}")
            if (json != null) {
                val bytes = json.toByteArray(Charsets.UTF_8)
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                conn.setFixedLengthStreamingMode(bytes.size)
                conn.outputStream.use { it.write(bytes) }
            }
            val code = conn.responseCode
            val stream = if (code < 400) conn.inputStream else conn.errorStream
            val body = stream?.bufferedReader()?.use { it.readText() } ?: ""
            return Res(code, body)
        } catch (e: IOException) {
            throw SyncError("Server nicht erreichbar (${e.message ?: e.javaClass.simpleName}).", retry = true)
        } finally {
            conn.disconnect()
        }
    }

    private fun problem(r: Res): SyncError {
        val detail = runCatching { JSONObject(r.body).optString("detail") }.getOrNull()?.takeIf { it.isNotBlank() }
        val text = when (r.code) {
            401, 403 -> "Schlüssel abgelehnt. Bitte den Schlüssel aus BodyBase (Quellen → Android Health Connect) eintragen."
            404 -> "Adresse nicht gefunden (HTTP 404). Stimmt die Adresse?"
            405 -> "Dein BodyBase ist zu alt. Bitte auf dem Server „bodybase update“ ausführen."
            413 -> "Daten zu groß für den Proxy vor BodyBase (HTTP 413)."
            in 500..599 -> "BodyBase hat einen Fehler gemeldet (HTTP ${r.code})${detail?.let { ": $it" } ?: "."}"
            else -> "HTTP ${r.code}${detail?.let { ": $it" } ?: ""}"
        }
        return SyncError(text, retry = r.code >= 500 || r.code == 408 || r.code == 429)
    }

    /** Verbindungstest; liefert eine Erfolgsmeldung oder wirft SyncError. */
    fun test(): String {
        val r = call("GET", null)
        if (r.code !in 200..299) throw problem(r)
        val account = runCatching { JSONObject(r.body).optString("account") }.getOrNull()
        return if (!account.isNullOrBlank()) "Verbunden mit dem Konto $account" else "Verbindung steht"
    }

    fun send(kind: String, items: List<JSONObject>) {
        val body = JSONObject()
            .put("timestamp", Instant.now().toString())
            .put("app_version", BuildConfig.VERSION_NAME)
            .put("app", "BodyBase Sync")
            .put("timezone", ZoneId.systemDefault().id)
            .put(kind, JSONArray(items))
        val r = call("POST", body.toString())
        if (r.code !in 200..299) throw problem(r)
    }
}

/** Gemeinsamer Zustand für Oberfläche und Hintergrund-Abgleich. */
object Sync {
    val running = MutableStateFlow(false)
    val progress = MutableStateFlow("")
    val version = MutableStateFlow(0)
    val mutex = Mutex()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val WINDOW: Duration = Duration.ofDays(7)
    private const val CHUNK = 1500
    private val DAY = DateTimeFormatter.ofPattern("d. MMM", Locale.GERMAN).withZone(ZoneId.systemDefault())

    fun startNow(ctx: Context) {
        if (running.value) return
        val app = ctx.applicationContext
        scope.launch { runCatching { run(app, background = false) } }
    }

    /**
     * Liest je Datenart alles seit dem letzten erfolgreichen Abgleich (minus Überlappung) in Wochenfenstern und
     * schickt es in Paketen. Nach jedem Fenster wird der Stand gespeichert: Ein abgebrochener Lauf macht dort weiter.
     */
    suspend fun run(ctx: Context, background: Boolean): Unit = mutex.withLock {
        running.value = true
        val prefs = Prefs(ctx)
        prefs.lastAttempt = System.currentTimeMillis()
        val counts = linkedMapOf<String, Int>()
        val problems = mutableListOf<String>()
        try {
            if (prefs.url.isBlank() || prefs.key.isBlank()) throw SyncError("Adresse und Schlüssel fehlen.", retry = false)
            if (HealthConnectClient.getSdkStatus(ctx) != HealthConnectClient.SDK_AVAILABLE) {
                throw SyncError("Health Connect ist auf diesem Gerät nicht verfügbar.", retry = false)
            }
            val client = HealthConnectClient.getOrCreate(ctx)
            val granted = client.permissionController.getGrantedPermissions()
            val kinds = Kinds.ALL.filter { it.permission in granted }
            if (kinds.isEmpty()) throw SyncError("Noch kein Zugriff auf Health Connect erlaubt.", retry = false)
            val api = Api(prefs.url, prefs.key)
            val now = Instant.now()
            for (kind in kinds) {
                var from = prefs.cursor(kind.key)?.minus(kind.overlap) ?: now.minus(Duration.ofDays(30))
                var sent = 0
                while (from < now) {
                    val to = minOf(from.plus(WINDOW), now)
                    progress.value = "${kind.label} · ab ${DAY.format(from)}"
                    val items = try {
                        kind.read(client, from, to)
                    } catch (e: SecurityException) {
                        problems += "${kind.label}: kein Zugriff" + if (background) " im Hintergrund" else ""
                        null
                    } catch (e: Exception) {
                        problems += "${kind.label}: ${e.message ?: e.javaClass.simpleName}"
                        null
                    } ?: break
                    for (part in items.chunked(CHUNK)) api.send(kind.key, part)
                    sent += items.size
                    prefs.setCursor(kind.key, to)
                    from = to
                }
                counts[kind.key] = sent
            }
            prefs.lastRun = System.currentTimeMillis()
            prefs.lastCounts = counts
            prefs.total = prefs.total + counts.values.sum()
            prefs.lastError = problems.joinToString("\n").ifBlank { null }
        } catch (e: SyncError) {
            prefs.lastError = e.message
            throw e
        } catch (e: Exception) {
            prefs.lastError = e.message ?: e.javaClass.simpleName
            throw SyncError(prefs.lastError ?: "Fehler", retry = true)
        } finally {
            running.value = false
            progress.value = ""
            version.value = version.value + 1
        }
        Unit
    }
}

class SyncWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result = try {
        Sync.run(applicationContext, background = true)
        Result.success()
    } catch (e: SyncError) {
        if (e.retry && runAttemptCount < 3) Result.retry() else Result.failure()
    } catch (e: Exception) {
        Result.failure()
    }
}

object Scheduler {
    private const val NAME = "bodybase-sync"

    fun apply(ctx: Context, minutes: Int, replace: Boolean = true) {
        val wm = WorkManager.getInstance(ctx.applicationContext)
        if (minutes <= 0) {
            wm.cancelUniqueWork(NAME)
            return
        }
        val req = PeriodicWorkRequestBuilder<SyncWorker>(minutes.toLong().coerceAtLeast(15), TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 5, TimeUnit.MINUTES)
            .build()
        wm.enqueueUniquePeriodicWork(NAME, if (replace) ExistingPeriodicWorkPolicy.UPDATE else ExistingPeriodicWorkPolicy.KEEP, req)
    }
}
