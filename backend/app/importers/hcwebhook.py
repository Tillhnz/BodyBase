"""Empfang von „HC Webhook“ (Android-App, liest Health Connect und schickt die Daten per POST).

App: https://github.com/mcnaveen/health-connect-webhook (Google Play oder GitHub). Health Connect sammelt die Daten
von Google Fit, Samsung Health, Fitbit, Xiaomi, Zepp, Garmin und vielen mehr.
Format: docs/webhook.md des Projekts. Intervalle (Schritte, Kalorien …) werden je Startzeit gespeichert und je Tag
summiert; erneut gesendete oder geänderte Einträge ersetzen den alten Wert.
"""
from __future__ import annotations

from datetime import timedelta

from ..store import ActivityIn, SleepIn, Writer
from ..timeutil import parse_iso

# Messwerte mit Zeitpunkt: Schlüssel im Webhook -> (Metrik, Feldnamen in Reihenfolge, Faktor)
POINT = {
    "heart_rate": ("heart_rate", ("avg", "bpm"), 1),
    "heart_rate_variability": ("hrv", ("avg", "rmssd_millis"), 1),
    "resting_heart_rate": ("resting_hr", ("bpm",), 1),
    "weight": ("weight", ("kilograms",), 1),
    "body_fat": ("body_fat", ("percentage",), 1),
    "lean_body_mass": ("lean_mass", ("kilograms",), 1),
    "bone_mass": ("bone_mass", ("kilograms",), 1),
    "oxygen_saturation": ("spo2", ("avg", "percentage"), 1),
    "respiratory_rate": ("respiratory_rate", ("avg", "rate"), 1),
    "body_temperature": ("body_temp", ("celsius",), 1),
    "skin_temperature": ("skin_temp_dev", ("avg_delta_celsius", "delta_celsius"), 1),
    "vo2_max": ("vo2max", ("ml_per_kg_per_min",), 1),
    "blood_glucose": ("glucose", ("mmol_per_liter",), 18.016),  # mmol/L -> mg/dL
}
# Mengen über einen Zeitraum: Summe je Tag
INTERVAL = {
    "steps": ("steps", "count", 1),
    "distance": ("distance", "meters", 0.001),
    "active_calories": ("active_energy", "calories", 1),
    "total_calories": ("total_energy", "calories", 1),
    "hydration": ("water", "liters", 1000),
}
NUTRITION = {"calories": ("calories_in", 1), "protein_grams": ("protein", 1), "carbs_grams": ("carbs", 1),
             "fat_grams": ("fat", 1), "caffeine_grams": ("caffeine", 1000)}
# Schlafphasen (Text oder Konstante aus Health Connect)
STAGES = {"1": "awake", "2": "light", "3": "awake", "4": "light", "5": "deep", "6": "rem", "7": "awake"}
# häufige Trainingsarten als Zahl (Health Connect ExerciseSessionRecord)
EXERCISE_CODES = {"8": "biking", "9": "biking_stationary", "56": "running", "57": "running_treadmill", "79": "walking",
                  "37": "hiking", "70": "strength_training", "81": "weightlifting", "73": "swimming_open_water",
                  "74": "swimming_pool", "53": "rock_climbing", "83": "yoga", "36": "hiit", "25": "elliptical",
                  "61": "rowing_machine", "48": "pilates"}


def _num(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _first(item: dict, keys) -> float | None:
    for k in keys:
        v = _num(item.get(k))
        if v is not None:
            return v
    return None


def _stage(raw) -> str | None:
    s = str(raw or "").lower()
    if s in STAGES:
        return STAGES[s]
    for key in ("deep", "rem", "light", "awake", "out_of_bed"):
        if key in s:
            return "awake" if key == "out_of_bed" else key
    if "sleep" in s:
        return "light"
    return None


def looks_like(payload: dict) -> bool:
    return isinstance(payload, dict) and "app_version" in payload and "timestamp" in payload and "metrics" not in payload


def ingest(w: Writer, payload: dict) -> dict:
    counts = {"records": 0}

    def rec(n=1):
        counts["records"] += n

    for key, (metric, fields, factor) in POINT.items():
        for item in payload.get(key) or []:
            v, ts = _first(item, fields), parse_iso(item.get("time"))
            if v is not None and ts is not None:
                w.sample(metric, ts, v * factor)
                rec()
    for key, (metric, field, factor) in INTERVAL.items():
        for item in payload.get(key) or []:
            v, ts = _num(item.get(field)), parse_iso(item.get("start_time"))
            if v is not None and ts is not None:
                w.sample(metric, ts, v * factor)
                rec()
    for item in payload.get("nutrition") or []:
        ts = parse_iso(item.get("start_time"))
        for field, (metric, factor) in NUTRITION.items():
            v = _num(item.get(field))
            if v is not None and ts is not None:
                w.sample(metric, ts, v * factor)
        rec()
    for item in payload.get("blood_pressure") or []:
        ts = parse_iso(item.get("time"))
        w.sample("bp_systolic", ts, item.get("systolic"))
        w.sample("bp_diastolic", ts, item.get("diastolic"))
        rec()
    for item in payload.get("mindfulness") or []:
        ts, dur = parse_iso(item.get("start_time")), _num(item.get("duration_seconds"))
        if ts and dur:
            w.sample("mindful_minutes", ts, dur / 60)
            rec()
    for item in payload.get("sleep") or []:
        end, dur = parse_iso(item.get("session_end_time")), _num(item.get("duration_seconds"))
        if not end or not dur:
            continue
        start = end - timedelta(seconds=dur)
        mins = {"deep": 0.0, "rem": 0.0, "light": 0.0, "awake": 0.0}
        stages = item.get("stages") or []
        for st in stages:
            kind = _stage(st.get("stage"))
            sec = _num(st.get("duration_seconds"))
            if sec is None:
                a, b = parse_iso(st.get("start_time")), parse_iso(st.get("end_time"))
                sec = (b - a).total_seconds() if a and b else 0
            if kind:
                mins[kind] += sec / 60
        asleep = mins["deep"] + mins["rem"] + mins["light"] if stages else dur / 60
        w.sleep(SleepIn(source_id=f"hc-{end.isoformat()}", start=start, end=end, asleep_min=asleep or None,
                        deep_min=mins["deep"] or None, rem_min=mins["rem"] or None, light_min=mins["light"] or None,
                        awake_min=mins["awake"] or None, nap=dur < 3 * 3600 and 9 <= end.hour <= 20))
        rec()
    for item in payload.get("exercise") or []:
        start, end = parse_iso(item.get("start_time")), parse_iso(item.get("end_time"))
        if not start:
            continue
        raw = str(item.get("type") or "")
        raw = EXERCISE_CODES.get(raw, raw).lower().replace("exercise_type_", "")
        w.activity(ActivityIn(
            source_id=f"hc-{start.isoformat()}", start=start, sport_raw=raw, name=raw.replace("_", " ").title() or None,
            duration_s=_num(item.get("duration_seconds")) or ((end - start).total_seconds() if end else None),
            distance_m=_num(item.get("distance_meters")),
        ))
        rec()
    return counts
