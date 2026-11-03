"""Komplette Datenexporte von Strava und WHOOP einlesen (manueller Import statt oder zusätzlich zur Schnittstelle).

Strava: „Konto herunterladen“ (strava.com → Einstellungen → Mein Konto → Konto herunterladen) liefert eine ZIP mit
activities.csv und dem Ordner activities/ (FIT/GPX/TCX, oft .gz). Die Activity ID ist dieselbe wie über die
Schnittstelle, darum entstehen keine Doppelten, wenn Strava zusätzlich verbunden ist.

WHOOP: „Data Export“ in der App (Profil → Data Export) liefert eine ZIP mit physiological_cycles.csv, sleeps.csv und
workouts.csv. Einzelne CSV-Dateien daraus gehen auch. Schlaf und Trainings, die schon über die Schnittstelle da sind,
werden über die Startzeit erkannt und ergänzt statt verdoppelt.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..models import Activity, SleepSession
from ..store import ActivityIn, SleepIn, Writer
from . import parsers


class ArchiveError(ValueError):
    pass


def _num(v):
    if v is None:
        return None
    s = str(v).strip().replace(" ", "")
    if not s or s.lower() in ("nan", "none", "-", "--"):
        return None
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s):  # 1.234,5
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _rows(data: bytes) -> tuple[list[str], list[list[str]]]:
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    if not rows:
        return [], []
    return [h.strip() for h in rows[0]], rows[1:]


def _col(headers: list[str], *names: str, last: bool = False) -> int | None:
    """Spalte nach (Teil-)Namen, ohne Groß/klein. last=True: bei doppelten Spalten die letzte (Strava hat z. B. zweimal „Distance“)."""
    low = [h.lower() for h in headers]
    for n in names:
        n = n.lower()
        hits = [i for i, h in enumerate(low) if h == n] or [i for i, h in enumerate(low) if h.startswith(n)]
        if hits:
            return hits[-1] if last else hits[0]
    return None


def _get(row, i):
    return row[i].strip() if i is not None and i < len(row) else ""


# ---------- Strava ----------

_EN_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_DE_MONTHS = {"jan": 1, "feb": 2, "mär": 3, "mrz": 3, "apr": 4, "mai": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dez": 12}


def strava_date(s: str) -> datetime | None:
    """„Jan 5, 2024, 7:31:12 AM“, „05.01.2024, 07:31:12“, „5. Jan. 2024, 07:31:12“ oder ISO; Strava exportiert in UTC."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%b %d, %Y, %I:%M:%S %p", "%b %d, %Y, %H:%M:%S", "%d.%m.%Y, %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ", "%d/%m/%Y, %H:%M:%S", "%m/%d/%Y, %I:%M:%S %p"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    m = re.match(r"(\d{1,2})\.?\s*([A-Za-zä]{3})[a-zä]*\.?\s+(\d{4}),?\s+(\d{1,2}):(\d{2}):(\d{2})", s)
    if m:
        mon = _DE_MONTHS.get(m.group(2).lower()) or _EN_MONTHS.get(m.group(2).lower())
        if mon:
            return datetime(int(m.group(3)), mon, int(m.group(1)), int(m.group(4)), int(m.group(5)), int(m.group(6)))
    return None


