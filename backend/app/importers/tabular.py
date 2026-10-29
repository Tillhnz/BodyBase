"""CSV-Import (Waagen-Apps, Cronometer, Tabellen) und das allgemeine JSON-Format für eigene Skripte."""
from __future__ import annotations

import csv
import io
import re

from .. import metrics as M
from ..store import ActivityIn, SleepIn, Writer
from ..timeutil import parse_date, parse_iso
from .apple import convert

# Spaltennamen -> Metrik (klein geschrieben, ohne Einheit in Klammern)
SYNONYMS = {
    "weight": ["weight", "gewicht", "body weight", "körpergewicht", "masse", "weight kg", "poids"],
    "body_fat": ["body fat", "körperfett", "fat", "fett %", "bodyfat", "body fat %", "fat ratio", "körperfettanteil"],
    "muscle_mass": ["muscle mass", "muskelmasse", "skeletal muscle", "muskeln"],
    "bone_mass": ["bone mass", "knochenmasse", "bone"],
    "body_water": ["body water", "körperwasser", "water %", "wasser"],
    "bmi": ["bmi"],
    "visceral_fat": ["visceral fat", "viszeralfett"],
    "waist": ["waist", "taille", "bauchumfang", "taillenumfang"],
    "resting_hr": ["resting hr", "resting heart rate", "ruhepuls", "rhr"],
    "heart_rate": ["heart rate", "puls", "pulse", "hr"],
    "hrv": ["hrv", "herzfrequenzvariabilität", "rmssd"],
    "bp_systolic": ["systolic", "systolisch", "sys"],
    "bp_diastolic": ["diastolic", "diastolisch", "dia"],
    "spo2": ["spo2", "sauerstoff", "oxygen saturation"],
    "steps": ["steps", "schritte"],
    "active_energy": ["active calories", "active energy", "aktive kalorien", "activity calories"],
    "calories_in": ["energy", "calories", "kalorien", "energy (kcal)", "kcal", "calories consumed", "energie"],
    "protein": ["protein", "eiweiß", "eiweiss"],
    "carbs": ["carbs", "carbohydrates", "kohlenhydrate", "net carbs"],
    "fat": ["fat (g)", "total fat", "fett"],
    "water": ["water (ml)", "trinkmenge", "wasser (ml)"],
    "caffeine": ["caffeine", "koffein"],
    "sleep_duration": ["sleep", "schlaf", "sleep minutes", "schlafdauer"],
    "glucose": ["glucose", "blutzucker", "blood glucose"],
    "vo2max": ["vo2max", "vo2 max"],
}
DATE_COLS = ["date", "datum", "time", "zeit", "timestamp", "day", "tag", "date/time", "datetime", "messzeitpunkt"]
LONG_METRIC_COLS = ["metric", "metrik", "type", "messgröße"]
LONG_VALUE_COLS = ["value", "wert"]


def _clean(h: str) -> tuple[str, str]:
    h = (h or "").strip().lower().lstrip("﻿")
    unit = ""
    m = re.search(r"[\(\[]([^\)\]]+)[\)\]]", h)
    if m:
        unit = m.group(1).strip()
    base = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", h).strip()
    return base, unit


def _match(header: str) -> tuple[str | None, str]:
    base, unit = _clean(header)
    full = header.strip().lower()
    if base in M.METRICS:
        return base, unit
    for metric, names in SYNONYMS.items():
        if full in names or base in names:
            # „fat (g)“ ist Ernährung, „fat (%)“ Körperfett
            if metric == "body_fat" and unit == "g":
                return "fat", unit
            return metric, unit
    return None, unit


def _num(s: str) -> float | None:
    if s is None:
        return None
    s = str(s).strip().replace(" ", "").replace(" ", "")
    if not s or s in ("-", "--", "n/a"):
        return None
    s = re.sub(r"[^\d,.\-]", "", s)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _unit_convert(metric: str, value: float, unit: str) -> float | None:
    u = unit.lower()
    if metric == "sleep_duration" and u in ("h", "hours", "std", "stunden"):
        return value * 60
    if metric == "body_fat" and value <= 1 and u in ("", "%"):
        return value * 100 if value < 1 else value
    return convert(metric, value, u)


