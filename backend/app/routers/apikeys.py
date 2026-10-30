"""Persönliche API-Schlüssel verwalten (nur mit Anmeldung in der App)."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..models import ApiKey, User
from ..security import hash_api_key, new_api_key, require_session
from ..timeutil import utcnow

router = APIRouter(prefix="/api/me/api-keys", tags=["api-keys"])
MAX_KEYS = 20


def _out(k: ApiKey) -> dict:
    iso = lambda d: d.isoformat() + "Z" if d else None  # noqa: E731
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "scope": k.scope, "created_at": iso(k.created_at),
            "last_used_at": iso(k.last_used_at), "expires_at": iso(k.expires_at)}


@router.get("")
def list_keys(user: User = Depends(require_session), db: Session = Depends(get_db)):
    return [_out(k) for k in db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.id.desc()))]


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: str = "read"
    expires_days: int | None = Field(default=None, ge=1, le=3650)


@router.post("", status_code=201)
def create_key(data: KeyIn, user: User = Depends(require_session), db: Session = Depends(get_db)):
    if (db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user.id)) or 0) >= MAX_KEYS:
        raise HTTPException(409, f"Höchstens {MAX_KEYS} Schlüssel. Lösche zuerst einen alten.")
    key = new_api_key()
    row = ApiKey(user_id=user.id, name=data.name.strip(), prefix=key[:9], key_hash=hash_api_key(key),
                 scope="write" if data.scope == "write" else "read",
                 expires_at=utcnow() + timedelta(days=data.expires_days) if data.expires_days else None)
    db.add(row)
    db.commit()
    audit.record(db, user.email, "apikey.create", f"{row.name} ({row.scope})")
    return {**_out(row), "key": key}  # der Schlüssel selbst wird nur dieses eine Mal gezeigt


@router.delete("/{key_id}", status_code=204)
def delete_key(key_id: int, user: User = Depends(require_session), db: Session = Depends(get_db)):
    row = db.get(ApiKey, key_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Schlüssel nicht gefunden")
    db.delete(row)
    db.commit()
    audit.record(db, user.email, "apikey.delete", row.name)
