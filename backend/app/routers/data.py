"""Auswertungen: Startseite, Messgrößen, Aktivitäten, Schlaf, Vergleiche."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import metrics as M
from .. import providers
from ..database import get_db
from ..models import Activity, Connection, Sample, SleepSession, User
from ..security import current_user
from ..sports import SPORTS
from ..store import daily_series, priority_for, rank, sources_for
from ..timeutil import today, tz
from .account import DEFAULT_GOALS

router = APIRouter(prefix="/api", tags=["data"])

HOME_DEFAULT = ["weight", "resting_hr", "hrv", "sleep_duration", "readiness", "vo2max"]


def _range(days: int | None, start: str | None, end: str | None) -> tuple[date, date]:
    e = date.fromisoformat(end) if end else today()
    if start:
        s = date.fromisoformat(start)
    else:
        s = e - timedelta(days=(days or 30) - 1)
    if s > e:
        s, e = e, s
    if (e - s).days > 3660 * 2:
        raise HTTPException(422, "Zeitraum zu groß")
    return s, e


def _stats(values: list[float], better: str | None) -> dict:
    if not values:
        return {}
    n = len(values)
    avg = sum(values) / n
    out = {"avg": avg, "min": min(values), "max": max(values), "first": values[0], "last": values[-1], "count": n}
    if n >= 3:  # Trend: Steigung der Ausgleichsgeraden pro Woche
        xs = range(n)
        mx = (n - 1) / 2
        sxx = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (v - avg) for x, v in zip(xs, values)) / sxx if sxx else 0
        out["trend_per_week"] = slope * 7
    return out


def group_series(series: list[dict], metric: M.Metric, group: str) -> list[dict]:
    if group == "day":
        return series
    buckets: dict[str, list[float]] = defaultdict(list)
    for p in series:
        d = date.fromisoformat(p["day"])
        key = (d - timedelta(days=d.weekday())).isoformat() if group == "week" else d.replace(day=1).isoformat()
        buckets[key].append(p["value"])
    out = []
    for k in sorted(buckets):
        vals = buckets[k]
        v = sum(vals) / len(vals)  # Schnitt pro Tag, auch bei Summen: Wochen und Monate bleiben vergleichbar
        out.append({"day": k, "value": round(v, 3), "n": len(vals)})
    return out


def _goal(user: User, metric: str):
    return {**DEFAULT_GOALS, **((user.prefs or {}).get("goals") or {})}.get(metric)


@router.get("/metrics/{key}")
def metric_detail(key: str, days: int | None = Query(None, ge=1, le=7300), start: str | None = None, end: str | None = None,
                  group: str = Query("day", pattern="^(day|week|month)$"), source: str | None = None,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = M.get(key)
    if m is None:
        raise HTTPException(404, "Unbekannte Messgröße")
    s, e = _range(days, start, end)
    series = daily_series(db, user, key, s, e, source)
    prev = daily_series(db, user, key, s - (e - s) - timedelta(days=1), s - timedelta(days=1), source)
    vals = [p["value"] for p in series]
    st = _stats(vals, m.better)
    if prev and vals:
        st["prev_avg"] = sum(p["value"] for p in prev) / len(prev)
    return {
        "metric": {**M.catalog_entry(key)}, "start": s.isoformat(), "end": e.isoformat(), "group": group,
        "series": group_series(series, m, group), "stats": st, "sources": sources_for(db, user.id, key),
        "priority": priority_for(user, key), "goal": _goal(user, key),
    }


@router.get("/summary")
def summary(keys: str = "", days: int = Query(30, ge=7, le=365), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Jüngster Wert, Vergleich zum Schnitt und kleiner Verlauf für mehrere Messgrößen."""
    wanted = [k for k in keys.split(",") if k in M.METRICS] or HOME_DEFAULT
    e = today()
    s = e - timedelta(days=days - 1)
    out = []
    for k in wanted:
        series = daily_series(db, user, k, s, e)
        if not series:
            last_day = db.scalar(select(func.max(Sample.day)).where(Sample.user_id == user.id, Sample.metric == k))
            if last_day:
                series = daily_series(db, user, k, last_day - timedelta(days=days - 1), last_day)
        vals = [p["value"] for p in series]
        last = series[-1] if series else None
        base = vals[:-1] or vals
        out.append({
            "key": k, "metric": M.catalog_entry(k), "last": last,
            "avg": sum(base) / len(base) if base else None,
            "spark": [{"day": p["day"], "value": p["value"]} for p in series],
        })
    return out


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = today()
    goals = {**DEFAULT_GOALS, **((user.prefs or {}).get("goals") or {})}

    def day_value(metric: str, d: date):
        s = daily_series(db, user, metric, d, d)
        return s[0]["value"] if s else None

    week_start = t - timedelta(days=6)
    # Bewegung der letzten 7 Tage aus den Aktivitäten
    acts = db.scalars(select(Activity).where(Activity.user_id == user.id, Activity.duplicate_of.is_(None),
                                             Activity.day >= week_start - timedelta(days=7)).order_by(Activity.start.desc())).all()
    days = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        da = [a for a in acts if a.day == d]
        days.append({"day": d.isoformat(), "minutes": round(sum((a.duration_s or a.moving_s or 0) for a in da) / 60),
                     "count": len(da), "sports": sorted({a.sport for a in da})})
    this_week = [a for a in acts if a.day >= week_start]
    prev_week = [a for a in acts if week_start - timedelta(days=7) <= a.day < week_start]

    def totals(items):
        return {"count": len(items), "minutes": round(sum((a.duration_s or a.moving_s or 0) for a in items) / 60),
                "distance_km": round(sum((a.distance_m or 0) for a in items) / 1000, 1),
                "calories": round(sum((a.calories or 0) for a in items))}
    # letzte Nacht
    sleep = best_sleep(db, user, t - timedelta(days=2), t)
    last_sleep = sleep[-1] if sleep else None
    conns = db.scalars(select(Connection).where(Connection.user_id == user.id)).all()
    yesterday = t - timedelta(days=1)
    return {
        "today": t.isoformat(),
        "rings": [
            {"key": "steps", "label": "Schritte", "value": day_value("steps", t), "yesterday": day_value("steps", yesterday), "goal": goals.get("steps")},
            {"key": "active_minutes", "label": "Aktive Minuten", "value": day_value("active_minutes", t),
             "yesterday": day_value("active_minutes", yesterday), "goal": goals.get("active_minutes")},
            {"key": "sleep_duration", "label": "Schlaf", "value": last_sleep["asleep_min"] if last_sleep else None,
             "goal": goals.get("sleep_duration")},
        ],
        "readiness": _readiness(db, user, t),
        "week": {"days": days, "totals": totals(this_week), "prev": totals(prev_week)},
        "recent": [activity_out(a) for a in acts[:6]],
        "sleep": last_sleep,
        "connections": {"total": len(conns), "ok": len([c for c in conns if c.status == "ok"]),
                        "problems": [{"provider": c.provider, "name": providers.name_of(c.provider), "status": c.status,
                                      "error": c.last_error} for c in conns if c.status in ("error", "auth")]},
        "demo": any((c.config or {}).get("demo") for c in conns),
        "has_data": db.scalar(select(Sample.id).where(Sample.user_id == user.id).limit(1)) is not None
                    or bool(acts) or bool(sleep),
    }


