package app.bodybase.sync

import androidx.compose.ui.graphics.Color
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.aggregate.AggregateMetric
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ActiveCaloriesBurnedRecord
import androidx.health.connect.client.records.BloodGlucoseRecord
import androidx.health.connect.client.records.BloodPressureRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.BodyTemperatureRecord
import androidx.health.connect.client.records.BoneMassRecord
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeartRateVariabilityRmssdRecord
import androidx.health.connect.client.records.HydrationRecord
import androidx.health.connect.client.records.IntervalRecord
import androidx.health.connect.client.records.LeanBodyMassRecord
import androidx.health.connect.client.records.NutritionRecord
import androidx.health.connect.client.records.OxygenSaturationRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.RespiratoryRateRecord
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.Vo2MaxRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.request.AggregateGroupByDurationRequest
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import org.json.JSONArray
import org.json.JSONObject
import java.time.Duration
import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.TreeMap
import kotlin.reflect.KClass

/**
 * Eine Datenart aus Health Connect und wie sie für BodyBase (/api/ingest/health-connect) aufbereitet wird.
 * key = Feldname im JSON, overlap = wie weit jeder Abgleich zurückschaut (Uhren und Waagen liefern oft verspätet nach).
 */
class Kind(
    val key: String,
    val label: String,
    val group: Group,
    val type: KClass<out Record>,
    val overlap: Duration,
    /** true: Stundensummen über Health Connect statt Rohdaten (Handy und Uhr zählen sonst doppelt) */
    val aggregated: Boolean = false,
    val read: suspend (HealthConnectClient, Instant, Instant) -> List<JSONObject>,
) {
    val permission: String get() = HealthPermission.getReadPermission(type)
}

enum class Group(val label: String, val color: Color) {
    ACTIVITY("Aktivität", Color(0xFFF5A524)),
    HEART("Herz", Color(0xFFFF6B81)),
    SLEEP("Schlaf", Color(0xFF8B7CFF)),
    BODY("Körper", Color(0xFF4CC9F0)),
    VITALS("Vitalwerte", Color(0xFF5EE2A0)),
    NUTRITION("Ernährung", Color(0xFFF2D15B)),
}

private fun at(t: Instant) = JSONObject().put("time", t.toString())
private fun span(a: Instant, b: Instant) = JSONObject().put("start_time", a.toString()).put("end_time", b.toString())
private fun JSONObject.maybe(k: String, v: Double?): JSONObject = apply { if (v != null && !v.isNaN()) put(k, v) }
private fun round1(v: Double) = Math.round(v * 10.0) / 10.0

/** Alle Einträge im Zeitraum, seitenweise gelesen. */
suspend inline fun <reified T : Record> HealthConnectClient.all(from: Instant, to: Instant): List<T> {
    val out = ArrayList<T>()
    var token: String? = null
    do {
        val res = readRecords(
            ReadRecordsRequest(T::class, TimeRangeFilter.between(from, to), pageSize = 1000, pageToken = token)
        )
        out.addAll(res.records)
        token = res.pageToken
    } while (!token.isNullOrEmpty())
    return out
}

/**
 * Stundensummen. Health Connect rechnet dabei Überschneidungen mehrerer Apps (Handy, Uhr, Fitness-App) nach der
 * Prioritätenliste in Health Connect heraus – Rohdaten aller Apps einfach zu addieren würde doppelt zählen.
 */
suspend fun <T : Any> HealthConnectClient.hourly(metric: AggregateMetric<T>, from: Instant, to: Instant): List<Triple<Instant, Instant, T>> {
    val start = from.truncatedTo(ChronoUnit.HOURS)
    if (!start.isBefore(to)) return emptyList()
    return aggregateGroupByDuration(
        AggregateGroupByDurationRequest(setOf(metric), TimeRangeFilter.between(start, to), Duration.ofHours(1))
    ).mapNotNull { g -> g.result[metric]?.let { Triple(g.startTime, g.endTime, it) } }
}