def _duration(s: str) -> float | None:
    if ":" in (s or ""):
        parts = [_num(p) or 0 for p in s.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return _num(s)


def import_strava(w: Writer, path: str, progress=lambda p: None) -> dict:
    if not zipfile.is_zipfile(path):
        with open(path, "rb") as f:
            data = f.read()
        if b"Activity ID" in data[:2000] or "Aktivitäts-ID".encode() in data[:2000]:
            return _strava_csv(w, data, None, progress)
        raise ArchiveError("Das ist keine Strava-ZIP. Erwartet wird die Datei aus „Konto herunterladen“.")
    with zipfile.ZipFile(path) as z:
        names = {n.lower(): n for n in z.namelist()}
        csv_name = next((names[n] for n in names if n.endswith("activities.csv")), None)
        if not csv_name:
            raise ArchiveError("In der ZIP fehlt activities.csv. Ist das der Export aus „Konto herunterladen“?")
        return _strava_csv(w, z.read(csv_name), z, progress, names)


def _strava_csv(w: Writer, data: bytes, z: zipfile.ZipFile | None, progress, names: dict | None = None) -> dict:
    h, rows = _rows(data)
    c = {
        "id": _col(h, "Activity ID", "Aktivitäts-ID"), "date": _col(h, "Activity Date", "Aktivitätsdatum"),
        "name": _col(h, "Activity Name", "Name der Aktivität", "Aktivitätsname"), "type": _col(h, "Activity Type", "Aktivitätsart", "Aktivitätstyp"),
        "elapsed": _col(h, "Elapsed Time", "Verstrichene Zeit", last=True), "moving": _col(h, "Moving Time", "Bewegungszeit"),
        "dist": _col(h, "Distance", "Distanz", last=True), "elev": _col(h, "Elevation Gain", "Höhenmeter", "Höhenunterschied"),
        "avg_hr": _col(h, "Average Heart Rate", "Durchschnittliche Herzfrequenz"), "max_hr": _col(h, "Max Heart Rate", "Max. Herzfrequenz", last=True),
        "watts": _col(h, "Average Watts", "Durchschnittliche Watt"), "cal": _col(h, "Calories", "Kalorien"),
        "effort": _col(h, "Relative Effort", "Relativer Aufwand"), "file": _col(h, "Filename", "Dateiname"),
    }
    if c["id"] is None or c["date"] is None:
        raise ArchiveError("activities.csv hat nicht die erwarteten Spalten (Activity ID, Activity Date).")
    dist_two = sum(1 for x in h if x.lower() in ("distance", "distanz")) > 1  # zweite Spalte in Metern
    stats = {"activities": 0, "with_track": 0, "files_unreadable": 0, "skipped": 0}
    for i, row in enumerate(rows):
        if i % 20 == 0:
            progress(i / max(1, len(rows)))
        aid = _get(row, c["id"])
        start = strava_date(_get(row, c["date"]))
        if not aid or not start:
            stats["skipped"] += 1
            continue
        dist = _num(_get(row, c["dist"]))
        if dist is not None and not dist_two:
            dist *= 1000  # nur eine Spalte: in km
        a = ActivityIn(
            source_id=aid, start=start, sport_raw=_get(row, c["type"]) or None, name=_get(row, c["name"]) or None,
            duration_s=_duration(_get(row, c["elapsed"])), moving_s=_duration(_get(row, c["moving"])), distance_m=dist,
            elevation_m=_num(_get(row, c["elev"])), avg_hr=_num(_get(row, c["avg_hr"])), max_hr=_num(_get(row, c["max_hr"])),
            avg_power=_num(_get(row, c["watts"])), calories=_num(_get(row, c["cal"])), load=_num(_get(row, c["effort"])),
        )
        fname = _get(row, c["file"])
        if z is not None and fname and names:
            key = fname.lower().lstrip("./")
            real = names.get(key) or next((v for k, v in names.items() if k.endswith("/" + key)), None)
            if real:
                try:
                    p = parsers.parse_activity_file(real, z.read(real))
                    d = p.details or {}
                    a.start = p.start or a.start
                    a.polyline = p.polyline
                    a.distance_m = a.distance_m or (p.distance_km * 1000 if p.distance_km else None)
                    a.moving_s = a.moving_s or p.moving_time_s
                    a.elevation_m = a.elevation_m or p.elevation_m
                    a.avg_hr = a.avg_hr or d.get("avg_hr")
                    a.max_hr = a.max_hr or d.get("max_hr")
                    a.avg_power = a.avg_power or d.get("avg_power")
                    if d.get("profile"):
                        a.details = {"profile": d.get("profile"), "max_speed": d.get("max_speed")}
                    if p.polyline:
                        stats["with_track"] += 1
                except Exception:
                    stats["files_unreadable"] += 1
        w.activity(a)
        stats["activities"] += 1
    progress(1.0)
    return stats


# ---------- WHOOP ----------

def whoop_time(s: str, tzs: str) -> datetime | None:
    """„2024-03-01 22:14:05“ in Ortszeit plus Spalte „Cycle timezone“ wie „UTC+01:00“ → UTC ohne Zone."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("T", " ").replace("Z", ""))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    m = re.search(r"([+-])(\d{1,2}):?(\d{2})?", tzs or "")
    off = timedelta(0)
    if m:
        off = timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0)) * (1 if m.group(1) == "+" else -1)
    return dt - off


def _near(index: dict[int, str], start: datetime, minutes: int = 10) -> str | None:
    """Vorhandener Eintrag (über die Schnittstelle) mit fast gleicher Startzeit."""
    key = int(start.timestamp() // 60)
    for d in range(-minutes, minutes + 1):
        if key + d in index:
            return index[key + d]
    return None


def import_whoop(w: Writer, path: str, progress=lambda p: None, filename: str = "") -> dict:
    files: dict[str, bytes] = {}
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                base = n.rsplit("/", 1)[-1].lower()
                if base in ("physiological_cycles.csv", "sleeps.csv", "workouts.csv"):
                    files[base] = z.read(n)
    else:
        with open(path, "rb") as f:
            data = f.read()
        head = data[:3000].decode("utf-8-sig", errors="replace").lower()
        if "workout start time" in head:
            files["workouts.csv"] = data
        elif "recovery score" in head:
            files["physiological_cycles.csv"] = data
        elif "sleep onset" in head:
            files["sleeps.csv"] = data
    if not files:
        raise ArchiveError("Keine WHOOP-Daten gefunden. Erwartet wird die ZIP aus „Data Export“ (physiological_cycles.csv, sleeps.csv, workouts.csv).")
    db = w.db
    acts = {int(a.start.timestamp() // 60): a.source_id for a in db.scalars(
        select(Activity).where(Activity.user_id == w.user_id, Activity.source == "whoop"))}
    nights = {int(s.start.timestamp() // 60): s.source_id for s in db.scalars(
        select(SleepSession).where(SleepSession.user_id == w.user_id, SleepSession.source == "whoop"))}
    stats = {"cycles": 0, "sleeps": 0, "workouts": 0, "merged": 0}
    done_sleep_from_cycles = "sleeps.csv" in files

    if "physiological_cycles.csv" in files:
        h, rows = _rows(files["physiological_cycles.csv"])
        c = {k: _col(h, *v) for k, v in {
            "start": ("Cycle start time",), "end": ("Cycle end time",), "tz": ("Cycle timezone",), "rec": ("Recovery score",),
            "rhr": ("Resting heart rate",), "hrv": ("Heart rate variability",), "skin": ("Skin temp",), "spo2": ("Blood oxygen",),
            "strain": ("Day Strain",), "energy": ("Energy burned",), "onset": ("Sleep onset",), "wake": ("Wake onset",),
            "resp": ("Respiratory rate",)}.items()}
        skins: list[float] = []
        for i, row in enumerate(rows):
            tzs = _get(row, c["tz"])
            wake = whoop_time(_get(row, c["wake"]), tzs) or whoop_time(_get(row, c["start"]), tzs)
            end = whoop_time(_get(row, c["end"]), tzs)
            if not wake:
                continue
            w.sample("recovery", wake, _num(_get(row, c["rec"])))
            w.sample("resting_hr", wake, _num(_get(row, c["rhr"])))
            w.sample("hrv", wake, _num(_get(row, c["hrv"])))
            w.sample("spo2", wake, _num(_get(row, c["spo2"])))
            w.sample("respiratory_rate", wake, _num(_get(row, c["resp"])))
            skin = _num(_get(row, c["skin"]))
            if skin is not None:
                if len(skins) >= 5:  # Abweichung vom eigenen Mittel der letzten Wochen, wie in der App
                    w.sample("skin_temp_dev", wake, skin - sum(skins[-28:]) / len(skins[-28:]))
                skins.append(skin)
            if end:
                w.sample("strain", end, _num(_get(row, c["strain"])))
                w.sample("total_energy", end, _num(_get(row, c["energy"])))
            stats["cycles"] += 1
            if not done_sleep_from_cycles:
                if _sleep_row(w, h, row, nights, stats):
                    stats["sleeps"] += 1
        progress(0.4)

    if "sleeps.csv" in files:
        h, rows = _rows(files["sleeps.csv"])
        for row in rows:
            if _sleep_row(w, h, row, nights, stats):
                stats["sleeps"] += 1
        progress(0.7)

    if "workouts.csv" in files:
        h, rows = _rows(files["workouts.csv"])
        c = {k: _col(h, *v) for k, v in {
            "tz": ("Cycle timezone",), "start": ("Workout start time",), "end": ("Workout end time",), "dur": ("Duration",),
            "name": ("Activity name",), "strain": ("Activity Strain",), "energy": ("Energy burned",), "max": ("Max HR",),
            "avg": ("Average HR",), "dist": ("Distance",), "alt": ("Altitude gain",)}.items()}
        zones = [_col(h, f"HR Zone {i}") for i in range(1, 6)]
        for row in rows:
            tzs = _get(row, c["tz"])
            start, end = whoop_time(_get(row, c["start"]), tzs), whoop_time(_get(row, c["end"]), tzs)
            if not start:
                continue
            sid = _near(acts, start)
            if sid:
                stats["merged"] += 1
            dur = _num(_get(row, c["dur"]))
            duration = dur * 60 if dur else ((end - start).total_seconds() if end else None)
            pct = [_num(_get(row, z)) for z in zones]
            details = {"hr_zones": [0] + [round((p or 0) / 100 * duration) for p in pct]} if duration and any(pct) else None
            name = _get(row, c["name"])
            w.activity(ActivityIn(
                source_id=sid or f"export-{int(start.timestamp())}", start=start, sport_raw=name or None, name=name or None,
                duration_s=duration, distance_m=_num(_get(row, c["dist"])), elevation_m=_num(_get(row, c["alt"])),
                calories=_num(_get(row, c["energy"])), avg_hr=_num(_get(row, c["avg"])), max_hr=_num(_get(row, c["max"])),
                load=_num(_get(row, c["strain"])), details=details,
            ))
            stats["workouts"] += 1
    progress(1.0)
    return stats


def _sleep_row(w: Writer, h: list[str], row: list[str], nights: dict, stats: dict) -> bool:
    c = {k: _col(h, *v) for k, v in {
        "tz": ("Cycle timezone",), "onset": ("Sleep onset",), "wake": ("Wake onset",), "perf": ("Sleep performance",),
        "asleep": ("Asleep duration",), "light": ("Light sleep duration",), "deep": ("Deep (SWS) duration", "Deep"),
        "rem": ("REM duration",), "awake": ("Awake duration",), "eff": ("Sleep efficiency",), "nap": ("Nap",)}.items()}
    tzs = _get(row, c["tz"])
    start, end = whoop_time(_get(row, c["onset"]), tzs), whoop_time(_get(row, c["wake"]), tzs)
    if not start or not end:
        return False
    sid = _near(nights, start)
    if sid:
        stats["merged"] += 1
    w.sleep(SleepIn(
        source_id=sid or f"export-{int(start.timestamp())}", start=start, end=end, asleep_min=_num(_get(row, c["asleep"])),
        deep_min=_num(_get(row, c["deep"])), rem_min=_num(_get(row, c["rem"])), light_min=_num(_get(row, c["light"])),
        awake_min=_num(_get(row, c["awake"])), score=_num(_get(row, c["perf"])), efficiency=_num(_get(row, c["eff"])),
        nap=_get(row, c["nap"]).lower() in ("true", "1", "yes", "ja"),
    ))
    nights[int(start.timestamp() // 60)] = sid or f"export-{int(start.timestamp())}"
    return True
