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
# Der Export hat je nach App-Sprache englische oder übersetzte Spaltennamen (und teils übersetzte Dateinamen),
# die Reihenfolge der Spalten ist aber immer gleich. Darum: erst nach Namen (Englisch/Deutsch) suchen, sonst nach Position.

CYCLE_COLS = {  # Feld: (Namen, Position)
    "start": (("Cycle start time", "Zyklus-Startzeit", "Zyklusbeginn", "Startzeit des Zyklus"), 0),
    "end": (("Cycle end time", "Zyklus-Endzeit", "Zyklusende", "Endzeit des Zyklus"), 1),
    "tz": (("Cycle timezone", "Zeitzone"), 2),
    "rec": (("Recovery score", "Erholung", "Recovery"), 3),
    "rhr": (("Resting heart rate", "Ruheherzfrequenz", "Ruhepuls"), 4),
    "hrv": (("Heart rate variability", "Herzfrequenzvariabilität", "HRV"), 5),
    "skin": (("Skin temp", "Hauttemperatur"), 6),
    "spo2": (("Blood oxygen", "Blutsauerstoff", "Sauerstoff"), 7),
    "strain": (("Day Strain", "Tagesbelastung", "Tages-Strain", "Belastung"), 8),
    "energy": (("Energy burned", "Verbrannte Energie", "Energieverbrauch", "Kalorien"), 9),
    "onset": (("Sleep onset", "Einschlafzeit", "Schlafbeginn", "Beginn des Schlafs"), 12),
    "wake": (("Wake onset", "Aufwachzeit", "Aufwachen", "Weckzeit"), 13),
    "perf": (("Sleep performance", "Schlafleistung"), 14),
    "resp": (("Respiratory rate", "Atemfrequenz"), 15),
    "asleep": (("Asleep duration", "Schlafdauer", "Dauer im Schlaf"), 16),
    "light": (("Light sleep duration", "Leichtschlaf"), 18),
    "deep": (("Deep (SWS) duration", "Tiefschlaf"), 19),
    "rem": (("REM duration", "REM"), 20),
    "awake": (("Awake duration", "Wach"), 21),
    "eff": (("Sleep efficiency", "Schlafeffizienz"), 24),
}
SLEEP_COLS = {
    "tz": (("Cycle timezone", "Zeitzone"), 2),
    "onset": (CYCLE_COLS["onset"][0], 3), "wake": (CYCLE_COLS["wake"][0], 4), "perf": (CYCLE_COLS["perf"][0], 5),
    "resp": (CYCLE_COLS["resp"][0], 6), "asleep": (CYCLE_COLS["asleep"][0], 7), "light": (CYCLE_COLS["light"][0], 9),
    "deep": (CYCLE_COLS["deep"][0], 10), "rem": (CYCLE_COLS["rem"][0], 11), "awake": (CYCLE_COLS["awake"][0], 12),
    "eff": (CYCLE_COLS["eff"][0], 15), "nap": (("Nap", "Nickerchen", "Schläfchen"), 17),
}
WORKOUT_COLS = {
    "tz": (("Cycle timezone", "Zeitzone"), 2),
    "start": (("Workout start time", "Trainingsstartzeit", "Trainingsbeginn", "Startzeit des Trainings", "Workout-Startzeit"), 3),
    "end": (("Workout end time", "Trainingsendzeit", "Trainingsende", "Endzeit des Trainings", "Workout-Endzeit"), 4),
    "dur": (("Duration", "Dauer"), 5),
    "name": (("Activity name", "Aktivitätsname", "Aktivität", "Sportart"), 6),
    "strain": (("Activity Strain", "Aktivitätsbelastung", "Belastung"), 7),
    "energy": (("Energy burned", "Verbrannte Energie", "Energieverbrauch", "Kalorien"), 8),
    "max": (("Max HR", "Max. HF", "Maximale Herzfrequenz", "Max. Herzfrequenz"), 9),
    "avg": (("Average HR", "Durchschnittliche HF", "Ø HF", "Durchschnittliche Herzfrequenz"), 10),
    "dist": (("Distance", "Distanz", "Strecke", "Entfernung"), 17),
    "alt": (("Altitude gain", "Höhengewinn", "Höhenmeter", "Anstieg"), 18),
}
ZONE_POS = [11, 12, 13, 14, 15]
EXPECTED = {"cycles": 26, "sleeps": 18, "workouts": 20}


def _cols(h: list[str], spec: dict, expected: int) -> dict:
    """Spaltennummer je Feld: Name (EN/DE), sonst feste Position, wenn die Datei die erwartete Spaltenzahl hat."""
    by_pos = len(h) >= expected
    out = {}
    for field, (names, pos) in spec.items():
        i = _col(h, *names)
        if i is None and by_pos:
            i = pos
        out[field] = i
    return out