def _readiness(db: Session, user: User, t: date) -> dict | None:
    """Bereitschaft: Wert eines Anbieters (Oura, WHOOP, Garmin) oder eigene Schätzung aus HRV und Ruhepuls."""
    for key in ("readiness", "recovery", "body_battery"):
        s = daily_series(db, user, key, t - timedelta(days=1), t)
        if s:
            return {"value": s[-1]["value"], "source": s[-1]["source"], "key": key, "day": s[-1]["day"], "estimated": False}
    hrv = daily_series(db, user, "hrv", t - timedelta(days=60), t)
    rhr = daily_series(db, user, "resting_hr", t - timedelta(days=60), t)
    if len(hrv) < 7 and len(rhr) < 7:
        return None
    score, parts = 50.0, []
    if len(hrv) >= 7 and hrv[-1]["day"] >= (t - timedelta(days=1)).isoformat():
        base = [p["value"] for p in hrv[:-1]]
        mean = sum(base) / len(base)
        sd = math.sqrt(sum((v - mean) ** 2 for v in base) / len(base)) or 1
        z = (hrv[-1]["value"] - mean) / sd
        score += max(-25, min(25, z * 12))
        parts.append("HRV")
    if len(rhr) >= 7 and rhr[-1]["day"] >= (t - timedelta(days=1)).isoformat():
        base = [p["value"] for p in rhr[:-1]]
        mean = sum(base) / len(base)
        sd = math.sqrt(sum((v - mean) ** 2 for v in base) / len(base)) or 1
        z = (rhr[-1]["value"] - mean) / sd
        score -= max(-25, min(25, z * 12))
        parts.append("Ruhepuls")
    if not parts:
        return None
    return {"value": round(max(0, min(100, score))), "source": "bodybase", "key": "readiness", "day": t.isoformat(),
            "estimated": True, "basis": parts}


