"""Gewohnheiten (z. B. tägliche Liegestütze mit wöchentlich steigendem Ziel) und Hinweise des Coaches."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import coach
from .. import habits as H
from ..database import get_db
from ..models import Habit, User
from ..security import current_user
from ..timeutil import today

router = APIRouter(prefix="/api", tags=["habits"])


class Body(BaseModel):
    model_config = {"extra": "allow"}


def _own(db: Session, user: User, habit_id: int) -> Habit:
    h = db.get(Habit, habit_id)
    if not h or h.user_id != user.id:
        raise HTTPException(404, "Gewohnheit nicht gefunden")
    return h


@router.get("/habits")
def list_habits(archived: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Habit).where(Habit.user_id == user.id)
    if not archived:
        q = q.where(Habit.archived.is_not(True))
    t = today()
    return [H.habit_dict(db, h, t) for h in db.scalars(q.order_by(Habit.position, Habit.id))]


@router.get("/habits/{habit_id}")
def get_habit(habit_id: int, days: int = 120, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return H.habit_dict(db, _own(db, user, habit_id), today(), days=max(7, min(days, 400)))


@router.post("/habits", status_code=201)
def create_habit(body: Body, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        v = H.clean(body.model_dump(), db, user.id)
    except H.HabitError as e:
        raise HTTPException(422, str(e))
    v["start"] = v["start"] or today()
    pos = (db.scalar(select(func.max(Habit.position)).where(Habit.user_id == user.id)) or 0) + 1
    h = Habit(user_id=user.id, position=pos, **v)
    db.add(h)
    db.commit()
    return H.habit_dict(db, h, today())


@router.put("/habits/{habit_id}")
def update_habit(habit_id: int, body: Body, user: User = Depends(current_user), db: Session = Depends(get_db)):
    h = _own(db, user, habit_id)
    data = body.model_dump()
    try:
        v = H.clean(data, db, user.id)
    except H.HabitError as e:
        raise HTTPException(422, str(e))
    v["start"] = v["start"] or h.start
    for k, val in v.items():
        setattr(h, k, val)
    if "archived" in data:
        h.archived = bool(data["archived"])
    db.commit()
    return H.habit_dict(db, h, today())


@router.delete("/habits/{habit_id}", status_code=204)
def delete_habit(habit_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from sqlalchemy import delete

    from ..models import HabitLog
    h = _own(db, user, habit_id)
    db.execute(delete(HabitLog).where(HabitLog.habit_id == h.id))
    db.delete(h)
    db.commit()


class LogIn(BaseModel):
    day: str | None = None
    value: float | None = None
    add: float | None = None


@router.post("/habits/{habit_id}/log")
def log_habit(habit_id: int, data: LogIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    h = _own(db, user, habit_id)
    try:
        d = date.fromisoformat(data.day) if data.day else today()
    except ValueError:
        raise HTTPException(422, "Ungültiges Datum")
    if d > today():
        raise HTTPException(422, "Für die Zukunft kann nichts eingetragen werden.")
    H.log(db, h, d, value=data.value, add=data.add)
    return H.habit_dict(db, h, today())


@router.get("/insights")
def insights(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return coach.insights(db, user.id, today())
