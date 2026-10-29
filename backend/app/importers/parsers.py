"""Einlesen von Trainingsdateien (GPX, TCX, FIT; auch als .gz) und Berechnung der Kennzahlen.

Dieses Modul kennt weder die Datenbank noch das Web-Framework und lässt sich daher einzeln testen.
"""
from __future__ import annotations

import gzip
import io
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

from . import polyline

MAX_POLYLINE_POINTS = 600
MAX_DECOMPRESSED_BYTES = 200 * 1024 * 1024
PAUSE_GAP_S = 30          # größere Lücken zwischen Punkten zählen als Pause
MIN_MOVING_SPEED = 0.5    # m/s, darunter gilt als Stillstand
MAX_PLAUSIBLE_SPEED = 40  # m/s (144 km/h): schnellere Sprünge sind GPS-Fehler
ELEVATION_THRESHOLD_M = 3.0

CYCLING_HINTS = ("ride", "cycl", "bik", "velo", "vélo", "rad", "cicl", "bici", "gravel")  # auch deutsche, französische, spanische Typen


class ParseError(Exception):
    """Datei konnte nicht gelesen werden; die Meldung ist für Nutzer gedacht."""


@dataclass
class Point:
    lat: float | None = None
    lng: float | None = None
    ele: float | None = None
    time: datetime | None = None
    dist: float | None = None  # kumulierte Strecke in m laut Datei
    hr: float | None = None    # Herzfrequenz (bpm)
    cad: float | None = None   # Trittfrequenz (U/min)
    pwr: float | None = None   # Leistung (Watt)


@dataclass
class ParsedActivity:
    start: datetime  # UTC, ohne Zeitzone gespeichert
    distance_km: float
    moving_time_s: int
    elevation_m: float
    polyline: str | None
    start_lat: float | None
    start_lng: float | None
    sport: str | None
    name: str | None
    details: dict | None = None  # Kennzahlen und Verlaufsdaten für die Einzelauswertung


# ---------- Hilfsfunktionen ----------

def is_cycling(sport: str | None) -> bool:
    """Unbekannte Sportart (None) zählt als Radfahrt, damit nichts verloren geht."""
    if not sport:
        return True
    s = sport.lower()
    return any(h in s for h in CYCLING_HINTS)


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$")


def parse_time(value: str) -> datetime | None:
    """ISO-8601-Zeit -> UTC ohne Zeitzone. Gibt None zurück, wenn das Format unbekannt ist."""
    m = _TIME_RE.match((value or "").strip())
    if not m:
        return None
    base, frac, tz = m.groups()
    frac = (frac or ".0")[1:7].ljust(6, "0")
    tz = tz or "Z"
    if tz == "Z":
        tz = "+00:00"
    elif ":" not in tz:
        tz = tz[:3] + ":" + tz[3:]
    try:
        dt = datetime.fromisoformat(f"{base.replace(' ', 'T')}.{frac}{tz}")
    except ValueError:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _valid_coord(lat: float | None, lng: float | None) -> bool:
    return (
        lat is not None and lng is not None
        and -90 <= lat <= 90 and -180 <= lng <= 180
        and not (lat == 0 and lng == 0)
    )


def _segment_m(a: Point, b: Point) -> float:
    if a.dist is not None and b.dist is not None:
        return max(b.dist - a.dist, 0.0)
    if _valid_coord(a.lat, a.lng) and _valid_coord(b.lat, b.lng):
        return haversine_m(a.lat, a.lng, b.lat, b.lng)
    return 0.0


PROFILE_BINS = 300


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round(v: float | None, n: int = 1) -> float | None:
    return None if v is None else round(v, n)


POWER_CURVE_SECONDS = (5, 30, 60, 300, 1200, 3600)
DETAILS_VERSION = 2  # 2 = Sekundenauswertung (Leistungskurve, Verteilungen, NP); ältere Fahrten haben nur das Profil
MAX_ANALYSIS_SECONDS = 16 * 3600