def sniff(text: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        class D(csv.excel):
            delimiter = ";" if text[:4096].count(";") > text[:4096].count(",") else ","
        return D


def import_csv(w: Writer, data: bytes) -> dict:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    reader = csv.reader(io.StringIO(text), sniff(text))
    rows = list(reader)
    if len(rows) < 2:
        raise ValueError("Die CSV-Datei enthält keine Daten.")
    header = rows[0]
    lower = [_clean(h)[0] for h in header]
    date_idx = next((i for i, h in enumerate(lower) if h in DATE_COLS), 0)
    metric_idx = next((i for i, h in enumerate(lower) if h in LONG_METRIC_COLS), None)
    value_idx = next((i for i, h in enumerate(lower) if h in LONG_VALUE_COLS), None)
    used: dict[str, str] = {}
    if metric_idx is not None and value_idx is not None:  # langes Format: Zeit, Metrik, Wert
        for r in rows[1:]:
            if len(r) <= max(date_idx, metric_idx, value_idx):
                continue
            metric = r[metric_idx].strip()
            if metric not in M.METRICS:
                metric, _ = _match(metric)
            if not metric:
                continue
            _write(w, metric, r[date_idx], _num(r[value_idx]))
            used[metric] = header[value_idx]
        return {"columns": used}
    columns = []
    for i, h in enumerate(header):
        if i == date_idx:
            continue
        metric, unit = _match(h)
        if metric:
            columns.append((i, metric, unit))
            used[metric] = h
    if not columns:
        raise ValueError("Keine bekannte Spalte gefunden. Erwartet werden z. B. „Datum“ und „Gewicht“, „Schritte“, „Ruhepuls“.")
    for r in rows[1:]:
        if len(r) <= date_idx:
            continue
        for i, metric, unit in columns:
            if i < len(r):
                v = _num(r[i])
                if v is not None:
                    _write(w, metric, r[date_idx], _unit_convert(metric, v, unit))
    return {"columns": used}


def _write(w: Writer, metric: str, when: str, value: float | None) -> None:
    if value is None:
        return
    when = (when or "").strip()
    # deutsches Datum 29.10.2026 [07:30]
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[ T,]+(\d{1,2}):(\d{2}))?", when)
    if m:
        d, mo, y, hh, mi = m.groups()
        when = f"{y}-{int(mo):02d}-{int(d):02d}" + (f" {int(hh):02d}:{mi}:00" if hh else "")
    if M.METRICS[metric].agg == "sum" or len(when) <= 10:
        w.daily(metric, parse_date(when), value)
    else:
        w.sample(metric, parse_iso(when), value)


# ---------- Allgemeines JSON-Format ----------

def ingest_json(w: Writer, payload: dict) -> None:
    """{"samples": [{"metric": "weight", "value": 80.1, "time": "…" | "date": "YYYY-MM-DD", "unit": "kg"}],
        "activities": [{"id", "start", "sport", "name", "duration_s", "distance_m", "calories", "avg_hr", …}],
        "sleep": [{"id", "start", "end", "asleep_min", "deep_min", "rem_min", "light_min", "awake_min", "score"}]}"""
    for s in payload.get("samples", []) or []:
        metric = s.get("metric")
        if metric not in M.METRICS:
            continue
        value = s.get("value")
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if s.get("unit"):
            value = convert(metric, value, s.get("unit"))
        if s.get("date") and not s.get("time"):
            w.daily(metric, parse_date(s.get("date")), value)
        else:
            w.sample(metric, parse_iso(s.get("time")), value)
    for a in payload.get("activities", []) or []:
        start = parse_iso(a.get("start"))
        if not start:
            continue
        w.activity(ActivityIn(
            source_id=str(a.get("id") or start.isoformat()), start=start, sport_raw=a.get("sport"), name=a.get("name"),
            duration_s=a.get("duration_s"), moving_s=a.get("moving_s"), distance_m=a.get("distance_m"),
            elevation_m=a.get("elevation_m"), calories=a.get("calories"), avg_hr=a.get("avg_hr"), max_hr=a.get("max_hr"),
            avg_power=a.get("avg_power"), load=a.get("load"),
        ))
    for s in payload.get("sleep", []) or []:
        start, end = parse_iso(s.get("start")), parse_iso(s.get("end"))
        if not start or not end:
            continue
        w.sleep(SleepIn(source_id=str(s.get("id") or start.isoformat()), start=start, end=end, asleep_min=s.get("asleep_min"),
                        deep_min=s.get("deep_min"), rem_min=s.get("rem_min"), light_min=s.get("light_min"),
                        awake_min=s.get("awake_min"), score=s.get("score"), nap=bool(s.get("nap"))))
