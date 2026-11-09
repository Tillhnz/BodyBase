"""Leistungswerte aus den eigenen Trainings: FTP (Radfahren) und VO₂max, dazu Hinweise nach neuen Aktivitäten.

FTP (Functional Threshold Power, die Leistung, die man etwa eine Stunde halten kann), bestes Ergebnis der letzten 90 Tage:
- mit Leistungsverlauf (Wattmesser): Maximum aus 95 % der besten 20 Minuten, 100 % der besten 60 Minuten
  und 75 % der besten 5 Minuten (Ramp-Test-Faustregel), je Fahrt;
- nur mit Durchschnitts- oder normalisierter Leistung: Fahrten von 20 bis 75 Minuten, 95 % (20 min) bis 100 % (60 min).
VO₂max:
- aus der Leistung: ACSM-Formel für das Rad, VO₂ = 10,8 · W/kg + 7, mit der besten 5-Minuten-Leistung
  (oder FTP / 0,8) als Leistung an der VO₂max;
- sonst grob aus dem Puls (Uth-Sørensen): 15,3 · Maximalpuls / Ruhepuls, nur mit gemessenem Maximalpuls.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Activity, User
from .scores import Context, load_score
from .sports import SPORTS
from .store import Writer, daily_series, day_ts
from .timeutil import today

WINDOW_DAYS = 90
FTP_CHANGE_W = 3  # ab so vielen Watt Unterschied gibt es einen Hinweis


def _weight(db: Session, user: User, end=None) -> float | None:
    end = end or today()
    s = daily_series(db, user, "weight", end - timedelta(days=365), end)
    return s[-1]["value"] if s else None


def estimate(db: Session, user: User, days: int = WINDOW_DAYS, end=None) -> dict:
    """Schätzung mit den Fahrten der `days` Tage bis `end` (Standard: heute)."""
    end = end or today()
    start = end - timedelta(days=days)
    rides = db.scalars(select(Activity).where(Activity.user_id == user.id, Activity.sport == "ride",
                                              Activity.duplicate_of.is_(None), Activity.day >= start, Activity.day <= end)).all()
    best = None
    best5 = None
    for a in rides:
        d = a.details or {}
        pc = d.get("pc") or {}
        cands = []
        if pc.get("1200"):
            cands.append((0.95 * pc["1200"], "95 % der besten 20 Minuten"))
        if pc.get("3600"):
            cands.append((pc["3600"], "beste 60 Minuten"))
        if pc.get("300"):
            cands.append((0.75 * pc["300"], "75 % der besten 5 Minuten"))
            if not best5 or pc["300"] > best5[0]:
                best5 = (pc["300"], a)
        if not pc:
            minutes = (a.moving_s or a.duration_s or 0) / 60
            p = d.get("np") or a.avg_power
            if p and 20 <= minutes <= 75:
                f = 0.95 + 0.05 * (min(minutes, 60) - 20) / 40
                cands.append((p * f, f"Durchschnittsleistung über {round(minutes)} Minuten"))
        for v, how in cands:
            if not best or v > best["ftp"]:
                best = {"ftp": v, "method": how, "activity_id": a.id, "name": a.name, "day": a.day.isoformat()}
    weight = _weight(db, user, end)
    out = {"ftp": round(best["ftp"]) if best else None, "ftp_from": best, "weight": weight,
           "wkg": round(best["ftp"] / weight, 2) if best and weight else None, "rides": len(rides),
           "rides_with_power": sum(1 for a in rides if a.avg_power or (a.details or {}).get("pc"))}
    vo2, how = None, None
    if weight:
        if best5:
            vo2, how = 10.8 * best5[0] / weight + 7, "aus der besten 5-Minuten-Leistung"
        elif best:
            vo2, how = 10.8 * (best["ftp"] / 0.8) / weight + 7, "aus der FTP"
    if vo2 is None:
        ctx = Context(db, user, start, end)
        seen = sorted(a.max_hr for lst in ctx.acts.values() for a in lst if a.max_hr and 120 < a.max_hr < 225)
        rhr = sorted(ctx.series["resting_hr"].values())
        if len(seen) >= 3 and rhr:
            vo2, how = 15.3 * seen[-3] / rhr[len(rhr) // 2], "grob aus Maximal- und Ruhepuls"
    out["vo2max"] = round(vo2, 1) if vo2 else None
    out["vo2_method"] = how
    return out


def store(db: Session, user: User, est: dict, day=None) -> None:
    """Als Messgrößen ablegen (Quelle BodyBase), damit FTP und VO₂max in Trends und Verläufen auftauchen."""
    w = Writer(db, user.id, "bodybase")
    t = day_ts(day or today())
    if est.get("ftp"):
        w.sample("ftp", t, est["ftp"])
    if est.get("vo2max"):
        w.sample("vo2max", t, est["vo2max"])
    w.flush_samples()
    db.commit()


def summary(db: Session, user: User, a: Activity) -> dict:
    ctx = Context(db, user, a.day - timedelta(days=1), a.day)
    d = a.details or {}
    return {
        "id": a.id, "name": a.name or SPORTS.get(a.sport, a.sport), "sport": a.sport, "sport_label": SPORTS.get(a.sport, a.sport),
        "start": a.start.isoformat() + "Z", "duration_s": a.moving_s or a.duration_s, "distance_m": a.distance_m,
        "elevation_m": a.elevation_m, "avg_hr": a.avg_hr, "avg_power": d.get("np") or a.avg_power, "calories": a.calories,
        "load": round(load_score(ctx.activity_load(a))), "volume_kg": d.get("volume_kg"),
    }


def notices(db: Session, user: User) -> dict:
    """Was seit dem letzten Besuch neu ist: abgeschlossene Aktivitäten (ohne Gehen) und eine geänderte FTP."""
    prefs = dict(user.prefs or {})
    seen = dict(prefs.get("notices") or {})
    max_id = db.scalar(select(func.max(Activity.id)).where(Activity.user_id == user.id)) or 0
    est = estimate(db, user)
    try:
        store(db, user, est)
    except Exception:
        db.rollback()
    if not prefs.get("perf_backfilled") and not prefs.get("perf_backfill_started"):
        user.prefs = prefs = {**prefs, "perf_backfill_started": 1}
        db.commit()
        count = db.scalar(select(func.count()).select_from(Activity).where(Activity.user_id == user.id)) or 0
        if count < 300:  # wenig Daten: gleich hier, sonst im Hintergrund
            backfill(db, user)
            user.prefs = prefs = {**(user.prefs or {}), "perf_backfilled": 1}
            db.commit()
        else:
            backfill_async(user.id)
    if "last_activity_id" not in seen:  # beim ersten Mal nichts Altes hochspülen
        seen = {"last_activity_id": max_id, "ftp": est["ftp"]}
        user.prefs = {**prefs, "notices": seen}
        db.commit()
        return {"activities": [], "ftp": None, "performance": est}
    new = db.scalars(select(Activity).where(
        Activity.user_id == user.id, Activity.id > seen["last_activity_id"], Activity.duplicate_of.is_(None),
        Activity.sport != "walk", Activity.start >= datetime.combine(today() - timedelta(days=3), time())).order_by(Activity.start.desc()).limit(5)).all()
    ftp = None
    if est["ftp"] and seen.get("ftp") and abs(est["ftp"] - seen["ftp"]) >= FTP_CHANGE_W:
        ftp = {"old": seen["ftp"], "new": est["ftp"], "wkg": est["wkg"], "vo2max": est["vo2max"], "from": est["ftp_from"]}
    elif est["ftp"] and not seen.get("ftp"):
        ftp = {"old": None, "new": est["ftp"], "wkg": est["wkg"], "vo2max": est["vo2max"], "from": est["ftp_from"]}
    return {"activities": [summary(db, user, a) for a in new], "ftp": ftp, "max_id": max_id, "performance": est}


def mark_seen(db: Session, user: User, activity_id: int | None, ftp: int | None) -> None:
    prefs = dict(user.prefs or {})
    seen = dict(prefs.get("notices") or {})
    if activity_id is not None:
        seen["last_activity_id"] = max(int(activity_id), int(seen.get("last_activity_id") or 0))
    if ftp is not None:
        seen["ftp"] = int(ftp)
    user.prefs = {**prefs, "notices": seen}
    db.commit()


def backfill(db: Session, user: User) -> int:
    """Verlauf rückwirkend: wöchentlich (jeweils Sonntag) die Schätzung aus den 90 Tagen davor, seit der ersten Aktivität."""
    first = db.scalar(select(func.min(Activity.day)).where(Activity.user_id == user.id))
    if not first:
        return 0
    d = first + timedelta(days=(6 - first.weekday()))
    n = 0
    last = None
    while d < today():
        est = estimate(db, user, end=d)
        key = (est["ftp"], est["vo2max"])
        if (est["ftp"] or est["vo2max"]) and key != last:
            store(db, user, est, d)
            n += 1
        last = key
        d += timedelta(days=7)
    store(db, user, estimate(db, user))
    return n


def backfill_async(user_id: int) -> None:
    import threading

    from .database import SessionLocal

    def run():
        with SessionLocal() as db:
            user = db.get(User, user_id)
            if not user:
                return
            try:
                backfill(db, user)
                user.prefs = {**(user.prefs or {}), "perf_backfilled": 1}
                db.commit()
            except Exception:
                db.rollback()
    threading.Thread(target=run, daemon=True, name=f"perf-backfill-{user_id}").start()
