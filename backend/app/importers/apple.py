"""Apple Health: Daten der App „Health Auto Export“ (Webhook, JSON) und der Export aus der Health-App (export.zip).

Beide Wege landen als Quelle "apple_health". Werte werden in die Basiseinheiten von BodyBase umgerechnet.
"""
from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta

from .. import metrics as M
from ..store import ActivityIn, SleepIn, Writer
from ..timeutil import local_day, parse_iso

log = logging.getLogger("bodybase.apple")

LB = 0.45359237
KJ = 1 / 4.184


def convert(metric: str, value: float, unit: str | None) -> float | None:
    """Einheiten von Apple Health auf die Basiseinheit der Metrik umrechnen."""
    if value is None:
        return None
    u = (unit or "").strip().lower().replace("·", "").replace(" ", "")
    if metric in ("weight", "lean_mass", "muscle_mass", "bone_mass"):
        if u in ("lb", "lbs"):
            return value * LB
        if u == "g":
            return value / 1000
        return value
    if metric in ("active_energy", "total_energy", "calories_in"):
        return value * KJ if u in ("kj",) else value
    if metric == "distance":
        if u in ("mi", "mile", "miles"):
            return value * 1.609344
        if u == "m":
            return value / 1000
        if u == "yd":
            return value * 0.0009144
        return value
    if metric in ("spo2", "body_fat", "body_water"):
        return value * 100 if value <= 1.0 else value
    if metric == "glucose":
        return value * 18.0182 if "mmol" in u else value
    if metric == "body_temp":
        return (value - 32) / 1.8 if u in ("degf", "°f", "f") else value
    if metric == "water":
        if u in ("l",):
            return value * 1000
        if "oz" in u:
            return value * 29.5735
        return value
    if metric == "waist":
        if u in ("in", "inch"):
            return value * 2.54
        if u == "m":
            return value * 100
        return value
    if metric in ("active_minutes", "mindful_minutes"):
        if u in ("hr", "h"):
            return value * 60
        if u in ("s", "sec"):
            return value / 60
        return value
    return value


# ---------- Health Auto Export (iOS-App, REST-Automatisierung) ----------

HAE_METRICS = {
    "step_count": "steps", "active_energy": "active_energy", "apple_exercise_time": "active_minutes",
    "flights_climbed": "floors", "walking_running_distance": "distance", "heart_rate": "heart_rate",
    "resting_heart_rate": "resting_hr", "heart_rate_variability": "hrv", "blood_oxygen_saturation": "spo2",
    "respiratory_rate": "respiratory_rate", "vo2_max": "vo2max", "weight_body_mass": "weight", "body_mass": "weight",
    "body_fat_percentage": "body_fat", "body_mass_index": "bmi", "lean_body_mass": "lean_mass", "blood_glucose": "glucose",
    "body_temperature": "body_temp", "dietary_energy": "calories_in", "protein": "protein", "carbohydrates": "carbs",
    "total_fat": "fat", "dietary_water": "water", "dietary_caffeine": "caffeine", "mindful_minutes": "mindful_minutes",
    "waist_circumference": "waist",
}


def _qty(item: dict, *keys):
    for k in keys:
        v = item.get(k)
        if isinstance(v, dict):
            v = v.get("qty")
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def ingest_health_auto_export(w: Writer, payload: dict) -> None:
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    for m in data.get("metrics", []) or []:
        name = m.get("name")
        units = m.get("units")
        points = m.get("data", []) or []
        if name == "sleep_analysis":
            for p in points:
                s = hae_sleep(p)
                if s:
                    w.sleep(s)
            continue
        if name == "blood_pressure":
            for p in points:
                ts = parse_iso(p.get("date"))
                w.sample("bp_systolic", ts, _qty(p, "systolic"))
                w.sample("bp_diastolic", ts, _qty(p, "diastolic"))
            continue
        metric = HAE_METRICS.get(name)
        if not metric:
            continue
        for p in points:
            ts = parse_iso(p.get("date"))
            v = _qty(p, "qty", "Avg", "avg")
            if v is None:
                continue
            w.sample(metric, ts, convert(metric, v, units))
    for wo in data.get("workouts", []) or []:
        a = hae_workout(wo)
        if a:
            w.activity(a)


