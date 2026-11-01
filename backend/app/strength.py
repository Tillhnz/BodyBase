"""Krafttraining: Speichern von Trainings, Rekorde und Auswertungen (Nachbau der Hevy-Statistiken)."""
from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Activity, Exercise, Routine, User, Workout, WorkoutSet
from .store import ActivityIn, Writer
from .strength_catalog import CATALOG, MUSCLE_GROUPS, MUSCLES, SPORT_MUSCLES, guess_muscles
from .timeutil import local_day, parse_iso, utcnow

SET_TYPES = ("normal", "warmup", "failure", "drop")
SOURCE = "strength"  # Quelle der gespiegelten Aktivitäten
MAX_SETS = 400
MAX_EXERCISES = 60


class StrengthError(ValueError):
    """Ungültige Eingabe, Meldung für die Oberfläche."""


# ---------- Katalog ----------

def seed_catalog(db: Session) -> None:
    """Eingebaute Übungen anlegen oder aktualisieren (beim Start, idempotent)."""
    existing = {e.key: e for e in db.scalars(select(Exercise).where(Exercise.user_id.is_(None)))}
    for item in CATALOG:
        row = existing.get(item["key"])
        if row is None:
            row = Exercise(user_id=None, key=item["key"])
            db.add(row)
        row.name, row.equipment, row.primary = item["name"], item["equipment"], item["primary"]
        row.secondary, row.kind, row.aliases = item["secondary"], item["kind"], item["aliases"]
        from . import strength_media
        row.media = strength_media.media_for_catalog(item["key"], [*item["aliases"], item["name"]], item["equipment"])
        row.media_checked = True
    db.commit()


def assign_media(db: Session) -> int:
    """Eigene Übungen (z. B. aus Hevy) mit Bildern verknüpfen; ohne Muskelzuordnung auch die Muskeln übernehmen."""
    from . import strength_media
    n = 0
    for e in db.scalars(select(Exercise).where(Exercise.user_id.is_not(None), Exercise.media_checked.is_not(True))):
        e.media_checked = True
        mid = strength_media.match([e.name, *(e.aliases or [])], e.equipment)
        if not mid:
            continue
        e.media = mid
        n += 1
        if e.primary == "other":
            mus = strength_media.muscles_of(mid)
            if mus:
                e.primary, e.secondary = mus
    db.commit()
    return n


def assign_unknown_muscles(db: Session) -> int:
    """Eigene Übungen ohne Muskelzuordnung (z. B. aus früheren Importen) nachträglich zuordnen."""
    n = 0
    for e in db.scalars(select(Exercise).where(Exercise.user_id.is_not(None), Exercise.primary == "other")):
        guess = guess_muscles(e.name)
        if guess:
            e.primary, e.secondary = guess[0], guess[1]
            n += 1
    if n:
        db.commit()
    return n


def norm(name: str | None) -> str:
    s = (name or "").lower().replace("ß", "ss")
    s = re.sub(r"[^a-z0-9äöü]+", " ", s)
    return " ".join(s.split())


def exercises_for(db: Session, user_id: int, include_archived: bool = True) -> list[Exercise]:
    q = select(Exercise).where((Exercise.user_id.is_(None)) | (Exercise.user_id == user_id))
    rows = db.scalars(q).all()
    return [e for e in rows if include_archived or not e.archived]


def exercise_dict(e: Exercise, usage: dict | None = None) -> dict:
    u = (usage or {}).get(e.id) or {}
    return {
        "id": e.id, "name": e.name, "equipment": e.equipment, "primary": e.primary, "secondary": e.secondary or [],
        "kind": e.kind, "custom": e.user_id is not None, "archived": bool(e.archived), "aliases": e.aliases or [],
        "group": MUSCLE_GROUPS.get(e.primary, "Sonstiges"), "count": u.get("count", 0), "last": u.get("last"),
        "media": e.media,
    }


EQUIP_HINTS = {
    "barbell": "barbell", "langhantel": "barbell", "dumbbell": "dumbbell", "kurzhantel": "dumbbell", "machine": "machine",
    "maschine": "machine", "cable": "cable", "kabel": "cable", "bodyweight": "bodyweight", "kettlebell": "kettlebell",
    "band": "band", "smith machine": "smith", "multipresse": "smith", "ez bar": "ez_bar", "sz": "ez_bar",
    "plate": "plate", "assisted": "machine", "weighted": "bodyweight",
}


class Matcher:
    """Ordnet Übungsnamen aus Importen bekannten Übungen zu und legt fehlende als eigene an."""

    def __init__(self, db: Session, user_id: int):
        self.db, self.user_id = db, user_id
        self.by_name: dict[str, Exercise] = {}
        for e in exercises_for(db, user_id):
            for n in [e.name, *(e.aliases or [])]:
                key = norm(n)
                # eigene Übungen haben Vorrang vor eingebauten
                if key and (key not in self.by_name or e.user_id is not None):
                    self.by_name[key] = e
        self.created = 0

    def get(self, name: str, kind_hint: str | None = None) -> Exercise:
        key = norm(name)
        if not key:
            key, name = "unbenannt", "Unbenannte Übung"
        e = self.by_name.get(key)
        if e:
            return e
        m = re.search(r"\(([^)]+)\)\s*$", name or "")
        hint = norm(m.group(1)) if m else ""
        equipment = EQUIP_HINTS.get(hint, "other")
        kind = kind_hint or ("bodyweight" if equipment == "bodyweight" else "weight_reps")
        guess = guess_muscles(name)
        primary, secondary = guess if guess else ("other", [])
        if primary == "cardio" and not kind_hint:
            kind = "distance"
        from . import strength_media
        mid = strength_media.match([name], equipment)
        if primary == "other" and mid and strength_media.muscles_of(mid):
            primary, secondary = strength_media.muscles_of(mid)
        e = Exercise(user_id=self.user_id, name=name.strip()[:120], equipment=equipment, primary=primary, secondary=secondary,
                     kind=kind, aliases=[], media=mid, media_checked=True)
        self.db.add(e)
        self.db.flush()
        self.by_name[key] = e
        self.created += 1
        return e


