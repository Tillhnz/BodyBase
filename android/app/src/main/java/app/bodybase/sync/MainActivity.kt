package app.bodybase.sync

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.HealthConnectFeatures
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.Instant

class MainActivity : ComponentActivity() {
    private val setup = mutableStateOf<Pair<String, String>?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        readSetupLink(intent)
        Scheduler.apply(this, Prefs(this).interval, replace = false)
        setContent { BodyBaseTheme { MainScreen(setup) } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        readSetupLink(intent)
    }

    /** bodybase://setup?url=…&key=… aus BodyBase (Quellen → Android Health Connect → „Mit App verbinden“). */
    private fun readSetupLink(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.scheme != "bodybase" || data.host != "setup") return
        val url = data.getQueryParameter("url")
        val key = data.getQueryParameter("key")
        if (!url.isNullOrBlank() && !key.isNullOrBlank()) setup.value = url to key
    }
}

/** Bildschirmzustand; liest und schreibt die Einstellungen. */
class Model(private val ctx: Context) {
    val prefs = Prefs(ctx)
    var url by mutableStateOf(prefs.url)
    var key by mutableStateOf(prefs.key)
    var test by mutableStateOf<Pair<Boolean, String>?>(null)
    var testing by mutableStateOf(false)
    var sdk by mutableIntStateOf(HealthConnectClient.SDK_UNAVAILABLE)
    var granted by mutableStateOf<Set<String>>(emptySet())
    var bgFeature by mutableStateOf(false)
    var historyFeature by mutableStateOf(false)
    var interval by mutableIntStateOf(prefs.interval)
    var lastRun by mutableLongStateOf(0L)
    var lastCounts by mutableStateOf<Map<String, Int>>(emptyMap())
    var lastError by mutableStateOf<String?>(null)
    var total by mutableLongStateOf(0L)

    val configured get() = prefs.url.isNotBlank() && prefs.key.isNotBlank()
    val grantedKinds get() = Kinds.ALL.filter { it.permission in granted }
    val hasBackground get() = HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND in granted
    val hasHistory get() = HealthPermission.PERMISSION_READ_HEALTH_DATA_HISTORY in granted

    suspend fun refresh() {
        sdk = HealthConnectClient.getSdkStatus(ctx)
        if (sdk == HealthConnectClient.SDK_AVAILABLE) {
            val client = HealthConnectClient.getOrCreate(ctx)
            granted = runCatching { client.permissionController.getGrantedPermissions() }.getOrDefault(emptySet())
            bgFeature = runCatching {
                client.features.getFeatureStatus(HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_IN_BACKGROUND) ==
                    HealthConnectFeatures.FEATURE_STATUS_AVAILABLE
            }.getOrDefault(false)
            historyFeature = runCatching {
                client.features.getFeatureStatus(HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_HISTORY) ==
                    HealthConnectFeatures.FEATURE_STATUS_AVAILABLE
            }.getOrDefault(false)
        }
        reload()
    }

    fun reload() {
        lastRun = prefs.lastRun
        lastCounts = prefs.lastCounts
        lastError = prefs.lastError
        total = prefs.total
    }

    fun permissions(): Set<String> = buildSet {
        Kinds.ALL.forEach { add(it.permission) }
        if (bgFeature) add(HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND)
        if (historyFeature) add(HealthPermission.PERMISSION_READ_HEALTH_DATA_HISTORY)
    }

    suspend fun saveAndTest() {
        prefs.url = Api.normalize(url)
        prefs.key = key
        url = prefs.url
        testing = true
        test = withContext(Dispatchers.IO) {
            try {
                true to Api(prefs.url, prefs.key).test()
            } catch (e: SyncError) {
                false to (e.message ?: "Fehler")
            } catch (e: Exception) {
                false to (e.message ?: e.javaClass.simpleName)
            }
        }
        testing = false
    }
}

private val INTERVALS = listOf(0 to "Aus", 15 to "15 Min", 30 to "30 Min", 60 to "1 Std", 180 to "3 Std")

private fun ago(ms: Long): String {
    if (ms <= 0) return "noch nie"
    val min = (System.currentTimeMillis() - ms) / 60_000
    return when {
        min < 1 -> "gerade eben"
        min < 60 -> "vor $min Min"
        min < 60 * 24 -> "vor ${min / 60} Std"
        else -> "vor ${min / 1440} Tagen"
    }
}

private fun fmt(n: Long): String = "%,d".format(n).replace(',', '.')