/** Summe/Mittel über einen Zeitraum; null, wenn kein Zugriff oder keine Daten. */
suspend fun <T : Any> HealthConnectClient.agg(metric: AggregateMetric<T>, from: Instant, to: Instant): T? = try {
    aggregate(AggregateRequest(setOf(metric), TimeRangeFilter.between(from, to)))[metric]
} catch (e: Exception) {
    null
}

private val STAGES = mapOf(
    SleepSessionRecord.STAGE_TYPE_DEEP to "deep",
    SleepSessionRecord.STAGE_TYPE_REM to "rem",
    SleepSessionRecord.STAGE_TYPE_LIGHT to "light",
    SleepSessionRecord.STAGE_TYPE_SLEEPING to "light",
    SleepSessionRecord.STAGE_TYPE_AWAKE to "awake",
    SleepSessionRecord.STAGE_TYPE_AWAKE_IN_BED to "awake",
    SleepSessionRecord.STAGE_TYPE_OUT_OF_BED to "awake",
)

private val EXERCISES = mapOf(
    ExerciseSessionRecord.EXERCISE_TYPE_RUNNING to "running",
    ExerciseSessionRecord.EXERCISE_TYPE_RUNNING_TREADMILL to "running_treadmill",
    ExerciseSessionRecord.EXERCISE_TYPE_WALKING to "walking",
    ExerciseSessionRecord.EXERCISE_TYPE_HIKING to "hiking",
    ExerciseSessionRecord.EXERCISE_TYPE_BIKING to "biking",
    ExerciseSessionRecord.EXERCISE_TYPE_BIKING_STATIONARY to "biking_stationary",
    ExerciseSessionRecord.EXERCISE_TYPE_STRENGTH_TRAINING to "strength_training",
    ExerciseSessionRecord.EXERCISE_TYPE_WEIGHTLIFTING to "weightlifting",
    ExerciseSessionRecord.EXERCISE_TYPE_CALISTHENICS to "calisthenics",
    ExerciseSessionRecord.EXERCISE_TYPE_HIGH_INTENSITY_INTERVAL_TRAINING to "hiit",
    ExerciseSessionRecord.EXERCISE_TYPE_BOOT_CAMP to "boot_camp",
    ExerciseSessionRecord.EXERCISE_TYPE_ROCK_CLIMBING to "rock_climbing",
    ExerciseSessionRecord.EXERCISE_TYPE_SWIMMING_POOL to "swimming_pool",
    ExerciseSessionRecord.EXERCISE_TYPE_SWIMMING_OPEN_WATER to "swimming_open_water",
    ExerciseSessionRecord.EXERCISE_TYPE_ROWING to "rowing",
    ExerciseSessionRecord.EXERCISE_TYPE_ROWING_MACHINE to "rowing_machine",
    ExerciseSessionRecord.EXERCISE_TYPE_ELLIPTICAL to "elliptical",
    ExerciseSessionRecord.EXERCISE_TYPE_STAIR_CLIMBING to "stair_climbing",
    ExerciseSessionRecord.EXERCISE_TYPE_STAIR_CLIMBING_MACHINE to "stair_climbing_machine",
    ExerciseSessionRecord.EXERCISE_TYPE_YOGA to "yoga",
    ExerciseSessionRecord.EXERCISE_TYPE_PILATES to "pilates",
    ExerciseSessionRecord.EXERCISE_TYPE_STRETCHING to "stretching",
    ExerciseSessionRecord.EXERCISE_TYPE_DANCING to "dancing",
    ExerciseSessionRecord.EXERCISE_TYPE_BOXING to "boxing",
    ExerciseSessionRecord.EXERCISE_TYPE_MARTIAL_ARTS to "martial_arts",
    ExerciseSessionRecord.EXERCISE_TYPE_SOCCER to "soccer",
    ExerciseSessionRecord.EXERCISE_TYPE_BASKETBALL to "basketball",
    ExerciseSessionRecord.EXERCISE_TYPE_VOLLEYBALL to "volleyball",
    ExerciseSessionRecord.EXERCISE_TYPE_HANDBALL to "handball",
    ExerciseSessionRecord.EXERCISE_TYPE_TENNIS to "tennis",
    ExerciseSessionRecord.EXERCISE_TYPE_TABLE_TENNIS to "table_tennis",
    ExerciseSessionRecord.EXERCISE_TYPE_BADMINTON to "badminton",
    ExerciseSessionRecord.EXERCISE_TYPE_SQUASH to "squash",
    ExerciseSessionRecord.EXERCISE_TYPE_GOLF to "golf",
    ExerciseSessionRecord.EXERCISE_TYPE_SKIING to "skiing",
    ExerciseSessionRecord.EXERCISE_TYPE_SNOWBOARDING to "snowboarding",
    ExerciseSessionRecord.EXERCISE_TYPE_ICE_SKATING to "ice_skating",
    ExerciseSessionRecord.EXERCISE_TYPE_SURFING to "surfing",
    ExerciseSessionRecord.EXERCISE_TYPE_PADDLING to "paddling",
    ExerciseSessionRecord.EXERCISE_TYPE_SAILING to "sailing",
    ExerciseSessionRecord.EXERCISE_TYPE_GYMNASTICS to "gymnastics",
    ExerciseSessionRecord.EXERCISE_TYPE_EXERCISE_CLASS to "exercise_class",
)