# ---------- Aktivitäten ----------

def activity_out(a: Activity, full: bool = False) -> dict:
    out = {
        "id": a.id, "source": a.source, "source_name": providers.name_of(a.source), "sport": a.sport,
        "sport_label": SPORTS.get(a.sport, a.sport), "sport_raw": a.sport_raw, "name": a.name,
        "start": a.start.isoformat() + "Z", "day": a.day.isoformat(), "duration_s": a.duration_s, "moving_s": a.moving_s,
        "distance_m": a.distance_m, "elevation_m": a.elevation_m, "calories": a.calories, "avg_hr": a.avg_hr,
        "max_hr": a.max_hr, "avg_power": a.avg_power, "load": a.load, "volume_kg": a.volume_kg,
        "has_map": bool(a.polyline), "duplicate_of": a.duplicate_of,
    }
    if full:
        out["polyline"] = a.polyline
        out["details"] = a.details
    return out


@router.get("/activities")
def list_activities(sport: str | None = None, q: str | None = None, days: int | None = Query(None, ge=1, le=7300),
                    start: str | None = None, end: str | None = None, limit: int = Query(50, ge=1, le=500),
                    offset: int = Query(0, ge=0), user: User = Depends(current_user), db: Session = Depends(get_db)):
    cond = [Activity.user_id == user.id, Activity.duplicate_of.is_(None)]
    if sport:
        cond.append(Activity.sport == sport)
    if q:
        like = f"%{q.strip()[:60]}%"
        cond.append(or_(Activity.name.ilike(like), Activity.sport_raw.ilike(like)))
    if days or start or end:
        s, e = _range(days, start, end)
        cond += [Activity.day >= s, Activity.day <= e]
    total = db.scalar(select(func.count()).select_from(Activity).where(*cond)) or 0
    rows = db.scalars(select(Activity).where(*cond).order_by(Activity.start.desc()).offset(offset).limit(limit)).all()
    dup_sources = defaultdict(list)
    if rows:
        for a in db.scalars(select(Activity).where(Activity.duplicate_of.in_([r.id for r in rows]))):
            dup_sources[a.duplicate_of].append(providers.name_of(a.source))
    items = []
    for a in rows:
        o = activity_out(a)
        o["also_in"] = dup_sources.get(a.id, [])
        items.append(o)
    agg = db.execute(select(func.count(), func.sum(Activity.duration_s), func.sum(Activity.distance_m),
                            func.sum(Activity.calories), func.sum(Activity.elevation_m)).where(*cond)).one()
    return {"total": total, "items": items, "totals": {
        "count": agg[0] or 0, "duration_s": agg[1] or 0, "distance_m": agg[2] or 0, "calories": agg[3] or 0, "elevation_m": agg[4] or 0}}