@Composable
fun MainScreen(setup: MutableState<Pair<String, String>?>) {
    val ctx = LocalContext.current
    val m = remember { Model(ctx.applicationContext) }
    val scope = rememberCoroutineScope()
    val running by Sync.running.collectAsState()
    val progress by Sync.progress.collectAsState()
    val version by Sync.version.collectAsState()
    var showKey by remember { mutableStateOf(false) }
    var confirmBackfill by remember { mutableStateOf(false) }

    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { scope.launch { m.refresh() } }
    LaunchedEffect(version) { m.reload() }
    val permissionLauncher = rememberLauncherForActivityResult(PermissionController.createRequestPermissionResultContract()) {
        scope.launch {
            m.refresh()
            if (m.configured && m.grantedKinds.isNotEmpty() && m.lastRun == 0L) Sync.startNow(ctx)
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(C.Ink)
            .safeDrawingPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        // Kopf
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 8.dp, bottom = 4.dp)) {
            Logo(46.dp)
            Spacer(Modifier.width(12.dp))
            Column {
                Text("BodyBase Sync", fontSize = 26.sp, fontWeight = FontWeight.Bold, color = C.Chalk)
                Text("Health Connect → dein BodyBase", fontSize = 14.sp, color = C.Mute)
            }
        }

        // 1. Server
        Panel("Server", "Adresse und Schlüssel stehen in BodyBase unter Quellen → Android Health Connect.") {
            val fieldColors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = C.Iris, unfocusedBorderColor = C.Line2,
                focusedLabelColor = C.Iris, unfocusedLabelColor = C.Mute, cursorColor = C.Iris,
            )
            OutlinedTextField(
                value = m.url, onValueChange = { m.url = it; m.test = null },
                label = { Text("Adresse") }, placeholder = { Text("https://bodybase.example.de") },
                singleLine = true, colors = fieldColors, shape = RoundedCornerShape(12.dp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = m.key, onValueChange = { m.key = it; m.test = null },
                label = { Text("Schlüssel") }, singleLine = true, colors = fieldColors, shape = RoundedCornerShape(12.dp),
                visualTransformation = if (showKey) VisualTransformation.None else PasswordVisualTransformation(),
                trailingIcon = { TextButton(onClick = { showKey = !showKey }) { Text(if (showKey) "Verbergen" else "Zeigen", color = C.Mute) } },
                modifier = Modifier.fillMaxWidth(),
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                PrimaryButton(if (m.testing) "Prüfe …" else "Speichern & testen", enabled = !m.testing && m.url.isNotBlank() && m.key.isNotBlank()) {
                    scope.launch { m.saveAndTest() }
                }
                if (m.testing) {
                    Spacer(Modifier.width(12.dp))
                    CircularProgressIndicator(Modifier.height(22.dp).width(22.dp), color = C.Iris, strokeWidth = 2.dp)
                }
            }
            m.test?.let { (ok, text) -> StatusLine(ok, text) }
        }

        // 2. Health Connect
        Panel("Health Connect", "Welche Daten BodyBase bekommen darf.") {
            when (m.sdk) {
                HealthConnectClient.SDK_AVAILABLE -> {
                    val kinds = m.grantedKinds
                    if (kinds.isEmpty()) StatusLine(null, "Noch kein Zugriff erlaubt. Tippe auf „Zugriff erlauben“ und wähle „Alle zulassen“.")
                    else StatusLine(true, "${kinds.size} von ${Kinds.ALL.size} Datenarten freigegeben.")
                    Group.entries.forEach { g ->
                        val list = Kinds.ALL.filter { it.group == g }
                        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(g.label.uppercase(), fontSize = 11.sp, letterSpacing = 1.sp, color = C.Mute, fontWeight = FontWeight.SemiBold)
                            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                list.forEach { k -> Chip(k.label, g.color, k.permission in m.granted) }
                            }
                        }
                    }
                    if (kinds.isNotEmpty() && m.bgFeature && !m.hasBackground) {
                        StatusLine(null, "„Im Hintergrund lesen“ ist nicht erlaubt. Ohne das klappt der automatische Abgleich nur, solange die App offen ist.")
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        PrimaryButton(if (kinds.isEmpty()) "Zugriff erlauben" else "Zugriff ändern") { permissionLauncher.launch(m.permissions()) }
                    }
                }
                HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> {
                    StatusLine(false, "Health Connect muss installiert oder aktualisiert werden.")
                    PrimaryButton("Im Play Store öffnen") {
                        val uri = Uri.parse("market://details?id=com.google.android.apps.healthdata&url=healthconnect%3A%2F%2Fonboarding")
                        runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, uri).setPackage("com.android.vending")) }
                    }
                }
                else -> StatusLine(false, "Health Connect gibt es auf diesem Gerät nicht.")
            }
        }

        // 3. Abgleich
        Panel("Abgleich", "Neue Werte gehen automatisch an BodyBase. Doppelt gesendete Werte ersetzen einfach die alten.") {
            Text("Automatisch", fontSize = 13.sp, color = C.Mute)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                INTERVALS.forEach { (min, label) ->
                    val on = m.interval == min
                    TextButton(
                        onClick = { m.interval = min; m.prefs.interval = min; Scheduler.apply(ctx, min) },
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier
                            .weight(1f)
                            .background(if (on) C.Iris.copy(alpha = 0.16f) else C.Panel2, RoundedCornerShape(10.dp)),
                    ) { Text(label, fontSize = 12.sp, color = if (on) C.Iris else C.Mute, maxLines = 1) }
                }
            }
            if (running) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.height(22.dp).width(22.dp), color = C.Iris, strokeWidth = 2.dp)
                    Spacer(Modifier.width(12.dp))
                    Text(progress.ifBlank { "Starte …" }, color = C.Chalk, fontSize = 14.sp)
                }
            } else {
                PrimaryButton("Jetzt abgleichen", enabled = m.configured && m.grantedKinds.isNotEmpty(), modifier = Modifier.fillMaxWidth()) {
                    Sync.startNow(ctx)
                }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column {
                    Text("Zuletzt", fontSize = 12.sp, color = C.Mute)
                    Text(ago(m.lastRun), fontSize = 16.sp, color = C.Chalk, fontWeight = FontWeight.SemiBold)
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text("Werte gesendet", fontSize = 12.sp, color = C.Mute)
                    Text(fmt(m.total), fontSize = 16.sp, color = C.Chalk, fontWeight = FontWeight.SemiBold)
                }
            }
            m.lastError?.let { StatusLine(false, it) }
            val counts = m.lastCounts.filterValues { it > 0 }
            if (counts.isNotEmpty()) {
                Text("Beim letzten Abgleich", fontSize = 13.sp, color = C.Mute)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    counts.forEach { (key, n) ->
                        val k = Kinds.byKey(key) ?: return@forEach
                        Chip("${k.label} ${fmt(n.toLong())}", k.group.color, true)
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                GhostButton("Verlauf erneut senden", enabled = !running && m.configured) { confirmBackfill = true }
            }
        }

        Text(
            "Version ${BuildConfig.VERSION_NAME} · Die Daten gehen nur an die eingetragene Adresse.",
            fontSize = 12.sp, color = C.Mute, modifier = Modifier.padding(bottom = 16.dp),
        )
    }

    // Einrichtung per Link: erst bestätigen, damit keine fremde Seite die Daten umleiten kann
    setup.value?.let { (url, key) ->
        AlertDialog(
            onDismissRequest = { setup.value = null },
            containerColor = C.Panel,
            title = { Text("Mit BodyBase verbinden?") },
            text = { Text("Adresse:\n${Api.normalize(url)}\n\nNur bestätigen, wenn das dein eigener BodyBase-Server ist.") },
            confirmButton = {
                TextButton(onClick = {
                    setup.value = null
                    m.url = url
                    m.key = key
                    scope.launch {
                        m.saveAndTest()
                        if (m.test?.first == true && m.grantedKinds.isEmpty() && m.sdk == HealthConnectClient.SDK_AVAILABLE) {
                            permissionLauncher.launch(m.permissions())
                        }
                    }
                }) { Text("Verbinden") }
            },
            dismissButton = { TextButton(onClick = { setup.value = null }) { Text("Abbrechen", color = C.Mute) } },
        )
    }

    if (confirmBackfill) {
        val days = if (m.hasHistory) 365L else 30L
        AlertDialog(
            onDismissRequest = { confirmBackfill = false },
            containerColor = C.Panel,
            title = { Text("Verlauf erneut senden?") },
            text = {
                Text(
                    "Schickt die letzten $days Tage noch einmal an BodyBase. Vorhandene Werte werden ersetzt, nichts doppelt." +
                        if (!m.hasHistory) "\n\nÄlter als 30 Tage geht nur mit der Freigabe „Vergangene Daten lesen“." else ""
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    confirmBackfill = false
                    m.prefs.resetCursors(Instant.now().minus(Duration.ofDays(days)))
                    Sync.startNow(ctx)
                }) { Text("Senden") }
            },
            dismissButton = { TextButton(onClick = { confirmBackfill = false }) { Text("Abbrechen", color = C.Mute) } },
        )
    }
}