/**
 * Stundenwerte ohne Doppelzählung: je App (z. B. WHOOP, Google Fit, Samsung Health) die Stundensumme, dann pro
 * Stunde der höchste Wert. Zählen zwei Apps dieselben Schritte, bleibt so nur einer übrig; Einträge über mehrere
 * Stunden werden anteilig verteilt. (Die Health-Connect-Summen addieren Apps, die nicht in der Prioritätenliste stehen.)
 */
suspend inline fun <reified T> HealthConnectClient.hourlyMax(from: Instant, to: Instant, crossinline value: (T) -> Double): List<Pair<Instant, Double>>
        where T : IntervalRecord {
    val start = from.truncatedTo(ChronoUnit.HOURS)
    if (!start.isBefore(to)) return emptyList()
    val perApp = HashMap<String, TreeMap<Instant, Double>>()
    for (r in all<T>(start, to)) {
        val v = value(r)
        if (v.isNaN() || v <= 0) continue
        val app = r.metadata.dataOrigin.packageName
        val total = Duration.between(r.startTime, r.endTime).toMillis().coerceAtLeast(1).toDouble()
        var h = r.startTime.truncatedTo(ChronoUnit.HOURS)
        while (h.isBefore(r.endTime) || h == r.startTime) {
            val a = maxOf(h, r.startTime)
            val b = minOf(h.plus(Duration.ofHours(1)), r.endTime)
            val share = if (r.endTime == r.startTime) 1.0 else Duration.between(a, b).toMillis() / total
            if (share > 0 && !h.isBefore(start)) perApp.getOrPut(app) { TreeMap() }.merge(h, v * share, Double::plus)
            h = h.plus(Duration.ofHours(1))
            if (r.endTime == r.startTime) break
        }
    }
    val best = TreeMap<Instant, Double>()
    for (m in perApp.values) for ((h, v) in m) best.merge(h, v) { x, y -> maxOf(x, y) }
    return best.map { (h, v) -> h to v }
}

object Kinds {
    private val H6: Duration = Duration.ofHours(6)
    private val D2: Duration = Duration.ofDays(2)