def _kind(name: str, h: list[str]) -> str | None:
    """Welche WHOOP-Tabelle: nach Dateiname (EN/DE), sonst nach Spaltennamen, sonst nach Spaltenzahl."""
    n = name.lower()
    head = " ".join(h).lower()
    if "journal" in n or "tagebuch" in n:
        return None
    if "workout" in n or "training" in n or "workout start" in head or "trainingsst" in head:
        return "workouts"
    if "sleep" in n or "schlaf" in n.rsplit("/", 1)[-1] and "zykl" not in n:
        return "sleeps"
    if "cycle" in n or "zykl" in n or "physio" in n or "recovery score" in head or "erholung" in head:
        return "cycles"
    if "nap" in head or "nickerchen" in head:
        return "sleeps"
    return {26: "cycles", 25: "cycles", 18: "sleeps", 20: "workouts"}.get(len(h))


def whoop_time(s: str, tzs: str) -> datetime | None:
    """„2024-03-01 22:14:05“ (oder „01.03.2024 22:14:05“) in Ortszeit plus Zeitzone wie „UTC+01:00“ → UTC ohne Zone."""
    s = (s or "").strip()
    if not s:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(s.replace("T", " ").replace("Z", ""))
    except ValueError:
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y, %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%Y/%m/%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                pass
    if dt is None:
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


def _truthy(v: str) -> bool:
    return v.strip().lower() in ("true", "1", "yes", "ja", "wahr", "x")


def import_whoop(w: Writer, path: str, progress=lambda p: None, filename: str = "") -> dict:
    raw: list[tuple[str, bytes]] = []
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            raw = [(n, z.read(n)) for n in z.namelist() if n.lower().endswith(".csv")]
    else:
        with open(path, "rb") as f:
            raw = [(filename or "upload.csv", f.read())]
    tables: dict[str, tuple[list[str], list[list[str]]]] = {}
    for name, data in raw:
        h, rows = _rows(data)
        kind = _kind(name, h) if h else None
        if kind and kind not in tables:
            tables[kind] = (h, rows)
    if not tables:
        raise ArchiveError("Keine WHOOP-Daten gefunden. Erwartet wird die ZIP aus „Data Export“ "
                           "(Tabellen zu Zyklen, Schlaf und Trainings).")
    db = w.db
    acts = {int(a.start.timestamp() // 60): a.source_id for a in db.scalars(
        select(Activity).where(Activity.user_id == w.user_id, Activity.source == "whoop"))}
    nights = {int(s.start.timestamp() // 60): s.source_id for s in db.scalars(
        select(SleepSession).where(SleepSession.user_id == w.user_id, SleepSession.source == "whoop"))}
    stats = {"cycles": 0, "sleeps": 0, "workouts": 0, "merged": 0, "skipped_rows": 0}

    if "cycles" in tables:
        h, rows = tables["cycles"]
        c = _cols(h, CYCLE_COLS, EXPECTED["cycles"])
        skins: list[float] = []
        for row in rows:
            tzs = _get(row, c["tz"])
            wake = whoop_time(_get(row, c["wake"]), tzs) or whoop_time(_get(row, c["start"]), tzs)
            end = whoop_time(_get(row, c["end"]), tzs)
            if not wake:
                stats["skipped_rows"] += 1
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
            if "sleeps" not in tables and _sleep_row(w, c, row, nights, stats):
                stats["sleeps"] += 1
        progress(0.4)

    if "sleeps" in tables:
        h, rows = tables["sleeps"]
        c = _cols(h, SLEEP_COLS, EXPECTED["sleeps"])
        for row in rows:
            if _sleep_row(w, c, row, nights, stats):
                stats["sleeps"] += 1
        progress(0.7)

    if "workouts" in tables:
        h, rows = tables["workouts"]
        c = _cols(h, WORKOUT_COLS, EXPECTED["workouts"])
        zones = [_col(h, f"HR Zone {i}", f"HF-Zone {i}", f"Herzfrequenzzone {i}", f"Zone {i}") for i in range(1, 6)]
        if any(z is None for z in zones) and len(h) >= EXPECTED["workouts"]:
            zones = ZONE_POS
        for row in rows:
            tzs = _get(row, c["tz"])
            start, end = whoop_time(_get(row, c["start"]), tzs), whoop_time(_get(row, c["end"]), tzs)
            if not start:
                stats["skipped_rows"] += 1
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
    if not (stats["cycles"] or stats["sleeps"] or stats["workouts"]):
        raise ArchiveError("Die WHOOP-Tabellen wurden gefunden, aber keine Zeile war lesbar (Datumsformat?). "
                           "Bitte die erste Zeile einer der CSV-Dateien an den Support schicken.")
    progress(1.0)
    return stats


def _sleep_row(w: Writer, c: dict, row: list[str], nights: dict, stats: dict) -> bool:
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
        nap=_truthy(_get(row, c.get("nap"))) if c.get("nap") is not None else False,
    ))
    nights[int(start.timestamp() // 60)] = sid or f"export-{int(start.timestamp())}"
    return True
