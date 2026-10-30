"""Puls in voller Auflösung, aber sparsam gespeichert.

- Einzelwerte (Health Connect, Health Auto Export, eigene Skripte …) landen in heart_rate_raw und bleiben RAW_DAYS Tage.
- Daraus entstehen laufend Stundenmittel in samples (metric "heart_rate"); die nutzen alle Ansichten dauerhaft.
- Jede Trainingseinheit bekommt ihren Verlauf fest in activities.details["hr"] (höchstens MAX_POINTS Punkte),
  bevor die Rohwerte gelöscht werden. Live per Bluetooth aufgezeichnete Verläufe kommen direkt mit dem Training.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Activity, HeartRateRaw, Sample
from .timeutil import local_day, utcnow

log = logging.getLogger("bodybase.heartrate")

RAW_DAYS = 3
MAX_POINTS = 900
MIN_POINTS = 10
BPM_MIN, BPM_MAX = 25, 250


# ---------- Speichern ----------

def store_raw(db: Session, user_id: int, source: str, items: dict) -> int:
    """items: {ts: bpm}. Doppelte Zeitpunkte werden übersprungen."""
    items = {ts: v for ts, v in items.items() if BPM_MIN <= v <= BPM_MAX}
    if not items:
        return 0
    lo, hi = min(items), max(items)
    have = set(db.scalars(select(HeartRateRaw.ts).where(
        HeartRateRaw.user_id == user_id, HeartRateRaw.source == source, HeartRateRaw.ts >= lo, HeartRateRaw.ts <= hi)))
    rows = [{"user_id": user_id, "source": source, "ts": ts, "bpm": float(v)} for ts, v in items.items() if ts not in have]
    if rows:
        db.execute(HeartRateRaw.__table__.insert(), rows)
        db.commit()
    return len(rows)


def after_ingest(db: Session, user_id: int, lo: datetime, hi: datetime) -> None:
    """Gleich nach dem Empfang: Stundenmittel aktualisieren und betroffene Trainingseinheiten mit Verlauf versehen."""
    try:
        aggregate_hours(db, user_id=user_id, since=lo - timedelta(hours=1), until=hi + timedelta(hours=1))
        attach_range(db, user_id, lo - timedelta(hours=6), hi + timedelta(hours=1))
    except Exception:  # der Empfang selbst darf daran nie scheitern
        db.rollback()
        log.exception("Puls-Nachbearbeitung fehlgeschlagen")


# ---------- Verlauf ----------

def downsample(t: list[float], v: list[float], max_points: int = MAX_POINTS) -> tuple[list, list]:
    if len(t) <= max_points:
        return [round(x) for x in t], [round(x) for x in v]
    span = (t[-1] - t[0]) or 1
    step = span / max_points
    bins: dict[int, list] = defaultdict(list)
    for x, y in zip(t, v):
        bins[min(max_points - 1, int((x - t[0]) / step))].append((x, y))
    out_t, out_v = [], []
    for k in sorted(bins):
        pts = bins[k]
        out_t.append(round(sum(p[0] for p in pts) / len(pts)))
        out_v.append(round(sum(p[1] for p in pts) / len(pts)))
    return out_t, out_v


def make_series(start: datetime, points: list[tuple[datetime, float]], source: str, marks: list | None = None) -> dict | None:
    pts = sorted((p for p in points if BPM_MIN <= p[1] <= BPM_MAX), key=lambda p: p[0])
    if len(pts) < MIN_POINTS:
        return None
    t = [(ts - start).total_seconds() for ts, _ in pts]
    v = [bpm for _, bpm in pts]
    tt, vv = downsample(t, v)
    out = {"start": start.isoformat() + "Z", "t": tt, "v": vv, "source": source,
           "avg": round(sum(v) / len(v)), "max": round(max(v)), "min": round(min(v))}
    if marks:
        out["marks"] = marks[:400]
    return out


def series_for(db: Session, user_id: int, start: datetime, end: datetime) -> dict | None:
    """Verlauf im Zeitfenster aus den Rohwerten (Quelle mit den meisten Punkten), sonst aus älteren Einzelwerten in samples."""
    by_src: dict[str, list] = defaultdict(list)
    for ts, bpm, src in db.execute(select(HeartRateRaw.ts, HeartRateRaw.bpm, HeartRateRaw.source).where(
            HeartRateRaw.user_id == user_id, HeartRateRaw.ts >= start, HeartRateRaw.ts <= end)):
        by_src[src].append((ts, bpm))
    if not by_src:
        for ts, bpm, src in db.execute(select(Sample.ts, Sample.value, Sample.source).where(
                Sample.user_id == user_id, Sample.metric == "heart_rate", Sample.ts >= start, Sample.ts <= end)):
            by_src[src].append((ts, bpm))
    if not by_src:
        return None
    src, pts = max(by_src.items(), key=lambda kv: len(kv[1]))
    return make_series(start, pts, src)


def _end(a: Activity) -> datetime | None:
    d = a.duration_s or a.moving_s
    return a.start + timedelta(seconds=d) if d else None


def attach(db: Session, a: Activity, final: bool = False) -> bool:
    """Verlauf an eine Einheit hängen, wenn es genug Werte gibt. final: danach nicht mehr suchen."""
    d = a.details or {}
    if d.get("hr") or d.get("hr_checked"):
        return False
    end = _end(a)
    if end is None:
        return False
    s = series_for(db, a.user_id, a.start, end)
    if s is None:
        if final:
            a.details = {**d, "hr_checked": True}
        return False
    new = {**d, "hr": s}
    if a.avg_hr is None:
        a.avg_hr = s["avg"]
        new["filled"] = {**(d.get("filled") or {}), "avg_hr": "heart_rate"}
    if a.max_hr is None:
        a.max_hr = s["max"]
        new["filled"] = {**(new.get("filled") or d.get("filled") or {}), "max_hr": "heart_rate"}
    a.details = new
    return True


def attach_range(db: Session, user_id: int | None, lo: datetime, hi: datetime) -> int:
    q = select(Activity).where(Activity.start >= lo - timedelta(hours=12), Activity.start <= hi)
    if user_id is not None:
        q = q.where(Activity.user_id == user_id)
    n = 0
    now = utcnow()
    for a in db.scalars(q):
        end = _end(a)
        if end is None or end < lo or end > now:
            continue
        n += attach(db, a, final=end < now - timedelta(days=RAW_DAYS))
    db.commit()
    return n


# ---------- Stundenmittel und Aufräumen ----------

def aggregate_hours(db: Session, user_id: int | None = None, since: datetime | None = None, until: datetime | None = None) -> int:
    """Stundenmittel je Quelle aus den Rohwerten (Zeitstempel: Stunde + 30 Minuten), nur für abgeschlossene Stunden."""
    now = utcnow()
    cur_hour = now.replace(minute=0, second=0, microsecond=0)
    q = select(HeartRateRaw.user_id, HeartRateRaw.source, HeartRateRaw.ts, HeartRateRaw.bpm).where(HeartRateRaw.ts < cur_hour)
    if user_id is not None:
        q = q.where(HeartRateRaw.user_id == user_id)
    if since is not None:
        q = q.where(HeartRateRaw.ts >= since.replace(minute=0, second=0, microsecond=0))
    if until is not None:
        q = q.where(HeartRateRaw.ts <= until)
    buckets: dict[tuple, list] = defaultdict(lambda: [0.0, 0])
    for uid, src, ts, bpm in db.execute(q):
        b = buckets[(uid, src, ts.replace(minute=0, second=0, microsecond=0))]
        b[0] += bpm
        b[1] += 1
    for (uid, src, hour), (total, cnt) in buckets.items():
        ts = hour + timedelta(minutes=30)
        row = db.scalar(select(Sample).where(Sample.user_id == uid, Sample.source == src, Sample.metric == "heart_rate",
                                             Sample.ts == ts))
        value = round(total / cnt, 1)
        if row is None:
            db.add(Sample(user_id=uid, metric="heart_rate", source=src, ts=ts, day=local_day(ts), value=value))
        else:
            row.value = value
    db.commit()
    return len(buckets)


def compact_old_samples(db: Session, cutoff: datetime, limit: int = 200_000) -> int:
    """Ältere Einzelwerte in samples (vor dieser Version gespeichert) zu Stundenmitteln zusammenfassen."""
    rows = db.execute(select(Sample.id, Sample.user_id, Sample.source, Sample.ts, Sample.value).where(
        Sample.metric == "heart_rate", Sample.ts < cutoff).order_by(Sample.user_id, Sample.ts).limit(limit)).all()
    buckets: dict[tuple, list] = defaultdict(list)
    for r in rows:
        buckets[(r.user_id, r.source, r.ts.replace(minute=0, second=0, microsecond=0))].append(r)
    drop: list[int] = []
    for (uid, src, hour), items in buckets.items():
        target = hour + timedelta(minutes=30)
        if len(items) == 1 and items[0].ts == target:
            continue  # schon ein Stundenmittel
        keep = next((r for r in items if r.ts == target), None)
        value = round(sum(r.value for r in items) / len(items), 1)
        if keep is not None:
            db.get(Sample, keep.id).value = value
        else:
            db.add(Sample(user_id=uid, metric="heart_rate", source=src, ts=target, day=local_day(target), value=value))
        drop += [r.id for r in items if keep is None or r.id != keep.id]
    for i in range(0, len(drop), 5000):
        db.execute(delete(Sample).where(Sample.id.in_(drop[i:i + 5000])))
    db.commit()
    return len(drop)


def maintenance(db: Session) -> None:
    """Regelmäßig (alle 30 Minuten): Verläufe an Einheiten hängen, Stundenmittel bilden, alte Rohwerte löschen."""
    now = utcnow()
    cutoff = now - timedelta(days=RAW_DAYS)
    attach_range(db, None, cutoff - timedelta(days=1), now)
    # Einheiten, deren Einzelwerte noch in samples liegen (ältere Versionen), vor dem Zusammenfassen sichern
    for a in db.scalars(select(Activity).where(Activity.start >= now - timedelta(days=120), Activity.start < cutoff)):
        if not (a.details or {}).get("hr_checked"):
            attach(db, a, final=True)
    db.commit()
    aggregate_hours(db, since=cutoff - timedelta(days=1))
    compact_old_samples(db, cutoff)
    db.execute(delete(HeartRateRaw).where(HeartRateRaw.ts < cutoff))
    db.commit()


def recent(db: Session, user_id: int, hours: int = 72) -> dict:
    """Puls der letzten Stunden für die Detailansicht: Rohwerte, auf höchstens 1500 Punkte verdichtet."""
    start = utcnow() - timedelta(hours=hours)
    by_src: dict[str, list] = defaultdict(list)
    for ts, bpm, src in db.execute(select(HeartRateRaw.ts, HeartRateRaw.bpm, HeartRateRaw.source).where(
            HeartRateRaw.user_id == user_id, HeartRateRaw.ts >= start).order_by(HeartRateRaw.ts)):
        by_src[src].append((ts, bpm))
    if not by_src:
        return {"start": start.isoformat() + "Z", "t": [], "v": [], "source": None}
    src, pts = max(by_src.items(), key=lambda kv: len(kv[1]))
    t = [(ts - start).total_seconds() for ts, _ in pts]
    tt, vv = downsample(t, [b for _, b in pts], 1500)
    return {"start": start.isoformat() + "Z", "t": tt, "v": vv, "source": src, "min": min(vv), "max": max(vv)}