def per_second(points: list[Point], attr: str) -> list[float | None]:
    """Messwert auf 1 Hz gebracht. Lücken über 10 s (Pause, Funkloch) und fehlende Werte sind None."""
    pts = [p for p in points if p.time is not None and getattr(p, attr) is not None]
    if len(pts) < 10:
        return []
    t0 = pts[0].time
    series: list[float | None] = []
    for i, p in enumerate(pts):
        t = int((p.time - t0).total_seconds())
        if t < 0:
            continue
        nxt = int((pts[i + 1].time - t0).total_seconds()) if i + 1 < len(pts) else t + 1
        span = max(1, nxt - t)
        while len(series) < t:
            series.append(None)
        if span <= 10:
            series.extend([float(getattr(p, attr))] * span)
        else:
            series.append(float(getattr(p, attr)))
            series.extend([None] * (span - 1))
        if len(series) > MAX_ANALYSIS_SECONDS:
            return []
    return series


def power_curve(points: list[Point], series: list[float | None] | None = None) -> dict | None:
    """Beste Durchschnittsleistung über feste Zeiträume (Sekunden -> Watt) aus den Rohpunkten, auf 1 Hz gebracht.

    Lücken über 10 s (Pausen, Funkloch) zählen als 0 W, damit eine Pause keine Spitzenwerte vortäuscht.
    """
    raw = per_second(points, "pwr") if series is None else series
    if not raw:
        return None
    vals = [max(0.0, v) if v is not None else 0.0 for v in raw]
    acc = [0.0]
    for v in vals:
        acc.append(acc[-1] + v)
    out = {}
    for d in POWER_CURVE_SECONDS:
        if len(vals) >= d:
            best = max(acc[i + d] - acc[i] for i in range(0, len(vals) - d + 1))
            out[str(d)] = round(best / d)
    return out or None


