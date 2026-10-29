"""Alle Messgrößen, die BodyBase kennt. Werte werden immer in der hier genannten Einheit gespeichert.

agg: wie mehrere Werte eines Tages zusammengefasst werden (sum, avg, min, max).
better: in welche Richtung eine Änderung gut ist ("up", "down" oder None = neutral), für Pfeile und Farben.
"""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str
    category: str
    agg: str = "avg"
    decimals: int = 0
    better: str | None = None
    lo: float | None = None  # Plausibilitätsgrenzen; Werte außerhalb werden verworfen
    hi: float | None = None


CATEGORIES = {
    "body": "Körper",
    "heart": "Herz & Kreislauf",
    "activity": "Bewegung",
    "sleep": "Schlaf",
    "recovery": "Erholung",
    "nutrition": "Ernährung",
    "metabolic": "Stoffwechsel",
}

METRICS: dict[str, Metric] = {m.key: m for m in [
    # Körper
    Metric("weight", "Gewicht", "kg", "body", "avg", 1, None, 20, 400),
    Metric("body_fat", "Körperfett", "%", "body", "avg", 1, "down", 2, 70),
    Metric("muscle_mass", "Muskelmasse", "kg", "body", "avg", 1, "up", 5, 150),
    Metric("lean_mass", "Fettfreie Masse", "kg", "body", "avg", 1, "up", 10, 200),
    Metric("bone_mass", "Knochenmasse", "kg", "body", "avg", 1, None, 0.5, 10),
    Metric("body_water", "Körperwasser", "%", "body", "avg", 1, None, 20, 80),
    Metric("bmi", "BMI", "", "body", "avg", 1, None, 10, 80),
    Metric("waist", "Taillenumfang", "cm", "body", "avg", 1, "down", 40, 200),
    Metric("visceral_fat", "Viszeralfett", "", "body", "avg", 0, "down", 0, 60),
    # Herz & Kreislauf
    Metric("resting_hr", "Ruhepuls", "bpm", "heart", "avg", 0, "down", 25, 130),
    Metric("heart_rate", "Puls", "bpm", "heart", "avg", 0, None, 25, 230),
    Metric("hrv", "Herzfrequenzvariabilität", "ms", "heart", "avg", 0, "up", 3, 300),
    Metric("bp_systolic", "Blutdruck systolisch", "mmHg", "heart", "avg", 0, "down", 60, 260),
    Metric("bp_diastolic", "Blutdruck diastolisch", "mmHg", "heart", "avg", 0, "down", 30, 160),
    Metric("spo2", "Sauerstoffsättigung", "%", "heart", "avg", 0, "up", 70, 100),
    Metric("respiratory_rate", "Atemfrequenz", "/min", "heart", "avg", 1, None, 4, 40),
    Metric("vo2max", "VO₂max", "ml/kg/min", "heart", "avg", 1, "up", 10, 95),
    Metric("body_temp", "Körpertemperatur", "°C", "heart", "avg", 1, None, 33, 43),
    Metric("skin_temp_dev", "Hauttemperatur (Abweichung)", "°C", "heart", "avg", 2, None, -6, 6),
    # Bewegung
    Metric("steps", "Schritte", "", "activity", "sum", 0, "up", 0, 150000),
    Metric("distance", "Strecke (Alltag)", "km", "activity", "sum", 1, "up", 0, 300),
    Metric("active_energy", "Aktive Kalorien", "kcal", "activity", "sum", 0, "up", 0, 15000),
    Metric("total_energy", "Gesamtumsatz", "kcal", "activity", "sum", 0, None, 0, 20000),
    Metric("active_minutes", "Aktive Minuten", "min", "activity", "sum", 0, "up", 0, 1440),
    Metric("floors", "Etagen", "", "activity", "sum", 0, "up", 0, 1000),
    Metric("training_load", "Trainingsbelastung", "", "activity", "sum", 0, None, 0, 2000),
    # Schlaf
    Metric("sleep_duration", "Schlafdauer", "min", "sleep", "sum", 0, "up", 0, 1440),
    Metric("sleep_deep", "Tiefschlaf", "min", "sleep", "sum", 0, "up", 0, 900),
    Metric("sleep_rem", "REM-Schlaf", "min", "sleep", "sum", 0, "up", 0, 900),
    Metric("sleep_light", "Leichtschlaf", "min", "sleep", "sum", 0, None, 0, 1200),
    Metric("sleep_awake", "Wachzeit", "min", "sleep", "sum", 0, "down", 0, 900),
    Metric("sleep_score", "Schlafwert", "", "sleep", "avg", 0, "up", 0, 100),
    Metric("sleep_efficiency", "Schlafeffizienz", "%", "sleep", "avg", 0, "up", 0, 100),
    # Erholung
    Metric("readiness", "Bereitschaft", "", "recovery", "avg", 0, "up", 0, 100),
    Metric("recovery", "Erholung (WHOOP)", "%", "recovery", "avg", 0, "up", 0, 100),
    Metric("body_battery", "Body Battery", "", "recovery", "max", 0, "up", 0, 100),
    Metric("stress", "Stress", "", "recovery", "avg", 0, "down", 0, 100),
    Metric("strain", "Belastung (WHOOP)", "", "recovery", "avg", 1, None, 0, 21),
    Metric("mindful_minutes", "Achtsamkeit", "min", "recovery", "sum", 0, "up", 0, 1440),
    # Ernährung
    Metric("calories_in", "Kalorienaufnahme", "kcal", "nutrition", "sum", 0, None, 0, 15000),
    Metric("protein", "Eiweiß", "g", "nutrition", "sum", 0, None, 0, 1000),
    Metric("carbs", "Kohlenhydrate", "g", "nutrition", "sum", 0, None, 0, 2000),
    Metric("fat", "Fett", "g", "nutrition", "sum", 0, None, 0, 1000),
    Metric("water", "Trinkmenge", "ml", "nutrition", "sum", 0, "up", 0, 15000),
    Metric("caffeine", "Koffein", "mg", "nutrition", "sum", 0, None, 0, 3000),
    # Stoffwechsel
    Metric("glucose", "Blutzucker", "mg/dL", "metabolic", "avg", 0, None, 20, 600),
    Metric("ketones", "Ketone", "mmol/L", "metabolic", "avg", 1, None, 0, 10),
]}

# Werte aus dem Schlaf, die beim Speichern einer Schlafphase zusätzlich als Messwert abgelegt werden
SLEEP_METRICS = {
    "asleep_min": "sleep_duration", "deep_min": "sleep_deep", "rem_min": "sleep_rem",
    "light_min": "sleep_light", "awake_min": "sleep_awake", "score": "sleep_score", "efficiency": "sleep_efficiency",
}


def get(key: str) -> Metric | None:
    return METRICS.get(key)


def plausible(key: str, value: float | None) -> bool:
    m = METRICS.get(key)
    if m is None or value is None:
        return False
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if v != v:  # NaN
        return False
    if m.lo is not None and v < m.lo:
        return False
    if m.hi is not None and v > m.hi:
        return False
    return True


def catalog() -> list[dict]:
    return [{**asdict(m), "category_label": CATEGORIES[m.category]} for m in METRICS.values()]


def catalog_entry(key: str) -> dict | None:
    m = METRICS.get(key)
    return {**asdict(m), "category_label": CATEGORIES[m.category]} if m else None
