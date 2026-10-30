"""Krafttraining: Übungen, Routinen, Trainings, laufendes Training, Auswertungen, Import aus Hevy/Strong."""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import strength as S
from ..database import get_db
from ..models import ActiveWorkout, Exercise, ImportJob, Routine, User, Workout, WorkoutSet
from ..security import current_user
from ..strength_catalog import EQUIPMENT, KINDS, MUSCLE_GROUPS, MUSCLES
from ..timeutil import parse_iso, today, utcnow

router = APIRouter(prefix="/api/strength", tags=["strength"])


class Body(BaseModel):
    model_config = {"extra": "allow"}


def _payload(body: Body) -> dict:
    return body.model_dump()


def _bad(e: Exception):
    raise HTTPException(422, str(e))


# ---------- Stammdaten ----------

@router.get("/meta")
def meta(user: User = Depends(current_user)):
    return {"muscles": MUSCLES, "groups": MUSCLE_GROUPS, "equipment": EQUIPMENT, "kinds": KINDS,
            "set_types": {"normal": "Normal", "warmup": "Aufwärmen", "failure": "Bis Versagen", "drop": "Dropsatz"}}


def _usage(db: Session, user_id: int) -> dict:
    rows = db.execute(select(WorkoutSet.exercise_id, func.count(func.distinct(WorkoutSet.workout_id)), func.max(WorkoutSet.start))
                      .where(WorkoutSet.user_id == user_id).group_by(WorkoutSet.exercise_id)).all()
    return {eid: {"count": n, "last": last.isoformat() + "Z" if last else None} for eid, n, last in rows}


@router.get("/exercises")
def list_exercises(user: User = Depends(current_user), db: Session = Depends(get_db)):
    usage = _usage(db, user.id)
    items = [S.exercise_dict(e, usage) for e in S.exercises_for(db, user.id)]
    items.sort(key=lambda x: x["name"].lower())
    return items


def _own_exercise(db: Session, user: User, exercise_id: int) -> Exercise:
    e = db.get(Exercise, exercise_id)
    if not e or (e.user_id is not None and e.user_id != user.id):
        raise HTTPException(404, "Übung nicht gefunden")
    return e