def hae_sleep(p: dict) -> SleepIn | None:
    start = parse_iso(p.get("sleepStart") or p.get("inBedStart"))
    end = parse_iso(p.get("sleepEnd") or p.get("inBedEnd"))
    if not start or not end:
        return None

    def mins(k):
        v = _qty(p, k)
        return v * 60 if v is not None else None  # Stunden
    asleep = mins("totalSleep") or mins("asleep")
    return SleepIn(source_id=f"hae-{start.isoformat()}", start=start, end=end, asleep_min=asleep, deep_min=mins("deep"),
                   rem_min=mins("rem"), light_min=mins("core"), awake_min=mins("awake"))


def hae_workout(wo: dict) -> ActivityIn | None:
    start, end = parse_iso(wo.get("start")), parse_iso(wo.get("end"))
    if not start:
        return None
    dist = wo.get("distance") if isinstance(wo.get("distance"), dict) else {}
    energy = wo.get("activeEnergyBurned") or wo.get("activeEnergy") or {}
    if isinstance(energy, list):
        energy = {"qty": sum(_qty(e, "qty") or 0 for e in energy), "units": (energy[0] or {}).get("units") if energy else None}
    hr = wo.get("heartRate") or {}
    elev = wo.get("elevationUp") if isinstance(wo.get("elevationUp"), dict) else {}
    dist_km = convert("distance", _qty(dist, "qty"), dist.get("units")) if _qty(dist, "qty") is not None else None
    return ActivityIn(
        source_id=str(wo.get("id") or f"hae-{start.isoformat()}"), start=start, sport_raw=wo.get("name"), name=wo.get("name"),
        duration_s=_qty(wo, "duration") or ((end - start).total_seconds() if end else None),
        distance_m=dist_km * 1000 if dist_km is not None else None,
        calories=convert("active_energy", _qty(energy, "qty"), energy.get("units")) if _qty(energy, "qty") is not None else None,
        avg_hr=_qty(wo, "avgHeartRate") or _qty(hr.get("avg") or {}, "qty"),
        max_hr=_qty(wo, "maxHeartRate") or _qty(hr.get("max") or {}, "qty"),
        elevation_m=_qty(elev, "qty"),
    )


# ---------- Export aus der Health-App (export.zip / export.xml) ----------

HK = "HKQuantityTypeIdentifier"
XML_METRICS = {
    "StepCount": "steps", "ActiveEnergyBurned": "active_energy", "AppleExerciseTime": "active_minutes",
    "FlightsClimbed": "floors", "DistanceWalkingRunning": "distance", "HeartRate": "heart_rate",
    "RestingHeartRate": "resting_hr", "HeartRateVariabilitySDNN": "hrv", "OxygenSaturation": "spo2",
    "RespiratoryRate": "respiratory_rate", "VO2Max": "vo2max", "BodyMass": "weight", "BodyFatPercentage": "body_fat",
    "BodyMassIndex": "bmi", "LeanBodyMass": "lean_mass", "BloodPressureSystolic": "bp_systolic",
    "BloodPressureDiastolic": "bp_diastolic", "BloodGlucose": "glucose", "BodyTemperature": "body_temp",
    "DietaryEnergyConsumed": "calories_in", "DietaryProtein": "protein", "DietaryCarbohydrates": "carbs",
    "DietaryFatTotal": "fat", "DietaryWater": "water", "DietaryCaffeine": "caffeine", "WaistCircumference": "waist",
}
SLEEP_STAGE = {
    "HKCategoryValueSleepAnalysisAsleepDeep": "deep", "HKCategoryValueSleepAnalysisAsleepREM": "rem",
    "HKCategoryValueSleepAnalysisAsleepCore": "light", "HKCategoryValueSleepAnalysisAsleepUnspecified": "asleep",
    "HKCategoryValueSleepAnalysisAsleep": "asleep", "HKCategoryValueSleepAnalysisAwake": "awake",
}
# Sehr häufige Messwerte werden zu Stundenmitteln zusammengefasst
HOURLY = {"heart_rate", "glucose", "respiratory_rate", "spo2"}