    val ALL: List<Kind> = listOf(
        Kind("steps", "Schritte", Group.ACTIVITY, StepsRecord::class, D2, aggregated = true) { c, a, b ->
            c.hourlyMax<StepsRecord>(a, b) { it.count.toDouble() }.map { (h, v) -> span(h, h.plus(Duration.ofHours(1))).put("count", Math.round(v)) }
        },
        Kind("distance", "Strecke", Group.ACTIVITY, DistanceRecord::class, D2, aggregated = true) { c, a, b ->
            c.hourlyMax<DistanceRecord>(a, b) { it.distance.inMeters }.map { (h, v) -> span(h, h.plus(Duration.ofHours(1))).put("meters", round1(v)) }
        },
        Kind("active_calories", "Aktive Kalorien", Group.ACTIVITY, ActiveCaloriesBurnedRecord::class, D2, aggregated = true) { c, a, b ->
            c.hourlyMax<ActiveCaloriesBurnedRecord>(a, b) { it.energy.inKilocalories }.map { (h, v) -> span(h, h.plus(Duration.ofHours(1))).put("calories", round1(v)) }
        },
        Kind("total_calories", "Kalorien gesamt", Group.ACTIVITY, TotalCaloriesBurnedRecord::class, D2, aggregated = true) { c, a, b ->
            c.hourlyMax<TotalCaloriesBurnedRecord>(a, b) { it.energy.inKilocalories }.map { (h, v) -> span(h, h.plus(Duration.ofHours(1))).put("calories", round1(v)) }
        },
        Kind("exercise", "Trainings", Group.ACTIVITY, ExerciseSessionRecord::class, D2) { c, a, b ->
            c.all<ExerciseSessionRecord>(a, b).map { r ->
                val j = span(r.startTime, r.endTime)
                    .put("type", EXERCISES[r.exerciseType] ?: "workout")
                    .put("duration_seconds", Duration.between(r.startTime, r.endTime).seconds)
                r.title?.takeIf { it.isNotBlank() }?.let { j.put("title", it) }
                j.maybe("distance_meters", c.agg(DistanceRecord.DISTANCE_TOTAL, r.startTime, r.endTime)?.inMeters?.takeIf { it > 0 })
                j.maybe("calories", (c.agg(TotalCaloriesBurnedRecord.ENERGY_TOTAL, r.startTime, r.endTime)
                    ?: c.agg(ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL, r.startTime, r.endTime))?.inKilocalories?.takeIf { it > 0 })
                j.maybe("avg_heart_rate", c.agg(HeartRateRecord.BPM_AVG, r.startTime, r.endTime)?.toDouble())
                j.maybe("max_heart_rate", c.agg(HeartRateRecord.BPM_MAX, r.startTime, r.endTime)?.toDouble())
                j
            }
        },
        // Puls: Einzelwerte zu Minutenmitteln zusammengefasst (spart Datenvolumen, BodyBase speichert ohnehin je Minute)
        Kind("heart_rate", "Puls", Group.HEART, HeartRateRecord::class, H6) { c, a, b ->
            val minutes = TreeMap<Long, IntArray>() // Minute -> [Summe, Anzahl, Min, Max]
            for (r in c.all<HeartRateRecord>(a, b)) for (s in r.samples) {
                if (s.time < a || s.time >= b) continue
                val bpm = s.beatsPerMinute.toInt()
                val v = minutes.getOrPut(s.time.epochSecond / 60) { intArrayOf(0, 0, Int.MAX_VALUE, 0) }
                v[0] += bpm; v[1] += 1; v[2] = minOf(v[2], bpm); v[3] = maxOf(v[3], bpm)
            }
            minutes.map { (m, v) ->
                at(Instant.ofEpochSecond(m * 60)).put("avg", round1(v[0].toDouble() / v[1])).put("min", v[2]).put("max", v[3])
            }
        },
        Kind("resting_heart_rate", "Ruhepuls", Group.HEART, RestingHeartRateRecord::class, D2) { c, a, b ->
            c.all<RestingHeartRateRecord>(a, b).map { at(it.time).put("bpm", it.beatsPerMinute) }
        },
        Kind("heart_rate_variability", "HRV", Group.HEART, HeartRateVariabilityRmssdRecord::class, D2) { c, a, b ->
            c.all<HeartRateVariabilityRmssdRecord>(a, b).map { at(it.time).put("rmssd_millis", it.heartRateVariabilityMillis) }
        },
        Kind("sleep", "Schlaf", Group.SLEEP, SleepSessionRecord::class, D2) { c, a, b ->
            c.all<SleepSessionRecord>(a, b).map { r ->
                val stages = JSONArray()
                r.stages.forEach { s ->
                    val name = STAGES[s.stage] ?: return@forEach
                    stages.put(span(s.startTime, s.endTime).put("stage", name).put("duration_seconds", Duration.between(s.startTime, s.endTime).seconds))
                }
                span(r.startTime, r.endTime)
                    .put("session_end_time", r.endTime.toString())
                    .put("duration_seconds", Duration.between(r.startTime, r.endTime).seconds)
                    .put("stages", stages)
            }
        },
        Kind("weight", "Gewicht", Group.BODY, WeightRecord::class, D2) { c, a, b ->
            c.all<WeightRecord>(a, b).map { at(it.time).put("kilograms", it.weight.inKilograms) }
        },
        Kind("body_fat", "Körperfett", Group.BODY, BodyFatRecord::class, D2) { c, a, b ->
            c.all<BodyFatRecord>(a, b).map { at(it.time).put("percentage", it.percentage.value) }
        },
        Kind("lean_body_mass", "Magermasse", Group.BODY, LeanBodyMassRecord::class, D2) { c, a, b ->
            c.all<LeanBodyMassRecord>(a, b).map { at(it.time).put("kilograms", it.mass.inKilograms) }
        },
        Kind("bone_mass", "Knochenmasse", Group.BODY, BoneMassRecord::class, D2) { c, a, b ->
            c.all<BoneMassRecord>(a, b).map { at(it.time).put("kilograms", it.mass.inKilograms) }
        },
        Kind("vo2_max", "VO2max", Group.VITALS, Vo2MaxRecord::class, D2) { c, a, b ->
            c.all<Vo2MaxRecord>(a, b).map { at(it.time).put("ml_per_kg_per_min", it.vo2MillilitersPerMinuteKilogram) }
        },
        Kind("oxygen_saturation", "Sauerstoff (SpO₂)", Group.VITALS, OxygenSaturationRecord::class, D2) { c, a, b ->
            c.all<OxygenSaturationRecord>(a, b).map { at(it.time).put("percentage", it.percentage.value) }
        },
        Kind("respiratory_rate", "Atemfrequenz", Group.VITALS, RespiratoryRateRecord::class, D2) { c, a, b ->
            c.all<RespiratoryRateRecord>(a, b).map { at(it.time).put("rate", it.rate) }
        },
        Kind("body_temperature", "Körpertemperatur", Group.VITALS, BodyTemperatureRecord::class, D2) { c, a, b ->
            c.all<BodyTemperatureRecord>(a, b).map { at(it.time).put("celsius", it.temperature.inCelsius) }
        },
        Kind("blood_pressure", "Blutdruck", Group.VITALS, BloodPressureRecord::class, D2) { c, a, b ->
            c.all<BloodPressureRecord>(a, b).map {
                at(it.time).put("systolic", it.systolic.inMillimetersOfMercury).put("diastolic", it.diastolic.inMillimetersOfMercury)
            }
        },
        Kind("blood_glucose", "Blutzucker", Group.VITALS, BloodGlucoseRecord::class, D2) { c, a, b ->
            c.all<BloodGlucoseRecord>(a, b).map { at(it.time).put("mmol_per_liter", it.level.inMillimolesPerLiter) }
        },
        Kind("nutrition", "Ernährung", Group.NUTRITION, NutritionRecord::class, D2) { c, a, b ->
            c.all<NutritionRecord>(a, b).map {
                span(it.startTime, it.endTime)
                    .maybe("calories", it.energy?.inKilocalories)
                    .maybe("protein_grams", it.protein?.inGrams)
                    .maybe("carbs_grams", it.totalCarbohydrate?.inGrams)
                    .maybe("fat_grams", it.totalFat?.inGrams)
                    .maybe("caffeine_grams", it.caffeine?.inGrams)
            }
        },
        Kind("hydration", "Trinken", Group.NUTRITION, HydrationRecord::class, D2, aggregated = true) { c, a, b ->
            c.hourly(HydrationRecord.VOLUME_TOTAL, a, b).map { (s, e, v) -> span(s, e).put("liters", v.inLiters) }
        },
    )

    fun byKey(key: String) = ALL.firstOrNull { it.key == key }
}