@router.get("/activities/stats")
def activity_stats(days: int = Query(365, ge=7, le=3650), user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = today()
    s = e - timedelta(days=days - 1)
    rows = db.execute(select(Activity.day, Activity.sport, Activity.duration_s, Activity.moving_s, Activity.distance_m,
                             Activity.calories, Activity.load).where(
        Activity.user_id == user.id, Activity.duplicate_of.is_(None), Activity.day >= s, Activity.day <= e)).all()
    by_day: dict = defaultdict(float)
    by_sport: dict = defaultdict(lambda: {"count": 0, "minutes": 0.0, "distance_km": 0.0, "calories": 0.0})
    by_week: dict = defaultdict(lambda: defaultdict(float))
    load_day: dict = defaultdict(float)
    for day, sport, dur, mov, dist, cal, load in rows:
        mins = (dur or mov or 0) / 60
        by_day[day.isoformat()] += mins
        b = by_sport[sport]
        b["count"] += 1
        b["minutes"] += mins
        b["distance_km"] += (dist or 0) / 1000
        b["calories"] += cal or 0
        wk = (day - timedelta(days=day.weekday())).isoformat()
        by_week[wk][sport] += mins
        load_day[day] += load if load is not None else mins  # ohne Belastungswert zählen Minuten
    # Fitness (CTL, 42 Tage) und Ermüdung (ATL, 7 Tage) als exponentiell gleitende Mittel der Tagesbelastung
    ctl = atl = 0.0
    form = []
    d = s
    while d <= e:
        x = load_day.get(d, 0.0)
        ctl += (x - ctl) / 42
        atl += (x - atl) / 7
        form.append({"day": d.isoformat(), "fitness": round(ctl, 1), "fatigue": round(atl, 1), "form": round(ctl - atl, 1)})
        d += timedelta(days=1)
    return {
        "start": s.isoformat(), "end": e.isoformat(),
        "calendar": [{"day": k, "minutes": round(v)} for k, v in sorted(by_day.items())],
        "sports": sorted(({"sport": k, "label": SPORTS.get(k, k), **{kk: round(vv, 1) for kk, vv in v.items()}}
                          for k, v in by_sport.items()), key=lambda x: -x["minutes"]),
        "weeks": [{"week": k, "sports": {sp: round(m) for sp, m in v.items()}, "minutes": round(sum(v.values()))}
                  for k, v in sorted(by_week.items())],
        "load": form[-120:],
    }


@router.get("/activities/{activity_id}")
def get_activity(activity_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(Activity, activity_id)
    if a is None or a.user_id != user.id:
        raise HTTPException(404, "Aktivität nicht gefunden")
    primary = db.get(Activity, a.duplicate_of) if a.duplicate_of else a
    group = [primary] + list(db.scalars(select(Activity).where(Activity.duplicate_of == primary.id)))
    out = activity_out(a, full=True)
    out["versions"] = [{"id": x.id, "source": x.source, "source_name": providers.name_of(x.source), "primary": x.id == primary.id,
                        "name": x.name, "distance_m": x.distance_m, "duration_s": x.duration_s, "avg_hr": x.avg_hr,
                        "calories": x.calories} for x in group]
    if not out.get("polyline"):
        out["polyline"] = next((x.polyline for x in group if x.polyline), None)
    if not out.get("details"):
        out["details"] = next((x.details for x in group if x.details), None)
    return out


# ---------- Verknüpfen von Einheiten aus mehreren Quellen ----------

def linked_info(db: Session, a: Activity) -> dict:
    """Alles, was zu einer Einheit aus anderen Quellen bekannt ist, plus Vorschläge zum Verknüpfen."""
    from ..store import LINK_WINDOW, overlap_ratio
    primary = db.get(Activity, a.duplicate_of) if a.duplicate_of else a
    group = [primary] + list(db.scalars(select(Activity).where(Activity.duplicate_of == primary.id)))
    ids = {x.id for x in group}
    filled = (primary.details or {}).get("filled") or {}
    sources = [{"id": x.id, "source": x.source, "source_name": providers.name_of(x.source), "name": x.name,
                "sport": x.sport, "start": x.start.isoformat() + "Z", "duration_s": x.duration_s, "avg_hr": x.avg_hr,
                "max_hr": x.max_hr, "calories": x.calories, "load": x.load, "primary": x.id == primary.id,
                "manual": bool((x.details or {}).get("link_to"))} for x in group]
    cands = []
    for c in db.scalars(select(Activity).where(Activity.user_id == a.user_id, Activity.start >= primary.start - LINK_WINDOW,
                                               Activity.start <= primary.start + LINK_WINDOW, Activity.id.not_in(ids))):
        if c.duplicate_of in ids:
            continue
        cands.append({"id": c.id, "source_name": providers.name_of(c.source), "name": c.name, "sport": c.sport,
                      "start": c.start.isoformat() + "Z", "duration_s": c.duration_s, "avg_hr": c.avg_hr,
                      "overlap": round(overlap_ratio(primary, c), 2)})
    cands.sort(key=lambda c: -c["overlap"])
    names = {k: ("Einzelmessungen Puls" if v == "heart_rate" else providers.name_of(v)) for k, v in filled.items()}
    return {"activity_id": primary.id, "avg_hr": primary.avg_hr, "max_hr": primary.max_hr, "calories": primary.calories,
            "load": primary.load, "hr_zones": (primary.details or {}).get("hr_zones"), "filled_from": names,
            "sources": sources, "candidates": cands[:6]}


class LinkIn(BaseModel):
    target_id: int


@router.post("/activities/{activity_id}/link")
def link_activity(activity_id: int, data: LinkIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Eine Einheit von Hand einer anderen zuordnen (z. B. WHOOP-Workout zum Hevy-Training)."""
    from ..store import link_duplicates
    a, t = db.get(Activity, activity_id), db.get(Activity, data.target_id)
    if not a or not t or a.user_id != user.id or t.user_id != user.id or a.id == t.id:
        raise HTTPException(404, "Aktivität nicht gefunden")
    target = db.get(Activity, t.duplicate_of) if t.duplicate_of else t
    d = dict(a.details or {})
    d.pop("unlink", None)
    d["link_to"] = target.id
    a.details = d
    db.flush()
    link_duplicates(db, user.id, a)
    db.commit()
    return linked_info(db, target)


@router.post("/activities/{activity_id}/unlink")
def unlink_activity(activity_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Eine Einheit aus ihrer Gruppe lösen; sie wird dann einzeln gezählt und nicht mehr automatisch verknüpft."""
    from ..store import link_duplicates
    a = db.get(Activity, activity_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Aktivität nicht gefunden")
    keep = db.get(Activity, a.duplicate_of) if a.duplicate_of else None
    if keep is None:  # die Hauptquelle selbst lösen: alle anderen lösen sich von ihr
        others = list(db.scalars(select(Activity).where(Activity.duplicate_of == a.id)))
        if not others:
            return linked_info(db, a)
        keep, a = a, None
        for o in others:
            d = dict(o.details or {})
            d.pop("link_to", None)
            d["unlink"] = True
            o.details = d
            o.duplicate_of = None
        db.flush()
        link_duplicates(db, user.id, others[0])
        db.commit()
        return linked_info(db, keep)
    d = dict(a.details or {})
    d.pop("link_to", None)
    d["unlink"] = True
    a.details = d
    db.flush()
    link_duplicates(db, user.id, a)
    db.commit()
    return linked_info(db, keep)


@router.get("/activities/{activity_id}/linked")
def activity_linked(activity_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(Activity, activity_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Aktivität nicht gefunden")
    return linked_info(db, a)


@router.delete("/activities/{activity_id}", status_code=204)
def delete_activity(activity_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(Activity, activity_id)
    if a is None or a.user_id != user.id:
        raise HTTPException(404, "Aktivität nicht gefunden")
    for d in db.scalars(select(Activity).where(Activity.duplicate_of == a.id)):
        d.duplicate_of = None
    db.delete(a)
    db.commit()


# ---------- Schlaf ----------

def best_sleep(db: Session, user: User, s: date, e: date) -> list[dict]:
    """Pro Nacht die Schlafphase der bevorzugten Quelle."""
    rows = db.scalars(select(SleepSession).where(SleepSession.user_id == user.id, SleepSession.day >= s, SleepSession.day <= e,
                                                 SleepSession.nap.isnot(True))).all()
    order = priority_for(user, "sleep_duration")
    best: dict = {}
    for r in rows:
        cur = best.get(r.day)
        if cur is None or rank(order, r.source) < rank(order, cur.source) or \
                (r.source == cur.source and (r.asleep_min or 0) > (cur.asleep_min or 0)):
            best[r.day] = r
    return [{"day": d.isoformat(), "source": r.source, "source_name": providers.name_of(r.source),
             "start": r.start.isoformat() + "Z", "end": r.end.isoformat() + "Z", "asleep_min": r.asleep_min,
             "deep_min": r.deep_min, "rem_min": r.rem_min, "light_min": r.light_min, "awake_min": r.awake_min,
             "score": r.score, "efficiency": r.efficiency, "avg_hr": r.avg_hr, "hrv": r.hrv}
            for d, r in sorted(best.items())]


@router.get("/sleep")
def sleep(days: int = Query(30, ge=1, le=3650), user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = today()
    s = e - timedelta(days=days - 1)
    nights = best_sleep(db, user, s, e)
    if not nights:  # nur Tageswerte (z. B. intervals.icu): aus den Messwerten
        series = daily_series(db, user, "sleep_duration", s, e)
        nights = [{"day": p["day"], "source": p["source"], "source_name": providers.name_of(p["source"]), "asleep_min": p["value"]}
                  for p in series]

    def avg(key):
        vals = [n[key] for n in nights if n.get(key) is not None]
        return sum(vals) / len(vals) if vals else None
    # Schlafrhythmus: mittlere Zubett- und Aufstehzeit (Minuten nach 18 Uhr bzw. nach Mitternacht, Ortszeit)
    beds, wakes = [], []
    for n in nights:
        if n.get("start") and n.get("end"):
            st = datetime.fromisoformat(n["start"][:-1]).replace(tzinfo=timezone.utc).astimezone(tz())
            en = datetime.fromisoformat(n["end"][:-1]).replace(tzinfo=timezone.utc).astimezone(tz())
            beds.append(((st.hour - 18) % 24) * 60 + st.minute)
            wakes.append(en.hour * 60 + en.minute)
    return {
        "nights": nights, "goal": _goal(user, "sleep_duration"),
        "avg": {k: avg(k) for k in ("asleep_min", "deep_min", "rem_min", "light_min", "awake_min", "score", "efficiency", "avg_hr", "hrv")},
        "bedtime_avg": (sum(beds) / len(beds) + 18 * 60) % 1440 if beds else None,
        "wake_avg": sum(wakes) / len(wakes) if wakes else None,
    }


# ---------- Vergleich zweier Messgrößen ----------

@router.get("/compare")
def compare(a: str, b: str, days: int = Query(90, ge=14, le=3650), lag: int = Query(0, ge=-7, le=7),
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    if a not in M.METRICS or b not in M.METRICS:
        raise HTTPException(404, "Unbekannte Messgröße")
    e = today()
    s = e - timedelta(days=days - 1)
    sa = {p["day"]: p["value"] for p in daily_series(db, user, a, s, e)}
    sb = {p["day"]: p["value"] for p in daily_series(db, user, b, s - timedelta(days=7), e + timedelta(days=7))}
    pairs = []
    for day, va in sa.items():
        d2 = (date.fromisoformat(day) + timedelta(days=lag)).isoformat()
        if d2 in sb:
            pairs.append({"day": day, "a": va, "b": sb[d2]})
    r = None
    if len(pairs) >= 5:
        xa = [p["a"] for p in pairs]
        xb = [p["b"] for p in pairs]
        ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
        cov = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
        va = math.sqrt(sum((x - ma) ** 2 for x in xa))
        vb = math.sqrt(sum((y - mb) ** 2 for y in xb))
        r = cov / (va * vb) if va and vb else None
    return {"a": M.catalog_entry(a), "b": M.catalog_entry(b), "pairs": sorted(pairs, key=lambda p: p["day"]), "r": r, "lag": lag,
            "series_a": [{"day": k, "value": v} for k, v in sorted(sa.items())],
            "series_b": [{"day": k, "value": v} for k, v in sorted(sb.items()) if s.isoformat() <= k <= e.isoformat()]}


@router.get("/overview")
def overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Welche Messgrößen liegen vor (für Trends und die Kategorie-Seiten)?"""
    rows = db.execute(select(Sample.metric, func.count(), func.min(Sample.day), func.max(Sample.day)).where(
        Sample.user_id == user.id).group_by(Sample.metric)).all()
    have = {m: {"count": n, "first": f.isoformat(), "last": la.isoformat()} for m, n, f, la in rows}
    return {"metrics": have}
