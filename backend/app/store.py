"""Speichern der normalisierten Daten aller Anbieter: Messwerte, Aktivitäten und Schlaf.

Jeder Anbieter liefert seine Daten über einen Writer. Der Writer vermeidet Doppelungen (gleiche Quelle, gleicher
Zeitpunkt bzw. gleiche ID beim Anbieter) und verknüpft dieselbe Aktivität aus mehreren Quellen miteinander.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from . import metrics as M
from . import sports
from .models import Activity, Sample, SleepSession, User
from .timeutil import day_start_utc, local_day

log = logging.getLogger("bodybase.store")

# Welche Quelle gewinnt, wenn mehrere denselben Wert liefern? Spezialisierte Geräte vor Sammelstellen.
DEFAULT_PRIORITY = [
    "manual", "withings", "garmin", "polar", "suunto", "coros", "wahoo", "oura", "whoop", "fitbit",
    "apple_health", "health_connect", "dexcom", "nightscout", "concept2", "hevy", "strava", "intervals",
    "homeassistant", "file", "csv", "api",
]
ACTIVITY_PRIORITY = [
    "strength", "garmin", "polar", "suunto", "coros", "wahoo", "concept2", "hevy", "file", "strava", "intervals",
    "apple_health", "health_connect", "fitbit", "whoop", "oura", "withings", "manual", "api",
]


def priority_for(user: User | None, metric: str) -> list[str]:
    prefs = (user.prefs or {}) if user else {}
    custom = (prefs.get("priority") or {}).get(metric)
    base = ACTIVITY_PRIORITY if metric == "_activities" else DEFAULT_PRIORITY
    if not custom:
        return list(base)
    return [s for s in custom if isinstance(s, str)] + [s for s in base if s not in custom]


def rank(order: list[str], source: str) -> int:
    try:
        return order.index(source)
    except ValueError:
        return len(order)


def day_ts(d: date) -> datetime:
    """Zeitstempel für Tageswerte (Schritte eines Tages …): Mittag Ortszeit, damit der Kalendertag eindeutig ist."""
    return day_start_utc(d) + timedelta(hours=12)


@dataclass
class ActivityIn:
    source_id: str
    start: datetime  # UTC ohne Zone
    sport_raw: str | None = None
    name: str | None = None
    duration_s: float | None = None
    moving_s: float | None = None
    distance_m: float | None = None
    elevation_m: float | None = None
    calories: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    avg_power: float | None = None
    load: float | None = None
    volume_kg: float | None = None
    polyline: str | None = None
    details: dict | None = None
    sport: str | None = None  # bereits normalisiert (optional)


@dataclass
class SleepIn:
    source_id: str
    start: datetime
    end: datetime
    asleep_min: float | None = None
    deep_min: float | None = None
    rem_min: float | None = None
    light_min: float | None = None
    awake_min: float | None = None
    score: float | None = None
    efficiency: float | None = None
    avg_hr: float | None = None
    hrv: float | None = None
    nap: bool = False


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


@dataclass
class Writer:
    db: Session
    user_id: int
    source: str
    batch: int = 2000
    counts: dict = field(default_factory=lambda: {"samples": 0, "activities": 0, "sleep": 0, "skipped": 0})
    _samples: dict = field(default_factory=dict)
    _touched_days: set = field(default_factory=set)

    # ---------- Messwerte ----------

    def sample(self, metric: str, ts: datetime | None, value) -> None:
        v = _num(value)
        if ts is None or v is None or not M.plausible(metric, v):
            self.counts["skipped"] += 1
            return
        self._samples[(metric, ts.replace(microsecond=0))] = v
        if len(self._samples) >= self.batch:
            self.flush_samples()

    def daily(self, metric: str, d: date | None, value) -> None:
        """Tageswert (z. B. Schritte eines Tages)."""
        if d is None:
            self.counts["skipped"] += 1
            return
        self.sample(metric, day_ts(d), value)

    def flush_samples(self) -> None:
        if not self._samples:
            return
        items = self._samples
        self._samples = {}
        metrics_set = {m for m, _ in items}
        ts_min = min(t for _, t in items)
        ts_max = max(t for _, t in items)
        existing = {
            (m, t): (sid, val)
            for sid, m, t, val in self.db.execute(
                select(Sample.id, Sample.metric, Sample.ts, Sample.value).where(
                    Sample.user_id == self.user_id, Sample.source == self.source,
                    Sample.metric.in_(metrics_set), Sample.ts >= ts_min, Sample.ts <= ts_max,
                )
            )
        }
        new_rows = []
        for (metric, ts), value in items.items():
            hit = existing.get((metric, ts))
            if hit is None:
                new_rows.append({"user_id": self.user_id, "metric": metric, "source": self.source, "ts": ts,
                                 "day": local_day(ts), "value": value})
            elif abs(hit[1] - value) > 1e-9:
                self.db.query(Sample).filter(Sample.id == hit[0]).update({"value": value}, synchronize_session=False)
            else:
                continue
            self.counts["samples"] += 1
        if new_rows:
            self.db.execute(Sample.__table__.insert(), new_rows)
        self.db.commit()

    # ---------- Aktivitäten ----------

    def activity(self, a: ActivityIn) -> Activity | None:
        if not a.source_id or a.start is None:
            self.counts["skipped"] += 1
            return None
        row = self.db.scalar(select(Activity).where(
            Activity.user_id == self.user_id, Activity.source == self.source, Activity.source_id == str(a.source_id)))
        if row is None:
            row = Activity(user_id=self.user_id, source=self.source, source_id=str(a.source_id)[:120])
            self.db.add(row)
        row.start = a.start.replace(microsecond=0)
        row.day = local_day(row.start)
        row.sport_raw = (a.sport_raw or "")[:80] or None
        row.sport = a.sport or sports.normalize(a.sport_raw or a.name)
        row.name = (a.name or "")[:200] or None
        for attr in ("distance_m", "elevation_m", "calories", "avg_hr", "max_hr", "avg_power", "load", "volume_kg"):
            setattr(row, attr, _num(getattr(a, attr)))
        row.duration_s = int(_num(a.duration_s)) if _num(a.duration_s) is not None else None
        row.moving_s = int(_num(a.moving_s)) if _num(a.moving_s) is not None else None
        filled = (row.details or {}).get("filled") or {}
        own = [k for k in filled if k in FILL_ATTRS and getattr(a, k, None) is not None]
        if own:  # die Quelle liefert den Wert inzwischen selbst
            row.details = {**row.details, "filled": {k: v for k, v in filled.items() if k not in own}}
        has_track = (row.details or {}).get("track") == "ok"
        if a.polyline and not has_track:
            row.polyline = a.polyline  # eine nachgeholte, genaue Strecke nicht durch die Vorschau ersetzen
        if a.details:
            row.details = {**(row.details or {}), **a.details}
        self.db.flush()
        link_duplicates(self.db, self.user_id, row)
        self.db.commit()
        self.counts["activities"] += 1
        return row

    # ---------- Schlaf ----------

    def sleep(self, s: SleepIn) -> None:
        if not s.source_id or s.start is None or s.end is None or s.end <= s.start:
            self.counts["skipped"] += 1
            return
        row = self.db.scalar(select(SleepSession).where(
            SleepSession.user_id == self.user_id, SleepSession.source == self.source, SleepSession.source_id == str(s.source_id)))
        if row is None:
            row = SleepSession(user_id=self.user_id, source=self.source, source_id=str(s.source_id)[:120])
            self.db.add(row)
        row.start, row.end = s.start.replace(microsecond=0), s.end.replace(microsecond=0)
        row.day = local_day(row.end)
        asleep = _num(s.asleep_min)
        if asleep is None:
            parts = [_num(x) for x in (s.deep_min, s.rem_min, s.light_min)]
            asleep = sum(p for p in parts if p is not None) if any(p is not None for p in parts) else None
        if asleep is None:
            asleep = (row.end - row.start).total_seconds() / 60 - (_num(s.awake_min) or 0)
        row.asleep_min = asleep
        for attr in ("deep_min", "rem_min", "light_min", "awake_min", "score", "efficiency", "avg_hr", "hrv"):
            setattr(row, attr, _num(getattr(s, attr)))
        row.nap = bool(s.nap)
        self.db.commit()
        self.counts["sleep"] += 1
        if not s.nap:
            for attr, metric in M.SLEEP_METRICS.items():
                value = getattr(row, attr)
                if value is not None:
                    self.sample(metric, row.end, value)
            if row.hrv is not None:
                self.sample("hrv", row.end, row.hrv)

    def flush(self) -> dict:
        self.flush_samples()
        self.db.commit()
        return self.counts


# ---------- Doppelte Aktivitäten ----------

START_TOLERANCE_S = 300


LINK_WINDOW = timedelta(hours=4)
MIN_OVERLAP = 0.6  # Anteil der kürzeren Einheit, der sich überschneiden muss
# Sportarten, die für dieselbe Einheit stehen können (Uhren erkennen Krafttraining oft als „Workout“ oder „Sonstiges“)
COMPATIBLE = {
    "strength": {"strength", "cardio", "other", "yoga"}, "cardio": {"cardio", "strength", "other", "yoga", "team"},
    "other": {"other", "strength", "cardio", "yoga", "climb"}, "yoga": {"yoga", "strength", "cardio", "other"},
    "climb": {"climb", "other", "hike"}, "hike": {"hike", "walk", "climb"}, "walk": {"walk", "hike"},
}
FILL_ATTRS = ("avg_hr", "max_hr", "calories", "elevation_m", "avg_power", "distance_m", "load")


def _end(a: Activity) -> datetime | None:
    d = a.duration_s or a.moving_s
    return a.start + timedelta(seconds=d) if d else None


def overlap_ratio(a: Activity, b: Activity) -> float:
    ea, eb = _end(a), _end(b)
    if not ea or not eb:
        return 0.0
    inter = (min(ea, eb) - max(a.start, b.start)).total_seconds()
    shorter = min((ea - a.start).total_seconds(), (eb - b.start).total_seconds())
    return max(0.0, inter) / shorter if shorter > 0 else 0.0


def _compatible(a: Activity, b: Activity) -> bool:
    if a.sport == b.sport:
        return True
    return b.sport in COMPATIBLE.get(a.sport, {a.sport}) or a.sport in COMPATIBLE.get(b.sport, {b.sport})


def _similar(a: Activity, b: Activity) -> bool:
    """Gleiche Einheit? Fast gleicher Start und ähnliche Dauer, oder zeitlich überwiegend deckungsgleich und
    passende Sportart (z. B. Hevy-Krafttraining und das von WHOOP erkannte „Weightlifting“)."""
    da, db_ = a.duration_s or a.moving_s, b.duration_s or b.moving_s
    if abs((a.start - b.start).total_seconds()) <= START_TOLERANCE_S:
        if not (da and db_ and abs(da - db_) > max(300, 0.25 * max(da, db_))):
            return True
    return _compatible(a, b) and overlap_ratio(a, b) >= MIN_OVERLAP


def _flags(a: Activity) -> dict:
    return a.details or {}


def link_duplicates(db: Session, user_id: int, row: Activity) -> None:
    """Dieselbe Einheit aus mehreren Quellen (Garmin, Strava, WHOOP, Hevy, Apple Health …) wird nur einmal gezählt.
    Die Quelle mit dem höchsten Rang bleibt sichtbar, die anderen verweisen auf sie. Fehlende Werte der Hauptquelle
    (Puls, Kalorien, Belastung …) werden aus den anderen ergänzt. Von Hand gelöste oder verknüpfte Einheiten
    behalten ihre Zuordnung (details.unlink, details.link_to)."""
    near = db.scalars(select(Activity).where(
        Activity.user_id == user_id, Activity.start >= row.start - LINK_WINDOW, Activity.start <= row.start + LINK_WINDOW)).all()
    by_id = {a.id: a for a in near}
    manual_target = _flags(row).get("link_to")
    if _flags(row).get("unlink"):
        group = [row]
    elif manual_target and manual_target in by_id:
        target = by_id[manual_target]
        group = [target] + [a for a in near if a.id != target.id and (_flags(a).get("link_to") == target.id
                                                                     or (a.id == row.id))]
    else:
        group = [a for a in near if a.id == row.id or (
            a.source != row.source and not _flags(a).get("unlink") and not _flags(a).get("link_to") and _similar(a, row))]
        # von Hand an ein Mitglied gehängte Einheiten gehören dazu
        ids = {a.id for a in group}
        group += [a for a in near if a.id not in ids and _flags(a).get("link_to") in ids]
    previous_primary = db.get(Activity, row.duplicate_of) if row.duplicate_of else None
    if len(group) <= 1:
        if row.duplicate_of is not None:
            row.duplicate_of = None
        _refill(db, row, [])
        if previous_primary is not None and previous_primary.id != row.id:
            others = list(db.scalars(select(Activity).where(Activity.duplicate_of == previous_primary.id, Activity.id != row.id)))
            _refill(db, previous_primary, others)
        return
    user = db.get(User, user_id)
    order = priority_for(user, "_activities")
    group.sort(key=lambda a: (rank(order, a.source), a.id))
    primary = group[0]
    primary.duplicate_of = None
    for a in group[1:]:
        a.duplicate_of = primary.id
    _refill(db, primary, group[1:])


def _refill(db: Session, primary: Activity, others: list) -> None:
    """Ergänzte Werte neu berechnen: erst die früher ergänzten entfernen, dann aus den aktuellen Partnern füllen,
    zuletzt Puls aus Einzelmessungen (z. B. Apple Watch) im Zeitraum der Einheit."""
    details = dict(primary.details or {})
    filled = dict(details.get("filled") or {})
    for attr in filled:
        if attr in FILL_ATTRS:
            setattr(primary, attr, None)
    filled = {}
    for attr in FILL_ATTRS:
        if getattr(primary, attr) is None:
            for a in others:
                if getattr(a, attr) is not None:
                    setattr(primary, attr, getattr(a, attr))
                    filled[attr] = a.source
                    break
    zones = next((a.details.get("hr_zones") for a in others if a.details and a.details.get("hr_zones")), None)
    if zones and not (details.get("hr_zones") and "hr_zones" not in (details.get("filled") or {})):
        details["hr_zones"] = zones
        filled["hr_zones"] = next(a.source for a in others if a.details and a.details.get("hr_zones"))
    elif "hr_zones" in (details.get("filled") or {}) and not zones:
        details.pop("hr_zones", None)
    end = _end(primary)
    if primary.avg_hr is None and end is not None:
        rows = db.execute(select(Sample.value).where(
            Sample.user_id == primary.user_id, Sample.metric == "heart_rate", Sample.ts >= primary.start, Sample.ts <= end)).all()
        vals = [r[0] for r in rows if r[0]]
        if len(vals) >= 3:
            primary.avg_hr = round(sum(vals) / len(vals), 1)
            primary.max_hr = primary.max_hr or max(vals)
            filled["avg_hr"] = "heart_rate"
            filled.setdefault("max_hr", "heart_rate")
    if filled or details.get("filled"):
        details["filled"] = filled
        primary.details = details


# ---------- Auswertung ----------

def daily_series(db: Session, user: User, metric: str, start: date, end: date, source: str | None = None) -> list[dict]:
    """Ein Wert pro Tag; je Tag gewinnt die Quelle mit dem höchsten Rang (Einstellungen → Datenquellen)."""
    m = M.get(metric)
    if m is None:
        return []
    agg = {"sum": func.sum, "avg": func.avg, "min": func.min, "max": func.max}[m.agg]
    q = select(Sample.day, Sample.source, agg(Sample.value), func.count()).where(
        Sample.user_id == user.id, Sample.metric == metric, Sample.day >= start, Sample.day <= end,
    ).group_by(Sample.day, Sample.source)
    if source:
        q = q.where(Sample.source == source)
    order = priority_for(user, metric)
    best: dict[date, tuple[int, str, float, int]] = {}
    for day, src, value, n in db.execute(q):
        r = rank(order, src)
        cur = best.get(day)
        if cur is None or r < cur[0]:
            best[day] = (r, src, float(value), n)
    return [{"day": d.isoformat(), "value": round(v[2], 3), "source": v[1], "n": v[3]} for d, v in sorted(best.items())]


def latest_value(db: Session, user: User, metric: str, within_days: int = 3650) -> dict | None:
    """Jüngster Tageswert einer Metrik (über die Quellen-Rangfolge)."""
    last_day = db.scalar(select(func.max(Sample.day)).where(Sample.user_id == user.id, Sample.metric == metric))
    if last_day is None:
        return None
    series = daily_series(db, user, metric, last_day, last_day)
    return series[-1] if series else None


def sources_for(db: Session, user_id: int, metric: str) -> list[dict]:
    rows = db.execute(select(Sample.source, func.count(), func.max(Sample.day)).where(
        Sample.user_id == user_id, Sample.metric == metric).group_by(Sample.source)).all()
    return [{"source": s, "count": n, "last": d.isoformat() if d else None} for s, n, d in rows]


def visible_activities(db: Session, user_id: int):
    return and_(Activity.user_id == user_id, Activity.duplicate_of.is_(None))
