"""Körperzusammensetzung je Segment (Withings) und Vergleich mit dem Training."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import segments as SG
from ..database import get_db
from ..models import User
from ..security import current_user
from ..timeutil import today

router = APIRouter(prefix="/api", tags=["data"])


@router.get("/body-segments")
def body_segments(days: int = Query(90, ge=7, le=730), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Muskel-, Fett- und fettfreie Masse je Segment, Veränderung im Zeitraum und Trainingsbelastung je Region."""
    return SG.overview(db, user, days, today())


class LabelsIn(BaseModel):
    labels: dict[str, str]


@router.put("/body-segments/labels")
def set_labels(data: LabelsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Segment-Codes Körperteilen zuordnen ({"3": "left_leg", …}); leer = automatische Zuordnung."""
    clean = {}
    for k, v in data.labels.items():
        if not str(k).lstrip("-").isdigit() or v not in SG.PARTS:
            raise HTTPException(422, "Ungültige Zuordnung")
        clean[str(int(k))] = v
    user.prefs = {**(user.prefs or {}), "segment_labels": clean}
    db.commit()
    return SG.overview(db, user, 90, today())