def _exercise_values(data: dict) -> dict:
    name = (data.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(422, "Bitte einen Namen eingeben.")
    primary = data.get("primary") if data.get("primary") in MUSCLES else "other"
    return {
        "name": name, "equipment": data.get("equipment") if data.get("equipment") in EQUIPMENT else "other",
        "primary": primary, "secondary": [m for m in (data.get("secondary") or []) if m in MUSCLES and m != primary][:6],
        "kind": data.get("kind") if data.get("kind") in KINDS else "weight_reps",
    }


@router.post("/exercises", status_code=201)
def create_exercise(body: Body, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = Exercise(user_id=user.id, aliases=[], **_exercise_values(_payload(body)))
    db.add(e)
    db.commit()
    return S.exercise_dict(e)


@router.put("/exercises/{exercise_id}")
def update_exercise(exercise_id: int, body: Body, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = _own_exercise(db, user, exercise_id)
    if e.user_id is None:
        raise HTTPException(403, "Eingebaute Übungen lassen sich nicht ändern. Lege eine eigene an.")
    data = _payload(body)
    for k, v in _exercise_values(data).items():
        setattr(e, k, v)
    if "archived" in data:
        e.archived = bool(data["archived"])
    db.commit()
    return S.exercise_dict(e)


@router.delete("/exercises/{exercise_id}", status_code=204)
def delete_exercise(exercise_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = _own_exercise(db, user, exercise_id)
    if e.user_id is None:
        raise HTTPException(403, "Eingebaute Übungen lassen sich nicht löschen.")
    used = db.scalar(select(func.count()).select_from(WorkoutSet).where(WorkoutSet.exercise_id == e.id))
    if used:
        e.archived = True  # Verlauf bleibt erhalten, die Übung verschwindet nur aus der Auswahl
    else:
        db.delete(e)
    db.commit()


@router.get("/exercises/{exercise_id}")
def exercise_detail(exercise_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return S.exercise_stats(db, user.id, _own_exercise(db, user, exercise_id))


class PrevBody(BaseModel):
    ids: list[int]
    before: str | None = None


@router.post("/previous")
def previous(body: PrevBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return S.previous_sets(db, user.id, body.ids, parse_iso(body.before) if body.before else None)


# ---------- Trainings ----------

def _own_workout(db: Session, user: User, workout_id: int) -> Workout:
    w = db.get(Workout, workout_id)
    if not w or w.user_id != user.id:
        raise HTTPException(404, "Training nicht gefunden")
    return w


@router.get("/workouts")
def list_workouts(limit: int = Query(20, ge=1, le=100), before: str | None = None, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    q = select(Workout).where(Workout.user_id == user.id)
    if before:
        b = parse_iso(before)
        if b:
            q = q.where(Workout.start < b)
    rows = db.scalars(q.order_by(Workout.start.desc()).limit(limit)).all()
    names = {e.id: e for e in S.exercises_for(db, user.id)}
    return [S.workout_dict(db, w, names=names) for w in rows]


@router.get("/workouts/{workout_id}")
def get_workout(workout_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return S.workout_dict(db, _own_workout(db, user, workout_id), full=True)


@router.post("/workouts", status_code=201)
def create_workout(body: Body, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        w = S.save_workout(db, user, _payload(body))
    except S.StrengthError as e:
        _bad(e)
    db.query(ActiveWorkout).filter(ActiveWorkout.user_id == user.id).delete()
    db.commit()
    return S.workout_dict(db, w, full=True)


@router.put("/workouts/{workout_id}")
def update_workout(workout_id: int, body: Body, user: User = Depends(current_user), db: Session = Depends(get_db)):
    w = _own_workout(db, user, workout_id)
    try:
        w = S.save_workout(db, user, _payload(body), workout=w)
    except S.StrengthError as e:
        _bad(e)
    return S.workout_dict(db, w, full=True)


@router.delete("/workouts/{workout_id}", status_code=204)
def remove_workout(workout_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    S.delete_workout(db, _own_workout(db, user, workout_id))


# ---------- Laufendes Training ----------

@router.get("/active")
def get_active(user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(ActiveWorkout, user.id)
    return {"data": a.data if a else None, "updated_at": a.updated_at.isoformat() + "Z" if a else None}


@router.put("/active")
def put_active(body: Body, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = _payload(body)
    if len(str(data)) > 400_000:
        raise HTTPException(413, "Das Training ist zu groß.")
    a = db.get(ActiveWorkout, user.id)
    if a is None:
        a = ActiveWorkout(user_id=user.id, data=data)
        db.add(a)
    a.data = data
    a.updated_at = utcnow()
    db.commit()
    return {"ok": True, "updated_at": a.updated_at.isoformat() + "Z"}


@router.delete("/active", status_code=204)
def drop_active(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(ActiveWorkout).filter(ActiveWorkout.user_id == user.id).delete()
    db.commit()


# ---------- Routinen ----------

def _names(db: Session, user: User) -> dict:
    return {e.id: e for e in S.exercises_for(db, user.id)}


def _own_routine(db: Session, user: User, routine_id: int) -> Routine:
    r = db.get(Routine, routine_id)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Routine nicht gefunden")
    return r


@router.get("/routines")
def list_routines(user: User = Depends(current_user), db: Session = Depends(get_db)):
    names = _names(db, user)
    rows = db.scalars(select(Routine).where(Routine.user_id == user.id).order_by(Routine.position, Routine.name)).all()
    last = defaultdict(lambda: None)
    for rid, start in db.execute(select(Workout.routine_id, func.max(Workout.start)).where(
            Workout.user_id == user.id, Workout.routine_id.is_not(None)).group_by(Workout.routine_id)):
        last[rid] = start.isoformat() + "Z"
    return [{**S.routine_dict(r, names), "last_done": last[r.id]} for r in rows]


@router.get("/routines/{routine_id}")
def get_routine(routine_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return S.routine_dict(_own_routine(db, user, routine_id), _names(db, user))


@router.post("/routines", status_code=201)
def create_routine(body: Body, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        values = S.clean_routine(db, user.id, _payload(body))
    except S.StrengthError as e:
        _bad(e)
    pos = (db.scalar(select(func.max(Routine.position)).where(Routine.user_id == user.id)) or 0) + 1
    r = Routine(user_id=user.id, position=pos, updated_at=utcnow(), **values)
    db.add(r)
    db.commit()
    return S.routine_dict(r, _names(db, user))


@router.put("/routines/{routine_id}")
def update_routine(routine_id: int, body: Body, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _own_routine(db, user, routine_id)
    try:
        values = S.clean_routine(db, user.id, _payload(body))
    except S.StrengthError as e:
        _bad(e)
    for k, v in values.items():
        setattr(r, k, v)
    r.updated_at = utcnow()
    db.commit()
    return S.routine_dict(r, _names(db, user))


@router.delete("/routines/{routine_id}", status_code=204)
def delete_routine(routine_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own_routine(db, user, routine_id))
    db.commit()


@router.post("/workouts/{workout_id}/routine", status_code=201)
def routine_from_workout(workout_id: int, body: Body, user: User = Depends(current_user), db: Session = Depends(get_db)):
    w = _own_workout(db, user, workout_id)
    data = S.routine_from_workout(db, w, (_payload(body).get("name") or "").strip() or None)
    values = S.clean_routine(db, user.id, data)
    pos = (db.scalar(select(func.max(Routine.position)).where(Routine.user_id == user.id)) or 0) + 1
    r = Routine(user_id=user.id, position=pos, updated_at=utcnow(), **values)
    db.add(r)
    db.commit()
    return S.routine_dict(r, _names(db, user))


# ---------- Auswertung und Import ----------

@router.get("/summary")
def summary(days: int = Query(30, ge=0, le=3650), user: User = Depends(current_user), db: Session = Depends(get_db)):
    return S.summary(db, user.id, days, today())


@router.get("/body-load")
def body_load(days: int = Query(30, ge=0, le=3650), user: User = Depends(current_user), db: Session = Depends(get_db)):
    return S.body_load(db, user.id, days, today())


@router.post("/import")
async def import_file(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    raw = await file.read(30 * 1024 * 1024 + 1)
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(413, "Die Datei ist zu groß (höchstens 30 MB).")
    try:
        return S.import_csv(db, user, raw)
    except S.StrengthError as e:
        _bad(e)


# Hochladen in Stücken: Der Nginx Proxy Manager lässt ohne Anpassung nur 1 MB pro Anfrage durch und bricht
# größere Uploads mittendrin ab („Failed to fetch“). Das Einlesen läuft danach im Hintergrund, damit auch
# lange Importe nicht an der Wartezeit des Proxys scheitern.

CHUNK_MAX = 900 * 1024
UPLOAD_MAX = 60 * 1024 * 1024


def _part_path(user_id: int, upload_id: str) -> str:
    import os
    import re
    from ..config import settings
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", upload_id or ""):
        raise HTTPException(422, "Ungültige Upload-Kennung.")
    folder = os.path.join(settings.data_dir, "uploads")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"strength-{user_id}-{upload_id}.part")


def _run_import(job_id: int, user_id: int, path: str) -> None:
    import gzip
    import logging
    import os
    from ..database import SessionLocal
    log = logging.getLogger("bodybase.strength")
    with SessionLocal() as db:
        job = db.get(ImportJob, job_id)
        try:
            with open(path, "rb") as f:
                raw = f.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            user = db.get(User, user_id)
            job.status, job.progress = "running", 0.1
            db.commit()
            result = S.import_csv(db, user, raw)
            job = db.get(ImportJob, job_id)
            job.status, job.progress, job.counts, job.finished_at = "done", 1.0, result, utcnow()
            db.commit()
        except Exception as e:
            db.rollback()
            if not isinstance(e, (S.StrengthError, OSError)):
                log.exception("Krafttraining-Import fehlgeschlagen")
            job = db.get(ImportJob, job_id)
            job.status, job.message, job.finished_at = "failed", str(e)[:500] or type(e).__name__, utcnow()
            db.commit()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


@router.post("/import/chunk")
async def import_chunk(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    import os
    import threading
    h = request.headers
    try:
        index, total = int(h.get("x-chunk-index", "")), int(h.get("x-chunk-total", ""))
    except ValueError:
        raise HTTPException(422, "Angaben zum Teilstück fehlen.")
    if not (0 <= index < total <= 200):
        raise HTTPException(422, "Ungültiges Teilstück.")
    path = _part_path(user.id, h.get("x-upload-id", ""))
    body = await request.body()
    if len(body) > CHUNK_MAX + 1024:
        raise HTTPException(413, "Teilstück zu groß.")
    if index == 0 and os.path.exists(path):
        os.remove(path)
    if index > 0 and not os.path.exists(path):
        raise HTTPException(409, "Upload unterbrochen. Bitte die Datei erneut wählen.")
    with open(path, "ab") as f:
        f.write(body)
    if os.path.getsize(path) > UPLOAD_MAX:
        os.remove(path)
        raise HTTPException(413, "Die Datei ist zu groß (höchstens 60 MB).")
    if index < total - 1:
        return {"received": index + 1, "total": total}
    from urllib.parse import unquote
    job = ImportJob(user_id=user.id, kind="strength", filename=unquote(h.get("x-filename", "workouts.csv"))[:200],
                    status="queued", progress=0.0)
    db.add(job)
    db.commit()
    threading.Thread(target=_run_import, args=(job.id, user.id, path), daemon=True).start()
    return {"job_id": job.id}


@router.get("/import/{job_id}")
def import_status(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(ImportJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404, "Import nicht gefunden")
    return {"status": job.status, "progress": job.progress, "message": job.message, "result": job.counts}