def _hist(series: list[float | None], width: int, cap: int, include_zero: bool = True) -> dict[str, int] | None:
    """Sekunden je Wertebereich (untere Grenze -> Sekunden). Werte über `cap` zählen in den obersten Bereich."""
    out: dict[int, int] = {}
    for v in series:
        if v is None or (v <= 0 and not include_zero):
            continue
        k = int(min(max(v, 0.0), cap) // width * width)
        out[k] = out.get(k, 0) + 1
    return {str(k): n for k, n in sorted(out.items())} or None


def _normalized_power(series: list[float | None]) -> float | None:
    """Normalisierte Leistung: 4. Wurzel aus dem Mittel der 4. Potenz des 30-s-Schnitts (Pausen als 0 W)."""
    vals = [max(0.0, v) if v is not None else 0.0 for v in series]
    if len(vals) < 90:
        return None
    acc = [0.0]
    for v in vals:
        acc.append(acc[-1] + v)
    roll = [(acc[i + 30] - acc[i]) / 30 for i in range(len(vals) - 29)]
    return (sum(x ** 4 for x in roll) / len(roll)) ** 0.25


def second_by_second(points: list[Point]) -> dict:
    """Kennzahlen, die den Sekundenverlauf brauchen: Leistung (NP, Arbeit, Verteilung), Puls- und Frequenzverteilung, Entkopplung."""
    out: dict = {}
    pw, hr, cd = per_second(points, "pwr"), per_second(points, "hr"), per_second(points, "cad")
    if pw:
        valid = [v for v in pw if v is not None]
        out["pc"] = power_curve(points, pw)
        out["ph"] = _hist(pw, 10, 1500)
        np_ = _normalized_power(pw)
        out["np"] = round(np_) if np_ else None
        out["kj"] = round(sum(max(0.0, v) for v in valid) / 1000)
        out["pt"] = len(valid)  # Sekunden mit Leistungswert
    hr = [v if v is None or v > 0 else None for v in hr]
    if hr:
        out["hh"] = _hist(hr, 5, 250)
    if cd:
        out["ch"] = _hist(cd, 10, 200)
    # Entkopplung: Verhältnis Leistung zu Puls in der ersten und zweiten Hälfte
    if pw and hr:
        n = min(len(pw), len(hr))
        pairs = [(pw[i], hr[i]) for i in range(n) if pw[i] is not None and hr[i] is not None]
        if len(pairs) >= 2400:
            half = len(pairs) // 2
            def ef(chunk):
                return (sum(a for a, _ in chunk) / len(chunk)) / (sum(b for _, b in chunk) / len(chunk))
            e1, e2 = ef(pairs[:half]), ef(pairs[half:])
            if e1 > 0:
                out["dec"] = round((e1 - e2) / e1 * 100, 1)
    return {k: v for k, v in out.items() if v is not None}


def build_details(points: list[Point], cum: list[float], segs: list[tuple[float, float]], total_m: float) -> dict | None:
    """Kennzahlen und ein auf ca. 300 Stützpunkte verdichteter Verlauf (Höhe, Tempo, Puls, Frequenz, Leistung).

    cum[i] ist die Strecke in m bis zum Punkt i, segs enthält (Meter, Sekunden) gültiger Teilstücke.
    """
    if total_m <= 0 or len(points) < 2:
        return None
    timed = [p.time for p in points if p.time]
    elapsed = (timed[-1] - timed[0]).total_seconds() if len(timed) >= 2 else None

    def vals(attr: str) -> list[float]:
        return [getattr(p, attr) for p in points if getattr(p, attr) is not None]

    eles, hrs, pwrs = vals("ele"), [v for v in vals("hr") if v > 0], vals("pwr")
    cads = [v for v in vals("cad") if v > 0]  # Ausrollen (0) zählt nicht in den Schnitt

    # höchstes Tempo: gleitender Schnitt über 5 gültige Teilstücke, damit einzelne Ausreißer nicht zählen
    max_speed = None
    win = 5
    for i in range(0, max(0, len(segs) - win + 1)):
        m = sum(x for x, _ in segs[i:i + win])
        t = sum(y for _, y in segs[i:i + win])
        if t >= 3:
            v = m / t * 3.6
            if max_speed is None or v > max_speed:
                max_speed = v

    n = PROFILE_BINS
    bins: dict[int, dict] = {}
    for i, p in enumerate(points):
        b = min(n - 1, int(cum[i] / total_m * n))
        d = bins.setdefault(b, {"ele": [], "hr": [], "cad": [], "pwr": [], "m": 0.0, "t": 0.0, "end": 0.0, "ll": None})
        if p.ele is not None:
            d["ele"].append(p.ele)
        if p.hr is not None and p.hr > 0:
            d["hr"].append(p.hr)
        if p.cad is not None:
            d["cad"].append(p.cad)
        if p.pwr is not None:
            d["pwr"].append(p.pwr)
        d["end"] = cum[i]
        if _valid_coord(p.lat, p.lng):
            d["ll"] = (p.lat, p.lng)
    # Zeit und Strecke je Abschnitt aus den Teilstücken
    prev_i = None
    for i, p in enumerate(points):
        if prev_i is not None and p.time and points[prev_i].time:
            dt = (p.time - points[prev_i].time).total_seconds()
            seg = cum[i] - cum[prev_i]
            if 0 < dt <= PAUSE_GAP_S:
                b = min(n - 1, int(cum[i] / total_m * n))
                bins[b]["m"] += seg
                bins[b]["t"] += dt
        prev_i = i

    keys = sorted(bins)
    profile = {"d": [], "e": [], "s": [], "h": [], "c": [], "p": []}
    ll = []
    for k in keys:
        d = bins[k]
        profile["d"].append(round(d["end"] / 1000, 2))
        profile["e"].append(_round(_avg(d["ele"])))
        profile["s"].append(_round(d["m"] / d["t"] * 3.6) if d["t"] > 0 else None)
        profile["h"].append(_round(_avg(d["hr"]), 0))
        profile["c"].append(_round(_avg(d["cad"]), 0))
        profile["p"].append(_round(_avg(d["pwr"]), 0))
        if d["ll"]:
            ll.append(d["ll"])
    for key in ("e", "s", "h", "c", "p"):
        if all(v is None for v in profile[key]):
            profile[key] = None
    # Position je Stützpunkt für die Verknüpfung von Diagramm und Karte (nur wenn jeder Punkt eine hat)
    profile["ll"] = polyline.encode(ll) if len(ll) == len(keys) else None

    return {
        "elapsed_s": int(elapsed) if elapsed is not None else None,
        "max_speed": _round(max_speed),
        "ele_max": _round(max(eles)) if eles else None,
        "ele_min": _round(min(eles)) if eles else None,
        "avg_hr": _round(_avg(hrs), 0),
        "max_hr": _round(max(hrs), 0) if hrs else None,
        "avg_cadence": _round(_avg(cads), 0),
        "avg_power": _round(_avg(pwrs), 0),
        "max_power": _round(max(pwrs), 0) if pwrs else None,
        **(second_by_second(points) if (pwrs or hrs or cads) else {}),
        "v": DETAILS_VERSION,
        "profile": profile,
    }


def summarize(
    points: list[Point],
    *,
    sport: str | None = None,
    name: str | None = None,
    session: dict | None = None,
) -> ParsedActivity:
    """Berechnet Start, Strecke, Bewegungszeit, Höhenmeter und die gekürzte Strecke."""
    timed = [p for p in points if p.time]
    start = timed[0].time if timed else (session or {}).get("start_time")
    if start is None:
        raise ParseError(
            "Die Datei enthält keine Zeitstempel. Vermutlich ist es eine geplante Route und keine gefahrene Strecke."
        )

    dist_m = 0.0
    moving = 0.0
    gain = 0.0
    ref_ele: float | None = None
    prev: Point | None = None
    cum: list[float] = []
    segs: list[tuple[float, float]] = []
    for p in points:
        if p.ele is not None:
            if ref_ele is None:
                ref_ele = p.ele
            elif p.ele - ref_ele >= ELEVATION_THRESHOLD_M:
                gain += p.ele - ref_ele
                ref_ele = p.ele
            elif ref_ele - p.ele >= ELEVATION_THRESHOLD_M:
                ref_ele = p.ele
        if prev is not None:
            seg = _segment_m(prev, p)
            dt = (p.time - prev.time).total_seconds() if p.time and prev.time else None
            if dt is not None and dt > 0 and seg / dt > MAX_PLAUSIBLE_SPEED:
                seg = 0.0  # GPS-Sprung
            dist_m += seg
            if dt is not None and 0 < dt <= PAUSE_GAP_S and seg / dt >= MIN_MOVING_SPEED:
                moving += dt
            if dt is not None and 0 < dt <= PAUSE_GAP_S:
                segs.append((seg, dt))
        cum.append(dist_m)
        prev = p

    if session:
        if session.get("total_distance"):
            dist_m = float(session["total_distance"])
        if session.get("total_timer_time"):
            moving = float(session["total_timer_time"])
        if session.get("total_ascent") is not None:
            gain = float(session["total_ascent"])

    coords = [(p.lat, p.lng) for p in points if _valid_coord(p.lat, p.lng)]
    encoded = None
    start_lat = start_lng = None
    if coords:
        start_lat, start_lng = coords[0]
        if len(coords) >= 2:
            step = max(1, math.ceil(len(coords) / MAX_POLYLINE_POINTS))
            sampled = coords[::step]
            if sampled[-1] != coords[-1]:
                sampled.append(coords[-1])
            encoded = polyline.encode(sampled)

    details = None
    if dist_m <= 0:
        # Einheiten ohne Strecke (Krafttraining, Yoga): Dauer aus den Zeitstempeln
        stamps = [p.time for p in points if p.time]
        if moving <= 0 and len(stamps) >= 2:
            moving = (stamps[-1] - stamps[0]).total_seconds()
        if moving <= 0:
            raise ParseError("Die Datei enthält weder Strecke noch Dauer.")
        hrs = [p.hr for p in points if p.hr]
        if hrs:
            details = {"avg_hr": _round(_avg(hrs), 0), "max_hr": _round(max(hrs), 0), "elapsed_s": int(moving)}
    else:
        try:
            details = build_details(points, cum, segs, dist_m)
        except Exception:  # die Zusatzauswertung darf den Import nie verhindern
            details = None

    return ParsedActivity(
        start=start,
        distance_km=round(dist_m / 1000, 3),
        moving_time_s=int(round(moving)),
        elevation_m=round(gain, 1),
        polyline=encoded,
        start_lat=start_lat,
        start_lng=start_lng,
        sport=sport,
        name=name,
        details=details,
    )


# ---------- XML: GPX und TCX ----------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _float(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def _load_xml(data: bytes) -> ET.Element:
    # Schutz gegen "Billion Laughs"-Angriffe: Entity-Definitionen werden nicht akzeptiert.
    # Entity-Deklarationen stehen immer vor dem Wurzelelement, also genügt der Dateianfang.
    if b"<!entity" in data[:65536].lower():
        raise ParseError("Die XML-Datei enthält nicht erlaubte Entity-Definitionen.")
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        raise ParseError(f"Die Datei ist kein gültiges GPX/TCX ({e}).") from e


def parse_gpx(root: ET.Element) -> ParsedActivity:
    points: list[Point] = []
    name = sport = None
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "trkpt":
            p = Point(lat=_float(el.get("lat")), lng=_float(el.get("lon")))
            for c in el:
                ct = _local(c.tag)
                if ct == "ele":
                    p.ele = _float(c.text)
                elif ct == "time":
                    p.time = parse_time(c.text or "")
                elif ct == "extensions":
                    for x in c.iter():
                        xt = _local(x.tag).lower()
                        if xt == "hr":
                            p.hr = _float(x.text)
                        elif xt in ("cad", "cadence"):
                            p.cad = _float(x.text)
                        elif xt in ("power", "watts"):
                            p.pwr = _float(x.text)
            points.append(p)
        elif tag == "name" and name is None and el.text:
            name = el.text.strip()
        elif tag == "type" and sport is None and el.text:
            sport = el.text.strip()
    if not points:
        raise ParseError("Die GPX-Datei enthält keine aufgezeichneten Streckenpunkte.")
    return summarize(points, sport=sport, name=name)


def parse_tcx(root: ET.Element) -> ParsedActivity:
    points: list[Point] = []
    sport = None
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "Activity" and sport is None:
            sport = el.get("Sport")
        elif tag == "Trackpoint":
            p = Point()
            for c in el.iter():
                ct = _local(c.tag)
                if ct == "Time":
                    p.time = parse_time(c.text or "")
                elif ct == "LatitudeDegrees":
                    p.lat = _float(c.text)
                elif ct == "LongitudeDegrees":
                    p.lng = _float(c.text)
                elif ct == "AltitudeMeters":
                    p.ele = _float(c.text)
                elif ct == "DistanceMeters":
                    p.dist = _float(c.text)
                elif ct == "Value":  # nur HeartRateBpm hat im Trackpoint ein Unterelement "Value"
                    p.hr = _float(c.text)
                elif ct == "Cadence":
                    p.cad = _float(c.text)
                elif ct == "Watts":
                    p.pwr = _float(c.text)
            points.append(p)
    if not points:
        raise ParseError("Die TCX-Datei enthält keine aufgezeichneten Streckenpunkte.")
    return summarize(points, sport=sport)


# ---------- FIT ----------

_SEMICIRCLE = 180.0 / 2**31


def _num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_fit(data: bytes) -> ParsedActivity:
    try:
        import fitdecode
    except ImportError as e:  # pragma: no cover - hängt von der Installation ab
        raise ParseError("FIT-Dateien brauchen das Python-Paket 'fitdecode' (pip install fitdecode).") from e

    points: list[Point] = []
    session: dict = {}
    sport = None
    try:
        with fitdecode.FitReader(io.BytesIO(data)) as reader:
            for frame in reader:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name == "record":
                    lat = frame.get_value("position_lat", fallback=None)
                    lng = frame.get_value("position_long", fallback=None)
                    ele = frame.get_value("enhanced_altitude", fallback=None)
                    if ele is None:
                        ele = frame.get_value("altitude", fallback=None)
                    dist = frame.get_value("distance", fallback=None)
                    points.append(Point(
                        lat=lat * _SEMICIRCLE if lat is not None else None,
                        lng=lng * _SEMICIRCLE if lng is not None else None,
                        ele=float(ele) if ele is not None else None,
                        time=_naive_utc(frame.get_value("timestamp", fallback=None)),
                        dist=float(dist) if dist is not None else None,
                        hr=_num(frame.get_value("heart_rate", fallback=None)),
                        cad=_num(frame.get_value("cadence", fallback=None)),
                        pwr=_num(frame.get_value("power", fallback=None)),
                    ))
                elif frame.name == "session":
                    for key in ("total_distance", "total_timer_time", "total_ascent"):
                        v = frame.get_value(key, fallback=None)
                        if v is not None:
                            session[key] = session.get(key, 0) + float(v)
                    st = _naive_utc(frame.get_value("start_time", fallback=None))
                    if st is not None and "start_time" not in session:
                        session["start_time"] = st
                    if sport is None:
                        s = frame.get_value("sport", fallback=None)
                        sub = frame.get_value("sub_sport", fallback=None)
                        sport = " ".join(str(x) for x in (s, sub) if x and str(x) != "generic") or None
    except ParseError:
        raise
    except Exception as e:  # fitdecode wirft verschiedene Fehlerarten bei kaputten Dateien
        raise ParseError(f"Die FIT-Datei konnte nicht gelesen werden ({e}).") from e

    if not points and not session:
        raise ParseError("Die FIT-Datei enthält keine Aufzeichnung.")
    return summarize(points, sport=sport, session=session or None)


# ---------- Einstieg ----------

def _gunzip(data: bytes) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
            out = g.read(MAX_DECOMPRESSED_BYTES + 1)
    except (OSError, EOFError) as e:
        raise ParseError(f"Die komprimierte Datei ist beschädigt ({e}).") from e
    if len(out) > MAX_DECOMPRESSED_BYTES:
        raise ParseError("Die Datei ist entpackt zu groß.")
    return out


def parse_activity_file(filename: str, data: bytes) -> ParsedActivity:
    """Liest GPX, TCX oder FIT (auch .gz) und liefert die Kennzahlen der Fahrt."""
    lower = filename.lower()
    if lower.endswith(".gz") or data[:2] == b"\x1f\x8b":
        data = _gunzip(data)
        lower = lower[:-3] if lower.endswith(".gz") else lower

    if data[8:12] == b".FIT" or lower.endswith(".fit"):
        activity = parse_fit(data)
    elif lower.endswith((".gpx", ".tcx", ".xml")) or data.lstrip()[:5] == b"<?xml" or data.lstrip()[:1] == b"<":
        root = _load_xml(data)
        kind = _local(root.tag).lower()
        if kind == "gpx":
            activity = parse_gpx(root)
        elif kind == "trainingcenterdatabase":
            activity = parse_tcx(root)
        else:
            raise ParseError("Unbekanntes XML-Format (erwartet wird GPX oder TCX).")
    else:
        raise ParseError("Unbekanntes Dateiformat (erlaubt sind .fit, .gpx und .tcx, auch als .gz).")

    if not activity.name:
        stem = filename.rsplit("/", 1)[-1]
        for suffix in (".gz", ".fit", ".gpx", ".tcx", ".xml"):
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
        activity.name = stem or None
    return activity
