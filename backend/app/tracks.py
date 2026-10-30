"""GPS-Strecken und Verläufe (Höhe, Puls, Tempo, Leistung) für Aktivitäten.

Die Übersichtslisten der Anbieter enthalten meist keine Strecke. Für jede neue Einheit mit Distanz holt BodyBase
deshalb die Detaildaten nach (FIT-/GPX-Datei oder Datenströme) und baut daraus dieselbe Strecke und denselben
Verlauf wie beim Datei-Import. Damit Anbieter-Limits halten, gibt es pro Abgleich ein Kontingent; der Rest folgt
beim nächsten Durchlauf.
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime, timedelta

from .importers import parsers
from .importers.parsers import Point

log = logging.getLogger("bodybase.tracks")

BUDGET_PER_RUN = 15  # Detailabrufe je Verbindung und Abgleich


def result_from_parsed(p: parsers.ParsedActivity) -> tuple[str | None, dict] | None:
    d = p.details or {}
    profile = d.get("profile")
    if not p.polyline and not profile:
        return None
    return p.polyline, {"profile": profile, "max_speed": d.get("max_speed")}


def from_points(points: list[Point]) -> tuple[str | None, dict] | None:
    pts = [p for p in points if p.time is not None]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda p: p.time)
    try:
        return result_from_parsed(parsers.summarize(pts))
    except parsers.ParseError:
        return None


def from_file(filename: str, data: bytes) -> tuple[str | None, dict] | None:
    """FIT, GPX oder TCX, auch gezippt (Garmin liefert das Original als ZIP) oder als .gz."""
    if not data:
        return None
    if data[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            return None
        names = [n for n in z.namelist() if n.lower().rsplit(".", 1)[-1] in ("fit", "gpx", "tcx")]
        if not names:
            return None
        filename, data = names[0], z.read(names[0])
    try:
        return result_from_parsed(parsers.parse_activity_file(filename, data))
    except parsers.ParseError:
        return None


def from_streams(start: datetime, time_s: list, lat: list | None = None, lng: list | None = None, ele: list | None = None,
                 hr: list | None = None, dist: list | None = None, watts: list | None = None,
                 cad: list | None = None) -> tuple[str | None, dict] | None:
    """Gleich lange Listen je Messgröße, time_s in Sekunden ab Start (Strava, intervals.icu)."""
    if not time_s:
        return None

    def at(seq, i):
        if not seq or i >= len(seq):
            return None
        v = seq[i]
        return float(v) if isinstance(v, (int, float)) else None

    points = []
    for i, t in enumerate(time_s):
        if not isinstance(t, (int, float)):
            continue
        points.append(Point(lat=at(lat, i), lng=at(lng, i), ele=at(ele, i), time=start + timedelta(seconds=float(t)),
                            dist=at(dist, i), hr=at(hr, i), pwr=at(watts, i), cad=at(cad, i)))
    return from_points(points)


def download(ctx, url: str, **kw) -> bytes | None:
    """Datei vom Anbieter holen; 404 und leere Antworten bedeuten: keine Detaildaten."""
    r = ctx.request("GET", url, expect_json=False, ok_status=(404, 204), **kw)
    if r is None or r.status_code in (404, 204) or not r.content:
        return None
    return r.content


# ---------- Anbindung an den Abgleich ----------

def wants_track(row) -> bool:
    if row is None or not (row.distance_m or 0) > 0:
        return False
    d = row.details or {}
    if d.get("track") in ("ok", "none"):
        return False
    return not (row.polyline and (d.get("profile") or {}).get("ll"))


def apply(db, row, result) -> None:
    details = dict(row.details or {})
    if result:
        poly, extra = result
        if poly:
            row.polyline = poly
        details.update({k: v for k, v in extra.items() if v is not None})
        details["track"] = "ok"
    else:
        details["track"] = "none"
    row.details = details
    db.commit()


def attach(ctx, row, fetch) -> None:
    """Holt für eine gerade gespeicherte Aktivität die Strecke nach, solange das Kontingent reicht.

    fetch() liefert (polyline, details) oder None, wenn es zu der Einheit keine Detaildaten gibt.
    Netzwerk- und Serverfehler markieren nichts, die Einheit kommt beim nächsten Abgleich wieder dran.
    """
    from .providers.base import RateLimited, SyncError
    if not wants_track(row):
        return
    if ctx.track_budget <= 0:
        ctx.track_pending += 1
        return
    ctx.track_budget -= 1
    try:
        result = fetch()
    except RateLimited:
        ctx.track_budget = 0
        ctx.track_pending += 1
        return
    except SyncError as e:
        log.info("Strecke für %s/%s nicht geholt: %s", row.source, row.source_id, e)
        tries = int((row.details or {}).get("track_tries") or 0) + 1
        if tries < 3:
            row.details = {**(row.details or {}), "track_tries": tries}
            ctx.db.commit()
            return
        result = None  # nach drei Fehlversuchen nicht mehr fragen
    except Exception:
        log.exception("Strecke für %s/%s nicht lesbar", row.source, row.source_id)
        result = None
    apply(ctx.db, row, result)


def backfill(ctx) -> None:
    """Nach dem Abgleich: Einheiten dieser Quelle ohne Strecke abarbeiten, neueste zuerst."""
    from sqlalchemy import select

    from .models import Activity
    provider = ctx.provider
    if not getattr(provider, "has_tracks", False) or ctx.user is None:
        return
    rows = ctx.db.scalars(select(Activity).where(
        Activity.user_id == ctx.user.id, Activity.source == provider.key, Activity.distance_m > 0,
    ).order_by(Activity.start.desc()).limit(400)).all()
    for row in rows:
        if wants_track(row):
            attach(ctx, row, lambda r=row: provider.track(ctx, r))
    if ctx.track_pending:
        ctx.note(f"Strecken: {ctx.track_pending} weitere folgen beim nächsten Abgleich.")
