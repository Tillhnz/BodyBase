"""Gewohnheiten: Ziele, die wöchentlich steigen, Serien und Anrechnung auf die Muskeln."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Exercise, Habit, HabitLog

REPS_PER_SET = 12  # so viele Wiederholungen zählen in der Körperkarte wie ein Arbeitssatz


class HabitError(ValueError):
    pass


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def target_for(h: Habit, d: date) -> float | None:
    """Ziel an einem Tag: Startziel plus Erhöhung für jede volle Woche seit der Startwoche (neue Woche ab Montag)."""
    if h.kind == "check":
        return 1.0
    if h.target is None:
        return None
    weeks = max(0, (week_start(d) - week_start(h.start)).days // 7)
    t = h.target + (h.increment or 0) * weeks
    if h.max_target:
        t = min(t, h.max_target)
    return max(0.0, t)


def due_on(h: Habit, d: date) -> bool:
    if d < h.start:
        return False
    return not h.weekdays or d.weekday() in h.weekdays


def is_done(h: Habit, d: date, value: float | None) -> bool:
    if value is None or value <= 0:
        return False
    t = target_for(h, d)
    return value >= (t or 1)


def streak(h: Habit, logs: dict, today: date) -> int:
    """Erledigte fällige Tage in Folge; heute zählt, sobald erledigt (sonst ab gestern)."""
    n = 0
    d = today if is_done(h, today, logs.get(today)) else today - timedelta(days=1)
    for _ in range(1000):
        if d < h.start:
            break
        if due_on(h, d):
            if not is_done(h, d, logs.get(d)):
                break
            n += 1
        d -= timedelta(days=1)
    return n


def habit_dict(db: Session, h: Habit, today: date, days: int = 28) -> dict:
    start = today - timedelta(days=max(days, 400))
    logs = {row.day: row.value for row in db.scalars(select(HabitLog).where(HabitLog.habit_id == h.id, HabitLog.day >= start))}
    recent = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        recent.append({"day": d.isoformat(), "value": logs.get(d), "target": target_for(h, d), "due": due_on(h, d),
                       "done": is_done(h, d, logs.get(d))})
    week = [x for x in recent if date.fromisoformat(x["day"]) >= week_start(today)]
    due_recent = [x for x in recent[-28:] if x["due"] and x["day"] != today.isoformat()]
    ex = db.get(Exercise, h.exercise_id) if h.exercise_id else None
    best = 0
    run = 0
    d = h.start
    while d <= today:  # längste Serie
        if due_on(h, d):
            run = run + 1 if is_done(h, d, logs.get(d)) else 0
            best = max(best, run)
        d += timedelta(days=1)
    return {
        "id": h.id, "name": h.name, "kind": h.kind, "exercise_id": h.exercise_id, "exercise": ex.name if ex else None,
        "unit": h.unit, "target": h.target, "increment": h.increment, "max_target": h.max_target, "start": h.start.isoformat(),
        "weekdays": h.weekdays or [], "color": h.color, "archived": bool(h.archived),
        "today": {"value": logs.get(today), "target": target_for(h, today), "due": due_on(h, today),
                  "done": is_done(h, today, logs.get(today))},
        "next_week_target": target_for(h, week_start(today) + timedelta(days=7)),
        "streak": streak(h, logs, today), "best_streak": best,
        "rate_28": round(sum(1 for x in due_recent if x["done"]) / len(due_recent), 2) if due_recent else None,
        "week_total": sum(x["value"] or 0 for x in week), "recent": recent,
    }


def clean(data: dict, db: Session, user_id: int) -> dict:
    name = (data.get("name") or "").strip()[:120]
    if not name:
        raise HabitError("Bitte gib der Gewohnheit einen Namen.")
    kind = data.get("kind") if data.get("kind") in ("count", "check") else "count"

    def num(k, lo=0, hi=100000):
        v = data.get(k)
        if v in (None, ""):
            return None
        try:
            v = float(str(v).replace(",", "."))
        except ValueError:
            raise HabitError("Bitte nur Zahlen eintragen.")
        return max(lo, min(hi, v))
    ex_id = data.get("exercise_id")
    if ex_id:
        e = db.get(Exercise, int(ex_id))
        if not e or (e.user_id is not None and e.user_id != user_id):
            raise HabitError("Übung nicht gefunden.")
    start = data.get("start")
    try:
        start = date.fromisoformat(start) if start else None
    except ValueError:
        raise HabitError("Ungültiges Startdatum.")
    target = num("target")
    if kind == "count" and not target:
        raise HabitError("Bitte ein Tagesziel eintragen (z. B. 20 Liegestütze).")
    return {
        "name": name, "kind": kind, "exercise_id": int(ex_id) if ex_id else None,
        "unit": (data.get("unit") or "").strip()[:20] or ("Wdh." if ex_id else None),
        "target": target, "increment": num("increment", -1000, 1000), "max_target": num("max_target"),
        "weekdays": sorted({int(x) for x in (data.get("weekdays") or []) if str(x).isdigit() and 0 <= int(x) <= 6}),
        "color": (data.get("color") or "")[:20] or None, "start": start,
    }


def log(db: Session, h: Habit, d: date, value: float | None = None, add: float | None = None) -> HabitLog | None:
    row = db.scalar(select(HabitLog).where(HabitLog.habit_id == h.id, HabitLog.day == d))
    if add is not None:
        value = (row.value if row else 0) + add
    if value is None or value <= 0:
        if row:
            db.delete(row)
        db.commit()
        return None
    value = min(value, 100000)
    if row is None:
        row = HabitLog(habit_id=h.id, user_id=h.user_id, day=d, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    return row


def purge_user(db: Session, user_id: int) -> None:
    db.execute(delete(HabitLog).where(HabitLog.user_id == user_id))
    db.execute(delete(Habit).where(Habit.user_id == user_id))


def muscle_load(db: Session, user_id: int, start: date) -> tuple[dict, list]:
    """Belastung durch Gewohnheiten mit Übung: Wiederholungen / REPS_PER_SET als Satz-Äquivalent."""
    from collections import defaultdict
    out: dict[str, float] = defaultdict(float)
    info = []
    habits = {h.id: h for h in db.scalars(select(Habit).where(Habit.user_id == user_id, Habit.exercise_id.is_not(None)))}
    if not habits:
        return {}, []
    totals: dict[int, float] = defaultdict(float)
    for row in db.scalars(select(HabitLog).where(HabitLog.user_id == user_id, HabitLog.day >= start,
                                                 HabitLog.habit_id.in_(list(habits)))):
        totals[row.habit_id] += row.value
    for hid, total in totals.items():
        h = habits[hid]
        e = db.get(Exercise, h.exercise_id)
        if not e or total <= 0:
            continue
        sets = total / REPS_PER_SET if e.kind in ("bodyweight", "weighted_bw", "weight_reps", "assisted_bw") else total / 60
        if e.primary not in ("other", "cardio", "full_body"):
            out[e.primary] += sets
        for m in e.secondary or []:
            out[m] += sets * 0.5
        info.append({"habit": h.name, "total": total, "unit": h.unit, "sets": round(sets, 1)})
    return dict(out), info