class _Counting(io.RawIOBase):
    def __init__(self, f, total, cb):
        self.f, self.total, self.cb, self.read_bytes, self._last = f, total, cb, 0, 0

    def readable(self):
        return True

    def readinto(self, b):
        data = self.f.read(len(b))
        n = len(data)
        b[:n] = data
        self.read_bytes += n
        if self.cb and self.total and self.read_bytes - self._last > 8 * 1024 * 1024:
            self._last = self.read_bytes
            self.cb(min(0.99, self.read_bytes / self.total))
        return n


def open_export(path: str):
    """Liefert (Datei-Objekt, Größe) für export.xml aus einer ZIP-Datei oder direkt."""
    if zipfile.is_zipfile(path):
        z = zipfile.ZipFile(path)
        names = [n for n in z.namelist() if n.endswith("export.xml") and "cda" not in n.lower()]
        if not names:
            raise ValueError("In der ZIP-Datei fehlt export.xml. Exportiere in der Health-App über Profil → Alle Gesundheitsdaten exportieren.")
        info = z.getinfo(names[0])
        return z.open(info), info.file_size
    import os
    return open(path, "rb"), os.path.getsize(path)


def import_export_xml(w: Writer, path: str, progress=None, since: datetime | None = None) -> dict:
    f, size = open_export(path)
    stream = io.BufferedReader(_Counting(f, size, progress), buffer_size=1024 * 1024)
    daily_sums: dict = defaultdict(float)  # (metric, day, quelle) -> Summe
    hourly: dict = defaultdict(lambda: [0.0, 0])  # (metric, Stunde) -> [Summe, Anzahl]
    sleep_parts: list = []
    mindful: dict = defaultdict(float)
    n = 0
    root = None
    try:
        for event, el in ET.iterparse(stream, events=("start", "end")):
            if event == "start":
                if root is None:
                    root = el
                continue
            tag = el.tag
            if tag == "Record":
                n += 1
                _record(el.attrib, w, daily_sums, hourly, sleep_parts, mindful, since)
            elif tag == "Workout":
                a = _workout(el)
                if a and (since is None or a.start >= since):
                    w.activity(a)
            else:
                continue
            if root is not None:
                root.clear()  # Speicher freigeben: export.xml kann mehrere GB groß sein
    finally:
        f.close()
    # Summen: Pro Tag die Quelle mit der größten Summe (iPhone und Uhr zählen sonst doppelt)
    best: dict = {}
    for (metric, day, src), total in daily_sums.items():
        key = (metric, day)
        if total > best.get(key, -1):
            best[key] = total
    for (metric, day), total in best.items():
        w.daily(metric, day, total)
    for (metric, hour), (total, cnt) in hourly.items():
        w.sample(metric, hour + timedelta(minutes=30), total / cnt)
    for day, minutes in mindful.items():
        w.daily("mindful_minutes", day, minutes)
    for s in build_sleep_sessions(sleep_parts):
        w.sleep(s)
    return {"records": n}


def _record(a: dict, w: Writer, daily_sums, hourly, sleep_parts, mindful, since):
    t = a.get("type", "")
    if t == "HKCategoryTypeIdentifierSleepAnalysis":
        stage = SLEEP_STAGE.get(a.get("value"))
        start, end = parse_iso(a.get("startDate")), parse_iso(a.get("endDate"))
        if stage and start and end and (since is None or end >= since):
            sleep_parts.append((start, end, stage, a.get("sourceName", "")))
        return
    if t == "HKCategoryTypeIdentifierMindfulSession":
        start, end = parse_iso(a.get("startDate")), parse_iso(a.get("endDate"))
        if start and end and (since is None or start >= since):
            mindful[local_day(start)] += (end - start).total_seconds() / 60
        return
    if not t.startswith(HK):
        return
    metric = XML_METRICS.get(t[len(HK):])
    if not metric:
        return
    try:
        value = float(a.get("value"))
    except (TypeError, ValueError):
        return
    start = parse_iso(a.get("startDate"))
    if start is None or (since is not None and start < since):
        return
    value = convert(metric, value, a.get("unit"))
    if value is None:
        return
    m = M.METRICS[metric]
    if m.agg == "sum":
        daily_sums[(metric, local_day(start), a.get("sourceName", ""))] += value
    elif metric in HOURLY:
        hour = start.replace(minute=0, second=0, microsecond=0)
        bucket = hourly[(metric, hour)]
        bucket[0] += value
        bucket[1] += 1
    else:
        w.sample(metric, start, value)