# ---------- Kennzahlen ----------

def e1rm(kg: float | None, reps: int | None) -> float | None:
    """Geschätztes Maximalgewicht für eine Wiederholung (Epley; über 12 Wdh. ungenau, daher gedeckelt)."""
    if not kg or not reps or kg <= 0 or reps <= 0:
        return None
    if reps == 1:
        return float(kg)
    return kg * (1 + min(reps, 12) / 30)


def set_volume(s, kind: str) -> float:
    if s.type == "warmup" or not s.kg or not s.reps:
        return 0.0
    if kind in ("weight_reps", "weighted_bw"):
        return float(s.kg) * int(s.reps)
    return 0.0


def _num(v, cast=float, lo=None, hi=None):
    if v is None or v == "":
        return None
    try:
        x = cast(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return None
    if lo is not None and x < lo:
        return None
    if hi is not None and x > hi:
        return None
    return x


# ---------- Speichern ----------

def _parse_payload(db: Session, user_id: int, data: dict) -> tuple[dict, list[dict]]:
    name = (data.get("name") or "").strip()[:160] or "Training"
    start = parse_iso(data.get("start")) or utcnow()
    end = parse_iso(data.get("end"))
    if end is not None and end < start:
        end = None
    if end is not None and (end - start) > timedelta(hours=12):
        end = start + timedelta(hours=12)
    allowed = {e.id: e for e in exercises_for(db, user_id)}
    exercises = []
    total_sets = 0
    for i, ex in enumerate((data.get("exercises") or [])[:MAX_EXERCISES]):
        eid = _num(ex.get("exercise_id"), int)
        if eid not in allowed:
            raise StrengthError("Eine Übung gibt es nicht (mehr). Bitte aus der Liste wählen.")
        sets = []
        for s in (ex.get("sets") or []):
            t = s.get("type") if s.get("type") in SET_TYPES else "normal"
            row = {
                "type": t, "kg": _num(s.get("kg"), float, -500, 2000), "reps": _num(s.get("reps"), int, 0, 1000),
                "duration_s": _num(s.get("duration_s"), int, 0, 86400), "distance_m": _num(s.get("distance_m"), float, 0, 500000),
                "rpe": _num(s.get("rpe"), float, 1, 10),
            }
            if all(row[k] is None for k in ("kg", "reps", "duration_s", "distance_m")):
                continue  # leere Sätze nicht speichern
            sets.append(row)
        total_sets += len(sets)
        if total_sets > MAX_SETS:
            raise StrengthError(f"Höchstens {MAX_SETS} Sätze pro Training.")
        exercises.append({
            "exercise_id": eid, "notes": (ex.get("notes") or "").strip()[:500] or None,
            "rest_s": _num(ex.get("rest_s"), int, 0, 3600), "superset": _num(ex.get("superset"), int, 0, 99),
            "sets": sets, "_ex": allowed[eid],
        })
    head = {"name": name, "notes": (data.get("notes") or "").strip()[:2000] or None, "start": start.replace(microsecond=0),
            "end": end.replace(microsecond=0) if end else None, "routine_id": _num(data.get("routine_id"), int)}
    return head, exercises


def save_workout(db: Session, user: User, data: dict, workout: Workout | None = None, source: str = "bodybase",
                 source_id: str | None = None, mirror: bool = True) -> Workout:
    head, exercises = _parse_payload(db, user.id, data)
    if not any(ex["sets"] for ex in exercises):
        raise StrengthError("Das Training enthält keine erledigten Sätze.")
    if workout is None and source_id:
        workout = db.scalar(select(Workout).where(Workout.user_id == user.id, Workout.source == source,
                                                  Workout.source_id == source_id))
    if workout is None:
        workout = Workout(user_id=user.id, source=source, source_id=source_id or f"tmp-{utcnow().timestamp()}")
        db.add(workout)
    workout.name, workout.notes, workout.start, workout.end = head["name"], head["notes"], head["start"], head["end"]
    workout.routine_id = head["routine_id"]
    workout.day = local_day(workout.start)
    workout.updated_at = utcnow()
    workout.layout = [{k: ex[k] for k in ("exercise_id", "notes", "rest_s", "superset")} for ex in exercises if ex["sets"]]
    if "hr" in data:
        workout.hr = clean_hr(data.get("hr"), workout.start)
    db.flush()
    if workout.source_id.startswith("tmp-"):
        workout.source_id = str(workout.id)
    db.execute(delete(WorkoutSet).where(WorkoutSet.workout_id == workout.id))
    volume, sets_count, reps = 0.0, 0, 0
    pos = 0
    for ex in exercises:
        if not ex["sets"]:
            continue
        for j, s in enumerate(ex["sets"]):
            ws = WorkoutSet(workout_id=workout.id, user_id=user.id, exercise_id=ex["exercise_id"], start=workout.start,
                            ex_pos=pos, pos=j, **s)
            db.add(ws)
            if s["type"] != "warmup":
                sets_count += 1
                reps += s["reps"] or 0
                volume += set_volume(ws, ex["_ex"].kind)
        pos += 1
    workout.volume_kg = round(volume, 1)
    workout.sets_count = sets_count
    workout.reps = reps
    db.flush()
    workout.prs = find_prs(db, user.id, workout)
    db.commit()
    if mirror:
        mirror_activity(db, user, workout)
    return workout


def clean_hr(hr, start: datetime) -> dict | None:
    """Live aufgezeichneter Puls: {start, t: [s], v: [bpm], marks: [[s, text]]} prüfen und verdichten."""
    from . import heartrate
    if not isinstance(hr, dict):
        return None
    t, v = hr.get("t") or [], hr.get("v") or []
    if not isinstance(t, list) or not isinstance(v, list) or len(t) != len(v) or len(t) > 20000:
        return None
    base = parse_iso(hr.get("start")) or start
    pts = []
    for x, y in zip(t, v):
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and 0 <= x <= 43200:
            pts.append((base + timedelta(seconds=float(x)), float(y)))
    marks = []
    for m in (hr.get("marks") or [])[:400]:
        if isinstance(m, list) and len(m) == 2 and isinstance(m[0], (int, float)):
            marks.append([round((base - start).total_seconds() + float(m[0])), str(m[1])[:60]])
    s = heartrate.make_series(start, pts, str(hr.get("source") or "bluetooth")[:40], marks)
    if s and hr.get("device"):
        s["device"] = str(hr["device"])[:60]
    return s


def purge_user(db: Session, user_id: int) -> None:
    """Alle Krafttraining-Daten eines Kontos löschen (SQLite kennt kein ON DELETE CASCADE ohne Pragma)."""
    from .models import ActiveWorkout
    for model in (WorkoutSet, Workout, Routine, ActiveWorkout):
        db.execute(delete(model).where(model.user_id == user_id))
    db.execute(delete(Exercise).where(Exercise.user_id == user_id))


def delete_workout(db: Session, workout: Workout) -> None:
    db.execute(delete(Activity).where(Activity.user_id == workout.user_id, Activity.source == SOURCE,
                                      Activity.source_id == f"w{workout.id}"))
    db.execute(delete(WorkoutSet).where(WorkoutSet.workout_id == workout.id))
    db.delete(workout)
    db.commit()


def mirror_activity(db: Session, user: User, w: Workout) -> None:
    """Das Training erscheint auch unter Aktivitäten (Kalender, Belastung, Wochenübersicht)."""
    sets = db.scalars(select(WorkoutSet).where(WorkoutSet.workout_id == w.id).order_by(WorkoutSet.ex_pos, WorkoutSet.pos)).all()
    names = {e.id: e.name for e in exercises_for(db, user.id)}
    blocks: list[dict] = []
    for s in sets:
        if not blocks or blocks[-1]["_pos"] != s.ex_pos:
            blocks.append({"_pos": s.ex_pos, "name": names.get(s.exercise_id, "Übung"), "sets": []})
        blocks[-1]["sets"].append({"kg": s.kg, "reps": s.reps, "type": s.type})
    for b in blocks:
        b.pop("_pos")
    duration = (w.end - w.start).total_seconds() if w.end else None
    writer = Writer(db, user.id, SOURCE)
    details = {"exercises": blocks, "sets": w.sets_count, "workout_id": w.id}
    if w.hr:
        details["hr"] = w.hr
    row = writer.activity(ActivityIn(
        source_id=f"w{w.id}", start=w.start, sport="strength", sport_raw="strength", name=w.name, duration_s=duration,
        volume_kg=w.volume_kg or None, details=details,
        avg_hr=(w.hr or {}).get("avg"), max_hr=(w.hr or {}).get("max"),
    ))
    if row is not None and not w.hr and (row.details or {}).get("hr", {}).get("source") == "bluetooth":
        row.details = {k: v for k, v in row.details.items() if k != "hr"}  # Verlauf wurde entfernt
        db.commit()
    if row is not None and not w.hr:
        from . import heartrate
        heartrate.attach(db, row)
        db.commit()
    writer.flush()


# ---------- Rekorde ----------

def _bests(sets: list, kind: str) -> dict:
    work = [s for s in sets if s.type != "warmup"]
    out = {}
    kgs = [s.kg for s in work if s.kg and s.reps]
    if kgs and kind in ("weight_reps", "weighted_bw"):
        out["weight"] = max(kgs)
        orms = [e1rm(s.kg, s.reps) for s in work if s.kg and s.reps]
        out["e1rm"] = max(x for x in orms if x is not None) if any(orms) else None
        out["set_volume"] = max(s.kg * s.reps for s in work if s.kg and s.reps)
    if kind == "assisted_bw" and kgs:
        out["assist"] = min(kgs)  # weniger Unterstützung ist besser
    reps = [s.reps for s in work if s.reps]
    if reps:
        out["reps"] = max(reps)
    durs = [s.duration_s for s in work if s.duration_s]
    if durs:
        out["duration"] = max(durs)
    dists = [s.distance_m for s in work if s.distance_m]
    if dists:
        out["distance"] = max(dists)
    return {k: v for k, v in out.items() if v is not None}


PR_LABELS = {"weight": "Schwerstes Gewicht", "e1rm": "Bestes 1RM (geschätzt)", "set_volume": "Bestes Satzvolumen",
             "reps": "Meiste Wiederholungen", "duration": "Längste Dauer", "distance": "Weiteste Strecke",
             "assist": "Wenigste Unterstützung"}


def find_prs(db: Session, user_id: int, w: Workout) -> list[dict]:
    sets = db.scalars(select(WorkoutSet).where(WorkoutSet.workout_id == w.id)).all()
    by_ex: dict[int, list] = defaultdict(list)
    for s in sets:
        by_ex[s.exercise_id].append(s)
    kinds = {e.id: e.kind for e in exercises_for(db, user_id)}
    prs = []
    for eid, ss in by_ex.items():
        kind = kinds.get(eid, "weight_reps")
        before = db.scalars(select(WorkoutSet).where(
            WorkoutSet.user_id == user_id, WorkoutSet.exercise_id == eid, WorkoutSet.start < w.start,
            WorkoutSet.workout_id != w.id)).all()
        if not before:
            continue  # erstes Mal: noch kein Rekord
        old, new = _bests(before, kind), _bests(ss, kind)
        relevant = ("weight", "e1rm", "set_volume") if kind in ("weight_reps", "weighted_bw") else \
            ("assist", "reps") if kind == "assisted_bw" else ("duration", "distance") if kind in ("duration", "distance") else ("reps",)
        for k in relevant:
            if k not in new or k not in old:
                continue
            better = new[k] < old[k] if k == "assist" else new[k] > old[k] + 1e-9
            if better:
                prs.append({"exercise_id": eid, "type": k, "label": PR_LABELS[k], "value": round(new[k], 2),
                            "previous": round(old[k], 2)})
    return prs


# ---------- Ausgabe ----------

def workout_dict(db: Session, w: Workout, full: bool = False, names: dict | None = None) -> dict:
    out = {
        "id": w.id, "name": w.name, "notes": w.notes, "start": w.start.isoformat() + "Z",
        "end": w.end.isoformat() + "Z" if w.end else None, "day": w.day.isoformat(), "source": w.source,
        "duration_s": int((w.end - w.start).total_seconds()) if w.end else None, "volume_kg": w.volume_kg,
        "sets": w.sets_count, "reps": w.reps, "prs": w.prs or [], "routine_id": w.routine_id,
    }
    sets = db.scalars(select(WorkoutSet).where(WorkoutSet.workout_id == w.id).order_by(WorkoutSet.ex_pos, WorkoutSet.pos)).all()
    if names is None:
        names = {e.id: e for e in exercises_for(db, w.user_id)}
    layout = list(w.layout or [])
    blocks: list[dict] = []
    for s in sets:
        while len(blocks) <= s.ex_pos:
            meta = layout[len(blocks)] if len(blocks) < len(layout) else {}
            blocks.append({"exercise_id": meta.get("exercise_id", s.exercise_id), "notes": meta.get("notes"),
                           "rest_s": meta.get("rest_s"), "superset": meta.get("superset"), "sets": []})
        blocks[s.ex_pos]["exercise_id"] = s.exercise_id
        blocks[s.ex_pos]["sets"].append({"type": s.type, "kg": s.kg, "reps": s.reps, "duration_s": s.duration_s,
                                         "distance_m": s.distance_m, "rpe": s.rpe})
    for b in blocks:
        e = names.get(b["exercise_id"])
        b["name"] = e.name if e else "Übung"
        b["kind"] = e.kind if e else "weight_reps"
        b["primary"] = e.primary if e else "other"
        b["secondary"] = (e.secondary or []) if e else []
        b["best"] = _best_set_text(b["sets"], b["kind"])
    if full:
        out["exercises"] = blocks
        act = db.scalar(select(Activity).where(Activity.user_id == w.user_id, Activity.source == SOURCE,
                                               Activity.source_id == f"w{w.id}"))
        if act is not None:
            from .routers.data import linked_info
            out["linked"] = linked_info(db, act)
    else:
        out["exercises"] = [{"exercise_id": b["exercise_id"], "name": b["name"], "sets": len([s for s in b["sets"] if s["type"] != "warmup"]),
                             "best": b["best"]} for b in blocks]
    return out


def _fmt(v: float | None) -> str:
    if v is None:
        return "–"
    return f"{v:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _best_set_text(sets: list[dict], kind: str) -> str | None:
    work = [s for s in sets if s["type"] != "warmup"] or sets
    if not work:
        return None
    if kind in ("weight_reps", "weighted_bw", "assisted_bw"):
        best = max(work, key=lambda s: (e1rm(s["kg"], s["reps"]) or 0, s["reps"] or 0))
        if best["kg"]:
            sign = "−" if kind == "assisted_bw" else ("+" if kind == "weighted_bw" else "")
            return f"{sign}{_fmt(best['kg'])} kg × {best['reps'] or 0}"
        return f"{best['reps'] or 0} Wdh."
    if kind == "duration":
        best = max(work, key=lambda s: s["duration_s"] or 0)
        d = best["duration_s"] or 0
        return f"{d // 60}:{d % 60:02d} min"
    if kind == "distance":
        best = max(work, key=lambda s: s["distance_m"] or 0)
        return f"{_fmt((best['distance_m'] or 0) / 1000)} km"
    best = max(work, key=lambda s: s["reps"] or 0)
    return f"{best['reps'] or 0} Wdh."


def previous_sets(db: Session, user_id: int, exercise_ids: list[int], before: datetime | None = None) -> dict:
    """Sätze der letzten Einheit je Übung (Spalte „Vorher“ beim Eintragen)."""
    out = {}
    for eid in exercise_ids[:80]:
        q = select(WorkoutSet).where(WorkoutSet.user_id == user_id, WorkoutSet.exercise_id == eid)
        if before is not None:
            q = q.where(WorkoutSet.start < before)
        last = db.scalar(q.order_by(WorkoutSet.start.desc(), WorkoutSet.pos.desc()).limit(1))
        if not last:
            continue
        sets = db.scalars(select(WorkoutSet).where(WorkoutSet.workout_id == last.workout_id, WorkoutSet.exercise_id == eid)
                          .order_by(WorkoutSet.ex_pos, WorkoutSet.pos)).all()
        out[str(eid)] = [{"type": s.type, "kg": s.kg, "reps": s.reps, "duration_s": s.duration_s, "distance_m": s.distance_m}
                         for s in sets]
    return out


def exercise_stats(db: Session, user_id: int, e: Exercise) -> dict:
    sets = db.scalars(select(WorkoutSet).where(WorkoutSet.user_id == user_id, WorkoutSet.exercise_id == e.id)
                      .order_by(WorkoutSet.start, WorkoutSet.ex_pos, WorkoutSet.pos)).all()
    by_w: dict[int, list] = defaultdict(list)
    for s in sets:
        by_w[s.workout_id].append(s)
    workouts = {w.id: w for w in db.scalars(select(Workout).where(Workout.id.in_(list(by_w) or [0])))}
    sessions = []
    rep_records: dict[int, dict] = {}
    for wid, ss in by_w.items():
        w = workouts.get(wid)
        if not w:
            continue
        work = [s for s in ss if s.type != "warmup"]
        b = _bests(ss, e.kind)
        vol = sum(set_volume(s, e.kind) for s in ss)
        sessions.append({
            "workout_id": wid, "name": w.name, "day": w.day.isoformat(), "start": w.start.isoformat() + "Z",
            "heaviest": b.get("weight"), "e1rm": round(b["e1rm"], 1) if b.get("e1rm") else None,
            "best_set_volume": b.get("set_volume"), "volume": round(vol, 1) or None,
            "reps": sum(s.reps or 0 for s in work) or None, "duration": b.get("duration"), "distance": b.get("distance"),
            "sets": [{"type": s.type, "kg": s.kg, "reps": s.reps, "duration_s": s.duration_s, "distance_m": s.distance_m,
                      "rpe": s.rpe} for s in ss],
        })
        for s in work:
            if s.reps and s.kg and 1 <= s.reps <= 15:
                cur = rep_records.get(s.reps)
                if cur is None or s.kg > cur["kg"]:
                    rep_records[s.reps] = {"reps": s.reps, "kg": s.kg, "day": w.day.isoformat(), "workout_id": wid}
    sessions.sort(key=lambda x: x["start"])

    def best(key):
        vals = [(x[key], x) for x in sessions if x.get(key)]
        if not vals:
            return None
        v, x = max(vals, key=lambda t: t[0])
        return {"value": v, "day": x["day"], "workout_id": x["workout_id"]}
    records = {k: best(k) for k in ("heaviest", "e1rm", "best_set_volume", "volume", "reps", "duration", "distance")}
    # Wiederholungs-Rekorde: nur behalten, was nicht von einem schwereren Satz mit mehr Wiederholungen übertroffen wird
    reps_sorted = sorted(rep_records.values(), key=lambda r: r["reps"])
    total = {"sessions": len(sessions), "sets": sum(len([s for s in x["sets"] if s["type"] != "warmup"]) for x in sessions),
             "reps": sum(x["reps"] or 0 for x in sessions), "volume": round(sum(x["volume"] or 0 for x in sessions), 1)}
    from . import strength_media
    return {"exercise": exercise_dict(e), "media": strength_media.info(e.media), "sessions": sessions, "records": records,
            "rep_records": reps_sorted,
            "total": total}


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def summary(db: Session, user_id: int, days: int, today_: date) -> dict:
    start_day = today_ - timedelta(days=days - 1) if days else date(1970, 1, 1)
    ws = db.scalars(select(Workout).where(Workout.user_id == user_id).order_by(Workout.start)).all()
    exs = {e.id: e for e in exercises_for(db, user_id)}
    in_range = [w for w in ws if w.day >= start_day]
    prev_start = start_day - timedelta(days=days) if days else None
    prev = [w for w in ws if prev_start and prev_start <= w.day < start_day]

    def totals(items):
        return {"workouts": len(items), "volume": round(sum(w.volume_kg or 0 for w in items)),
                "sets": sum(w.sets_count or 0 for w in items), "reps": sum(w.reps or 0 for w in items),
                "duration_s": int(sum((w.end - w.start).total_seconds() for w in items if w.end)),
                "prs": sum(len(w.prs or []) for w in items)}

    # Wochenwerte (letzte 12 bzw. so viele wie der Zeitraum)
    n_weeks = max(4, min(52, (days or 364) // 7))
    first_week = _week_start(today_) - timedelta(weeks=n_weeks - 1)
    weeks = {first_week + timedelta(weeks=i): {"workouts": 0, "volume": 0.0, "sets": 0, "reps": 0, "duration_s": 0}
             for i in range(n_weeks)}
    for w in ws:
        k = _week_start(w.day)
        if k in weeks:
            b = weeks[k]
            b["workouts"] += 1
            b["volume"] += w.volume_kg or 0
            b["sets"] += w.sets_count or 0
            b["reps"] += w.reps or 0
            b["duration_s"] += int((w.end - w.start).total_seconds()) if w.end else 0
    week_list = [{"week": k.isoformat(), **{kk: (round(v) if isinstance(v, float) else v) for kk, v in b.items()}}
                 for k, b in sorted(weeks.items())]

    # Muskelverteilung: Arbeitssätze je Hauptmuskel (Nebenmuskeln zählen halb)
    ids = [w.id for w in in_range]
    muscles: dict[str, float] = defaultdict(float)
    prev_muscles: dict[str, float] = defaultdict(float)
    ex_count: dict[int, int] = defaultdict(int)
    prev_ids = {w.id for w in prev}
    all_ids = ids + list(prev_ids)
    if all_ids:
        for s in db.scalars(select(WorkoutSet).where(WorkoutSet.workout_id.in_(all_ids), WorkoutSet.type != "warmup")):
            e = exs.get(s.exercise_id)
            if not e:
                continue
            target = prev_muscles if s.workout_id in prev_ids else muscles
            target[e.primary] += 1
            for m in e.secondary or []:
                target[m] += 0.5
            if s.workout_id not in prev_ids:
                ex_count[s.exercise_id] += 1
    muscle_list = sorted(({"muscle": m, "label": MUSCLES.get(m, m), "group": MUSCLE_GROUPS.get(m, "Sonstiges"),
                           "sets": round(v, 1), "previous": round(prev_muscles.get(m, 0), 1)} for m, v in muscles.items()),
                         key=lambda x: -x["sets"])
    groups: dict[str, float] = defaultdict(float)
    for m in muscle_list:
        groups[m["group"]] += m["sets"]
    top = sorted(ex_count.items(), key=lambda t: -t[1])[:8]

    # Serie: Wochen in Folge mit mindestens einem Training (die laufende Woche zählt, sobald trainiert wurde)
    trained_weeks = {_week_start(w.day) for w in ws}
    streak = 0
    wk = _week_start(today_)
    if wk not in trained_weeks:
        wk -= timedelta(weeks=1)
    while wk in trained_weeks:
        streak += 1
        wk -= timedelta(weeks=1)

    return {
        "totals": totals(in_range), "previous": totals(prev) if days else None, "weeks": week_list,
        "muscles": muscle_list, "groups": [{"group": g, "sets": round(v, 1)} for g, v in sorted(groups.items(), key=lambda t: -t[1])],
        "top_exercises": [{"exercise_id": eid, "name": exs[eid].name, "sets": n} for eid, n in top if eid in exs],
        "streak_weeks": streak, "days": _calendar(ws, today_),
        "all_time": {"workouts": len(ws), "volume": round(sum(w.volume_kg or 0 for w in ws))},
    }


def _calendar(ws: list, today_: date) -> list[dict]:
    mins: dict[str, int] = defaultdict(int)
    for w in ws:
        if w.day >= today_ - timedelta(days=370):
            dur = int((w.end - w.start).total_seconds() // 60) if w.end else 45
            mins[w.day.isoformat()] += max(1, dur)
    return [{"day": d, "minutes": m} for d, m in sorted(mins.items())]


FULL_BODY = {"chest": 0.3, "upper_back": 0.3, "lats": 0.3, "shoulders": 0.3, "quads": 0.3, "glutes": 0.3, "hamstrings": 0.2,
             "abs": 0.3, "biceps": 0.15, "triceps": 0.15}


def body_load(db: Session, user_id: int, days: int, today_: date) -> dict:
    """Beanspruchung je Muskel über alle Sportarten.

    Krafttraining: jeder Arbeitssatz zählt 1 für den Hauptmuskel und 0,5 für Nebenmuskeln.
    Andere Sportarten: je 10 Minuten ein Gewicht je Muskel (SPORT_MUSCLES), grob vergleichbar mit einem Satz.
    """
    from .sports import SPORTS
    start = today_ - timedelta(days=days - 1) if days else date(1970, 1, 1)
    strength: dict[str, float] = defaultdict(float)
    other: dict[str, float] = defaultdict(float)
    exs = {e.id: e for e in exercises_for(db, user_id)}
    wids = [w.id for w in db.scalars(select(Workout).where(Workout.user_id == user_id, Workout.day >= start))]
    sets_total = 0
    if wids:
        for s in db.scalars(select(WorkoutSet).where(WorkoutSet.workout_id.in_(wids), WorkoutSet.type != "warmup")):
            e = exs.get(s.exercise_id)
            if not e or e.primary == "cardio":
                continue
            sets_total += 1
            if e.primary == "full_body":
                for m, w in FULL_BODY.items():
                    strength[m] += w
            elif e.primary != "other":
                strength[e.primary] += 1
            for m in e.secondary or []:
                if m in MUSCLES and m not in ("cardio", "full_body", "other"):
                    strength[m] += 0.5
    from . import habits as H
    habit_load, habit_info = H.muscle_load(db, user_id, start)
    sources: dict[str, dict] = {}
    per_sport: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    acts = db.scalars(select(Activity).where(Activity.user_id == user_id, Activity.day >= start,
                                             Activity.duplicate_of.is_(None), Activity.source.not_in([SOURCE, "hevy"])))
    for a in acts:
        weights = SPORT_MUSCLES.get(a.sport)
        minutes = ((a.moving_s or a.duration_s) or 0) / 60
        if not weights or minutes <= 0:
            continue
        src = sources.setdefault(a.sport, {"sport": a.sport, "label": SPORTS.get(a.sport, a.sport), "minutes": 0, "count": 0})
        src["minutes"] += round(minutes)
        src["count"] += 1
        for m, w in weights.items():
            other[m] += minutes / 10 * w
            per_sport[a.sport][m] += minutes / 10 * w
    muscles = []
    for m in MUSCLES:
        if m in ("cardio", "full_body", "other"):
            continue
        v = strength.get(m, 0) + other.get(m, 0) + habit_load.get(m, 0)
        muscles.append({"muscle": m, "label": MUSCLES[m], "group": MUSCLE_GROUPS.get(m), "value": round(v, 1),
                        "strength": round(strength.get(m, 0), 1), "sports": round(other.get(m, 0), 1),
                        "habits": round(habit_load.get(m, 0), 1),
                        # aufgeschlüsselt nach Art, für den Filter der Körperkarte
                        "by": {k: round(v, 2) for k, v in (
                            [("strength", strength.get(m, 0)), ("habits", habit_load.get(m, 0))]
                            + [(sp, vals.get(m, 0)) for sp, vals in per_sport.items()]) if v > 0}})
    muscles.sort(key=lambda x: -x["value"])
    categories = []
    if sets_total:
        categories.append({"key": "strength", "label": "Krafttraining", "detail": f"{len(wids)} Trainings · {sets_total} Sätze"})
    for src in sorted(sources.values(), key=lambda x: -x["minutes"]):
        h, mnt = divmod(src["minutes"], 60)
        categories.append({"key": src["sport"], "label": src["label"],
                           "detail": f"{src['count']}× · {h}:{mnt:02d} h" if h else f"{src['count']}× · {mnt} min"})
    if habit_load:
        categories.append({"key": "habits", "label": "Gewohnheiten", "detail": ", ".join(i["habit"] for i in habit_info)})
    return {"days": days, "muscles": muscles, "categories": categories,
            "sources": sorted(sources.values(), key=lambda x: -x["minutes"]),
            "strength": {"workouts": len(wids), "sets": sets_total}, "habits": habit_info}


# ---------- Routinen ----------

def clean_routine(db: Session, user_id: int, data: dict) -> dict:
    allowed = {e.id for e in exercises_for(db, user_id)}
    exercises = []
    for ex in (data.get("exercises") or [])[:MAX_EXERCISES]:
        eid = _num(ex.get("exercise_id"), int)
        if eid not in allowed:
            continue
        sets = []
        for s in (ex.get("sets") or [])[:30]:
            sets.append({"type": s.get("type") if s.get("type") in SET_TYPES else "normal",
                         "kg": _num(s.get("kg"), float, -500, 2000), "reps": _num(s.get("reps"), int, 0, 1000),
                         "duration_s": _num(s.get("duration_s"), int, 0, 86400),
                         "distance_m": _num(s.get("distance_m"), float, 0, 500000)})
        exercises.append({"exercise_id": eid, "rest_s": _num(ex.get("rest_s"), int, 0, 3600),
                          "notes": (ex.get("notes") or "").strip()[:500] or None, "superset": _num(ex.get("superset"), int, 0, 99),
                          "sets": sets or [{"type": "normal", "kg": None, "reps": None}]})
    name = (data.get("name") or "").strip()[:120]
    if not name:
        raise StrengthError("Bitte gib der Routine einen Namen.")
    return {"name": name, "folder": (data.get("folder") or "").strip()[:80] or None,
            "notes": (data.get("notes") or "").strip()[:2000] or None, "exercises": exercises}


def routine_dict(r: Routine, names: dict) -> dict:
    exs = []
    for ex in r.exercises or []:
        e = names.get(ex.get("exercise_id"))
        if e is None:
            continue
        exs.append({**ex, "name": e.name, "kind": e.kind, "primary": e.primary, "equipment": e.equipment})
    return {"id": r.id, "name": r.name, "folder": r.folder, "notes": r.notes, "position": r.position or 0,
            "exercises": exs, "updated_at": r.updated_at.isoformat() + "Z"}


def routine_from_workout(db: Session, w: Workout, name: str | None = None) -> dict:
    full = workout_dict(db, w, full=True)
    return {"name": name or w.name, "exercises": [
        {"exercise_id": b["exercise_id"], "rest_s": b.get("rest_s"), "notes": b.get("notes"), "superset": b.get("superset"),
         "sets": [{k: s.get(k) for k in ("type", "kg", "reps", "duration_s", "distance_m")} for s in b["sets"]]}
        for b in full["exercises"]]}


# ---------- Import aus Hevy und Strong (CSV) ----------

HEVY_TYPES = {"warmup": "warmup", "normal": "normal", "failure": "failure", "dropset": "drop", "drop": "drop"}


MONTHS = {
    "jan": 1, "januar": 1, "january": 1, "jän": 1, "feb": 2, "februar": 2, "february": 2, "mär": 3, "mrz": 3, "märz": 3,
    "mar": 3, "march": 3, "apr": 4, "april": 4, "mai": 5, "may": 5, "jun": 6, "juni": 6, "june": 6, "jul": 7, "juli": 7,
    "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "okt": 10, "oct": 10, "oktober": 10,
    "october": 10, "nov": 11, "november": 11, "dez": 12, "dec": 12, "dezember": 12, "december": 12,
}


def _parse_dt(text: str | None) -> datetime | None:
    """Datum aus Hevy/Strong, in jeder Sprache der App. Zeiten sind Ortszeit.

    Beispiele: '28 Oct 2024, 18:05', '28. Okt. 2024, 18:05', 'Oct 28, 2024, 6:05 PM', '2024-10-28 18:05:00', '28.10.2024 18:05'
    """
    if not text:
        return None
    from datetime import timezone

    from .timeutil import tz
    t = text.strip().strip('"').strip()

    def local(y, mo, d, h=0, mi=0, sec=0):
        try:
            return datetime(y, mo, d, h, mi, sec).replace(tzinfo=tz()).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            return None

    # ISO und Zahlenformate
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?", t)
    if m and not re.search(r"(Z|[+-]\d{2}:?\d{2})$", t):
        return local(*(int(x or 0) for x in m.groups()))
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4}),?\s+(\d{1,2}):(\d{2})", t)
    if m:
        d, mo, y, h, mi = (int(x) for x in m.groups())
        return local(y, mo, d, h, mi)
    # Monatsnamen (deutsch, englisch …), mit 12-Stunden-Uhr
    ampm = re.search(r"\b(am|pm)\b", t, re.I)
    tm = re.search(r"(\d{1,2}):(\d{2})", t)
    words = re.findall(r"[A-Za-zÄÖÜäöü]+", t)
    month = next((MONTHS[w.lower().rstrip(".")] for w in words if w.lower().rstrip(".") in MONTHS), None)
    nums = [int(x) for x in re.findall(r"\d+", re.sub(r"\d{1,2}:\d{2}", " ", t))]
    year = next((n for n in nums if n > 1900), None)
    day = next((n for n in nums if 1 <= n <= 31), None)
    if month and year and day:
        h, mi = (int(tm.group(1)), int(tm.group(2))) if tm else (0, 0)
        if ampm:
            h = h % 12 + (12 if ampm.group(1).lower() == "pm" else 0)
        return local(year, month, day, h, mi)
    try:
        return parse_iso(t)
    except Exception:
        return None


def _import_routines(db: Session, user: User, reader, ex_col: str, title_col: str) -> dict:
    """Routinen ohne Datum (z. B. Hevy-Routinen-Export): je Titel eine Routine mit Übungen und Zielsätzen."""
    matcher = Matcher(db, user.id)
    routines: dict[str, dict] = {}
    for row in reader:
        g = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        title, ex_name = g.get(title_col), g.get(ex_col)
        if not title or not ex_name:
            continue
        r = routines.setdefault(title, {"name": title, "folder": g.get("folder") or g.get("folder_title") or None,
                                        "notes": g.get("description") or g.get("notes") or None, "exercises": []})
        e = matcher.get(ex_name)
        if not r["exercises"] or r["exercises"][-1]["exercise_id"] != e.id:
            rest = _num(g.get("rest_seconds") or g.get("rest_s") or g.get("rest"), int)
            r["exercises"].append({"exercise_id": e.id, "rest_s": rest if rest is not None else 90,
                                   "notes": g.get("exercise_notes") or None, "superset": _num(g.get("superset_id"), int), "sets": []})
        kg = _num(g.get("weight_kg") or g.get("weight"))
        reps = _num(g.get("reps"), int)
        if reps is None and g.get("rep_range_start"):
            reps = _num(g.get("rep_range_start"), int)
        r["exercises"][-1]["sets"].append({
            "type": HEVY_TYPES.get((g.get("set_type") or "normal").lower(), "normal"), "kg": kg, "reps": reps,
            "duration_s": _num(g.get("duration_seconds"), int), "distance_m": (_num(g.get("distance_km")) or 0) * 1000 or None})
    db.commit()
    if not routines:
        raise StrengthError("In der Datei wurden keine Routinen oder Trainings erkannt.")
    created = updated = 0
    for data in routines.values():
        values = clean_routine(db, user.id, data)
        row = db.scalar(select(Routine).where(Routine.user_id == user.id, Routine.name == values["name"]))
        if row is None:
            from sqlalchemy import func as _f
            pos = (db.scalar(select(_f.max(Routine.position)).where(Routine.user_id == user.id)) or 0) + 1
            row = Routine(user_id=user.id, position=pos, **values)
            db.add(row)
            created += 1
        else:
            for k, v in values.items():
                setattr(row, k, v)
            updated += 1
        row.updated_at = utcnow()
    db.commit()
    return {"source": "routines", "created": created, "updated": updated, "skipped": 0, "new_exercises": matcher.created}


def _strong_duration(text: str | None) -> int | None:
    """Strong: '1h 5m', '45m', '3600' (Sekunden)."""
    if not text:
        return None
    text = text.strip()
    if text.isdigit():
        return int(text)
    h = re.search(r"(\d+)\s*h", text)
    m = re.search(r"(\d+)\s*m", text)
    s = (int(h.group(1)) * 3600 if h else 0) + (int(m.group(1)) * 60 if m else 0)
    return s or None


def import_csv(db: Session, user: User, raw: bytes) -> dict:
    if raw[:2] == b"PK":  # manche Handys verpacken den Export als ZIP
        import zipfile
        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
            name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
        except zipfile.BadZipFile:
            name = None
        if not name:
            raise StrengthError("In der ZIP-Datei ist keine CSV-Datei.")
        raw = z.read(name)
    text = raw.decode("utf-8-sig", errors="replace")
    first = text.splitlines()[0] if text else ""
    delim = ";" if first.count(";") > first.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
    hevy = "exercise_title" in cols and "start_time" in cols
    strong = "exercise name" in cols and "date" in cols
    ex_col = next((c for c in ("exercise_title", "exercise name", "exercise", "übung") if c in cols), None)
    title_col = next((c for c in ("routine_title", "routine", "title", "routine name", "workout name", "name") if c in cols), None)
    if not hevy and not strong and ex_col and title_col:
        return _import_routines(db, user, reader, ex_col, title_col)
    if not hevy and not strong:
        found = ", ".join(list(cols)[:8]) or "keine"
        raise StrengthError("Unbekanntes Format. Erwartet wird der Export aus Hevy (workouts.csv) oder Strong (strong.csv). "
                            f"Gefundene Spalten: {found}")
    matcher = Matcher(db, user.id)
    groups: dict[str, dict] = {}
    bad_dates: list[str] = []
    for row in reader:
        g = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        if hevy:
            key = g.get("start_time", "") + "|" + g.get("title", "")
            start, end = _parse_dt(g.get("start_time")), _parse_dt(g.get("end_time"))
            title, ex_name = g.get("title") or "Training", g.get("exercise_title")
            set_type = HEVY_TYPES.get((g.get("set_type") or "normal").lower(), "normal")
            kg, reps = _num(g.get("weight_kg")), _num(g.get("reps"), int)
            if kg is None and g.get("weight_lbs"):
                kg = (_num(g.get("weight_lbs")) or 0) * 0.45359237 or None
            dist = (_num(g.get("distance_km")) or 0) * 1000 or None
            if dist is None and g.get("distance_miles"):
                dist = (_num(g.get("distance_miles")) or 0) * 1609.344 or None
            dur, rpe = _num(g.get("duration_seconds"), int), _num(g.get("rpe"))
            notes, wnotes, superset = g.get("exercise_notes"), g.get("description"), _num(g.get("superset_id"), int)
        else:
            key = g.get("date", "") + "|" + g.get("workout name", "")
            start = _parse_dt(g.get("date"))
            secs = _strong_duration(g.get("duration") or g.get("workout duration"))
            end = start + timedelta(seconds=secs) if start and secs else None
            title, ex_name = g.get("workout name") or "Training", g.get("exercise name")
            order = (g.get("set order") or "").upper()
            set_type = "warmup" if order == "W" else "drop" if order == "D" else "failure" if order == "F" else "normal"
            unit = (g.get("weight unit") or "kg").lower()
            kg = _num(g.get("weight"))
            if kg is not None and unit.startswith("lb"):
                kg *= 0.45359237
            reps, dur, rpe = _num(g.get("reps"), int), _num(g.get("seconds"), int), _num(g.get("rpe"))
            dist = _num(g.get("distance"))
            if dist is not None and (g.get("distance unit") or "m").lower() in ("km",):
                dist *= 1000
            notes, wnotes, superset = g.get("notes"), g.get("workout notes"), None
        if not start:
            raw_date = g.get("start_time") if hevy else g.get("date")
            if raw_date and len(bad_dates) < 3:
                bad_dates.append(raw_date)
            continue
        if not ex_name:
            continue
        wo = groups.setdefault(key, {"name": title, "start": start, "end": end, "notes": wnotes or None, "exercises": []})
        exercise = matcher.get(ex_name, "duration" if (dur and not reps and not kg) else None)
        if not wo["exercises"] or wo["exercises"][-1]["exercise_id"] != exercise.id:
            wo["exercises"].append({"exercise_id": exercise.id, "notes": notes or None, "superset": superset, "sets": []})
        wo["exercises"][-1]["sets"].append({"type": set_type, "kg": kg if kg else None, "reps": reps, "duration_s": dur,
                                            "distance_m": dist, "rpe": rpe})
    db.commit()
    if not groups:
        sample = next(iter(bad_dates), "")
        raise StrengthError(
            "In der Datei wurde kein Training erkannt." + (f" Das Datum „{sample}“ ist nicht lesbar." if sample else
                                                           " Die Datei enthält keine Sätze."))
    source = "hevy" if hevy else "strong"
    created = updated = skipped = 0
    for key, wo in sorted(groups.items(), key=lambda t: t[1]["start"]):
        sid = f"{wo['start'].isoformat()}|{wo['name']}"[:120]
        exists = db.scalar(select(Workout.id).where(Workout.user_id == user.id, Workout.source == source, Workout.source_id == sid))
        try:
            save_workout(db, user, {**wo, "start": wo["start"].isoformat(), "end": wo["end"].isoformat() if wo["end"] else None},
                         source=source, source_id=sid)
        except StrengthError:
            db.rollback()
            skipped += 1
            continue
        if exists:
            updated += 1
        else:
            created += 1
    return {"source": source, "created": created, "updated": updated, "skipped": skipped,
            "new_exercises": matcher.created}
