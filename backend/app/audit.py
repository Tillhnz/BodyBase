"""Ereignisprotokoll für die Administration (Anmeldungen, Verbindungen, Fehler). Keine Gesundheitsdaten."""
import logging

from sqlalchemy import delete, select

from .database import SessionLocal
from .models import AuditEvent

log = logging.getLogger("bodybase.audit")
KEEP = 2000


def record(db, actor: str, action: str, text: str | None = None) -> None:
    try:
        db.add(AuditEvent(actor=actor[:255], action=action[:60], text=(text or "")[:4000]))
        db.commit()
        _trim(db)
    except Exception:  # Protokoll darf nie die eigentliche Aktion stören
        db.rollback()
        log.exception("Ereignis konnte nicht gespeichert werden")


def event(actor: str, action: str, text: str | None = None) -> None:
    with SessionLocal() as db:
        record(db, actor, action, text)


def _trim(db) -> None:
    ids = db.scalars(select(AuditEvent.id).order_by(AuditEvent.id.desc()).offset(KEEP).limit(1)).all()
    if ids:
        db.execute(delete(AuditEvent).where(AuditEvent.id <= ids[0]))
        db.commit()