def _workout(el) -> ActivityIn | None:
    a = el.attrib
    start, end = parse_iso(a.get("startDate")), parse_iso(a.get("endDate"))
    if not start:
        return None
    kind = (a.get("workoutActivityType") or "").replace("HKWorkoutActivityType", "")
    dist_km = energy = None
    if a.get("totalDistance"):
        dist_km = convert("distance", float(a["totalDistance"]), a.get("totalDistanceUnit"))
    if a.get("totalEnergyBurned"):
        energy = convert("active_energy", float(a["totalEnergyBurned"]), a.get("totalEnergyBurnedUnit"))
    avg_hr = max_hr = None
    for st in el.findall("WorkoutStatistics"):
        sa = st.attrib
        typ = sa.get("type", "")
        try:
            if typ.endswith("DistanceWalkingRunning") or typ.endswith("DistanceCycling") or typ.endswith("DistanceSwimming"):
                dist_km = dist_km or convert("distance", float(sa.get("sum")), sa.get("unit"))
            elif typ.endswith("ActiveEnergyBurned"):
                energy = energy or convert("active_energy", float(sa.get("sum")), sa.get("unit"))
            elif typ.endswith("HeartRate"):
                avg_hr = float(sa.get("average")) if sa.get("average") else None
                max_hr = float(sa.get("maximum")) if sa.get("maximum") else None
        except (TypeError, ValueError):
            continue
    dur = None
    if a.get("duration"):
        try:
            dur = float(a["duration"]) * (60 if (a.get("durationUnit") or "min") == "min" else 1)
        except ValueError:
            dur = None
    return ActivityIn(
        source_id=f"ah-{start.isoformat()}-{kind}", start=start, sport_raw=kind, name=kind,
        duration_s=dur or ((end - start).total_seconds() if end else None),
        distance_m=dist_km * 1000 if dist_km is not None else None, calories=energy, avg_hr=avg_hr, max_hr=max_hr,
    )


def build_sleep_sessions(parts: list) -> list[SleepIn]:
    """Einzelne Schlafabschnitte zu Nächten zusammenfassen (Lücken unter 90 Minuten gehören dazu).
    Je Nacht zählt nur die Quelle mit den meisten Daten (Uhr und Handy überschneiden sich)."""
    by_src: dict = defaultdict(list)
    for p in parts:
        by_src[p[3]].append(p)
    sessions: list = []
    for src, items in by_src.items():
        items.sort()
        cur = None
        for start, end, stage, _ in items:
            if cur and start - cur["end"] <= timedelta(minutes=90):
                cur["end"] = max(cur["end"], end)
            else:
                if cur:
                    sessions.append(cur)
                cur = {"start": start, "end": end, "src": src, "deep": 0.0, "rem": 0.0, "light": 0.0, "asleep": 0.0, "awake": 0.0}
            cur[stage] += (end - start).total_seconds() / 60
        if cur:
            sessions.append(cur)
    # pro Aufwachtag die Sitzung mit der meisten Schlafzeit behalten (Nickerchen unter 3 h nicht)
    best: dict = {}
    for s in sessions:
        total = s["deep"] + s["rem"] + s["light"] + s["asleep"]
        if total < 180:
            continue
        day = local_day(s["end"])
        if total > best.get(day, (0, None))[0]:
            best[day] = (total, s)
    out = []
    for day, (total, s) in best.items():
        staged = s["deep"] + s["rem"] + s["light"] > 0
        out.append(SleepIn(source_id=f"ah-sleep-{day.isoformat()}", start=s["start"], end=s["end"], asleep_min=total,
                           deep_min=s["deep"] if staged else None, rem_min=s["rem"] if staged else None,
                           light_min=s["light"] if staged else None, awake_min=s["awake"] or None))
    return out
