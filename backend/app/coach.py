"""Hinweise und Lob aus den Trainingsdaten: vernachlässigte Muskelgruppen, Ungleichgewichte, Serien, Fortschritte.

Bewusst einfache, nachvollziehbare Regeln. Jede Aussage nennt ihren Grund, damit man sie einordnen kann.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import habits as H
from .models import Activity, Exercise, Habit, Workout, WorkoutSet
from .timeutil import local_hour_now

GROUPS = {
    "Brust": ["chest"], "Rücken": ["lats", "upper_back", "lower_back", "traps"], "Schultern": ["shoulders"],
    "Arme": ["biceps", "triceps", "forearms"], "Beine": ["quads", "hamstrings", "glutes", "calves", "adductors", "abductors"],
    "Rumpf": ["abs"],
}
# Gruppen sind unterschiedlich groß: Beine und Rücken sollen mehr abbekommen als Arme
GROUP_WEIGHT = {"Brust": 1.0, "Rücken": 1.4, "Schultern": 0.8, "Arme": 0.8, "Beine": 1.6, "Rumpf": 0.7}
SUGGEST = {
    "Brust": ["push_up", "bench_press_db", "fly_db"], "Rücken": ["pull_up", "seated_row", "db_row", "back_extension"],
    "Schultern": ["lateral_raise", "shoulder_press_db", "face_pull"], "Arme": ["curl_db", "triceps_pushdown", "hammer_curl"],
    "Beine": ["squat", "rdl", "leg_curl_seated", "hip_thrust"], "Rumpf": ["plank", "leg_raise_hanging", "cable_crunch"],
    "hamstrings": ["rdl", "leg_curl_lying", "good_morning"], "pull": ["pull_up", "seated_row", "face_pull"],
    "push": ["push_up", "shoulder_press_db", "dips_triceps"],
}
DAYS = 14


def _suggestions(db: Session, user_id: int, key: str, muscles: list[str] | None = None) -> list[dict]:
    """Zuerst Übungen, die man schon kennt (meist benutzt), dann bewährte aus dem Katalog."""
    out: list[dict] = []
    if muscles:
        rows = db.execute(select(Exercise.id, Exercise.name, func.count(WorkoutSet.id).label("n"))
                          .join(WorkoutSet, WorkoutSet.exercise_id == Exercise.id)
                          .where(WorkoutSet.user_id == user_id, Exercise.primary.in_(muscles))
                          .group_by(Exercise.id, Exercise.name).order_by(func.count(WorkoutSet.id).desc()).limit(2)).all()
        out += [{"id": r.id, "name": r.name, "known": True} for r in rows]
    for k in SUGGEST.get(key, []):
        e = db.scalar(select(Exercise).where(Exercise.key == k))
        if e and all(x["id"] != e.id for x in out):
            out.append({"id": e.id, "name": e.name, "known": False})
    return out[:3]


def insights(db: Session, user_id: int, today: date) -> list[dict]:
    from .strength import body_load
    cur = body_load(db, user_id, DAYS, today)
    by = {m["muscle"]: m["value"] for m in cur["muscles"]}
    groups = {g: sum(by.get(m, 0) for m in ms) for g, ms in GROUPS.items()}
    norm = {g: v / GROUP_WEIGHT[g] for g, v in groups.items()}
    total = sum(groups.values())
    both = body_load(db, user_id, 2 * DAYS, today)
    prev_total = sum(m["value"] for m in both["muscles"] if m["muscle"] in sum(GROUPS.values(), [])) - total
    out: list[dict] = []

    last = db.scalar(select(func.max(Activity.start)).where(Activity.user_id == user_id, Activity.duplicate_of.is_(None)))
    if total < 6:
        if last is None:
            return [{"type": "tip", "title": "Los geht's", "text": "Sobald Trainings, Aktivitäten oder Gewohnheiten da sind, bekommst du hier Hinweise, welche Muskeln zu kurz kommen und was gut läuft."}]
        days_ago = (today - last.date()).days
        if days_ago >= 7:
            out.append({"type": "tip", "title": f"Seit {days_ago} Tagen kein Training",
                        "text": "Schon 20 Minuten mit ein paar Grundübungen bringen dich zurück in den Rhythmus. Fang leicht an."})
    else:
        top = max(norm.values()) or 1
        neglected = [g for g, v in norm.items() if v < 0.12 * top]
        for g in sorted(neglected, key=lambda g: norm[g]):
            what = "gar nicht" if groups[g] == 0 else "kaum"
            out.append({"type": "warn", "title": f"{g} {what} trainiert",
                        "text": f"In den letzten {DAYS} Tagen kam {g.lower() if g != 'Rumpf' else 'der Rumpf'} {what} vor, während anderes regelmäßig dran war. "
                                "Zwei, drei Sätze pro Training reichen schon, um das auszugleichen.",
                        "group": g, "exercises": _suggestions(db, user_id, g, GROUPS[g])})
        # Ungleichgewichte innerhalb der trainierten Bereiche
        push = by.get("chest", 0) + 0.5 * by.get("shoulders", 0) + 0.5 * by.get("triceps", 0)
        pull = by.get("lats", 0) + by.get("upper_back", 0) + 0.5 * by.get("biceps", 0)
        if push >= 8 and pull < push / 1.6 and "Rücken" not in neglected:
            out.append({"type": "tip", "title": "Mehr ziehen als drücken",
                        "text": f"Drücken (Brust, Schultern) liegt deutlich vor Ziehen (Rücken): etwa {round(push)} zu {round(pull)}. "
                                "Mehr Zugübungen gleichen das aus und sind gut für die Haltung.",
                        "exercises": _suggestions(db, user_id, "pull", ["lats", "upper_back"])})
        quads, hams = by.get("quads", 0), by.get("hamstrings", 0)
        if quads >= 8 and hams < quads * 0.35 and "Beine" not in neglected:
            out.append({"type": "tip", "title": "Beinrückseite kommt zu kurz",
                        "text": "Die Oberschenkel vorne arbeiten viel (auch beim Radfahren), die Rückseite wenig. "
                                "Kreuzheben-Varianten oder Beinbeuger beugen Verletzungen und Knieproblemen vor.",
                        "exercises": _suggestions(db, user_id, "hamstrings", ["hamstrings"])})
        if not neglected and min(norm.values()) >= 0.3 * top:
            out.append({"type": "good", "title": "Ausgewogen trainiert",
                        "text": f"Alle großen Muskelgruppen waren in den letzten {DAYS} Tagen dabei. Genau so."})
        if prev_total >= 10:
            change = (total - prev_total) / prev_total
            if change >= 0.15:
                out.append({"type": "good", "title": "Mehr als in den zwei Wochen davor",
                            "text": f"Rund {round(change * 100)} % mehr Trainingsumfang. Achte darauf, genug zu schlafen, damit die Steigerung ankommt."})
            elif change <= -0.4:
                out.append({"type": "tip", "title": "Ruhigere Phase",
                            "text": f"Etwa {round(-change * 100)} % weniger als in den zwei Wochen davor. Als Erholung völlig in Ordnung; wenn nicht geplant, hilft ein fester Termin im Kalender."})

    # Serien im Krafttraining
    weeks = _strength_week_streak(db, user_id, today)
    if weeks >= 3:
        out.append({"type": "good", "title": f"{weeks} Wochen in Folge Krafttraining", "text": "Regelmäßigkeit schlägt alles andere. Weiter so."})
    prs = db.scalars(select(Workout).where(Workout.user_id == user_id, Workout.day >= today - timedelta(days=6))).all()
    n_prs = sum(len(w.prs or []) for w in prs)
    if n_prs:
        out.append({"type": "good", "title": f"{n_prs} neue {'Bestleistung' if n_prs == 1 else 'Bestleistungen'} diese Woche",
                    "text": "Du wirst stärker. Ein Blick in die Übungen zeigt, wo genau."})

    # Gewohnheiten
    hour = local_hour_now()
    for h in db.scalars(select(Habit).where(Habit.user_id == user_id, Habit.archived.is_not(True))):
        d = H.habit_dict(db, h, today, days=1)
        if d["streak"] >= 7:
            nxt = d["next_week_target"]
            extra = f" Ab Montag sind es {_fmt(nxt)} {h.unit or ''}.".rstrip(" .") + "." if h.increment and nxt else ""
            out.append({"type": "good", "title": f"{h.name}: {d['streak']} Tage in Folge", "text": f"Starke Serie.{extra}"})
        t = d["today"]
        if t["due"] and not t["done"] and hour >= 17:
            rest = (t["target"] or 1) - (t["value"] or 0)
            text = f"Heute fehlen noch {_fmt(rest)} {h.unit or ''}".rstrip() + "." if h.kind == "count" else "Heute noch nicht abgehakt."
            if d["streak"] >= 3:
                text += f" Deine Serie von {d['streak']} Tagen hält, wenn du es heute noch schaffst."
            out.append({"type": "tip", "title": f"{h.name} offen", "text": text, "habit_id": h.id})
    order = {"warn": 0, "tip": 1, "good": 2}
    out.sort(key=lambda x: order[x["type"]])
    return out[:8]


def _fmt(v) -> str:
    return str(int(v)) if v is not None and float(v).is_integer() else f"{v:.1f}".replace(".", ",")


def _strength_week_streak(db: Session, user_id: int, today: date) -> int:
    days = {r[0] for r in db.execute(select(Workout.day).where(Workout.user_id == user_id, Workout.day >= today - timedelta(weeks=60)))}
    weeks = {d - timedelta(days=d.weekday()) for d in days}
    wk = today - timedelta(days=today.weekday())
    if wk not in weeks:
        wk -= timedelta(weeks=1)
    n = 0
    while wk in weeks:
        n += 1
        wk -= timedelta(weeks=1)
    return n
