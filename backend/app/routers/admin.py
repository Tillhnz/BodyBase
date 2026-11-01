"""Administration: Konten, Einladungen, Anbieter-Apps, Server-Optionen, Updates, Sicherungen, Protokoll."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from .. import audit, providers, server_settings, sync
from ..config import settings
from ..database import get_db
from ..models import Activity, AuditEvent, Connection, Invite, Sample, SleepSession, User
from ..security import hash_password, require_admin
from .auth import admins_left

router = APIRouter(prefix="/api/admin", tags=["admin"])
STARTED = time.time()


# ---------- Konten ----------

@router.get("/users")
def users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    out = []
    for u in db.scalars(select(User).order_by(User.id)):
        out.append({
            "id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active is not False,
            "created_at": u.created_at.isoformat() + "Z",
            "connections": db.scalar(select(func.count()).select_from(Connection).where(Connection.user_id == u.id)) or 0,
            "samples": db.scalar(select(func.count()).select_from(Sample).where(Sample.user_id == u.id)) or 0,
            "activities": db.scalar(select(func.count()).select_from(Activity).where(Activity.user_id == u.id)) or 0,
        })
    return out


class UserUpdateIn(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|user)$")
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)


@router.put("/users/{user_id}")
def update_user(user_id: int, data: UserUpdateIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Konto nicht gefunden")
    if u.id == admin.id and (data.role == "user" or data.active is False) and admins_left(db) <= 1:
        raise HTTPException(409, "Du bist der letzte Administrator.")
    if data.role:
        u.role = data.role
    if data.active is not None:
        u.active = data.active
        u.token_version = (u.token_version or 0) + 1
    if data.password:
        u.password_hash = hash_password(data.password)
        u.token_version = (u.token_version or 0) + 1
    db.commit()
    audit.record(db, admin.email, "user.update", f"{u.email}: " + ", ".join(k for k, v in data.model_dump().items() if v is not None and k != "password") +
                 (" Passwort neu gesetzt" if data.password else ""))
    return {"ok": True}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Konto nicht gefunden")
    if u.id == admin.id:
        raise HTTPException(409, "Das eigene Konto löschst du unter Einstellungen.")
    email = u.email
    for model in (Sample, SleepSession, Activity):
        db.execute(delete(model).where(model.user_id == u.id))
    from ..habits import purge_user as purge_habits
    from ..strength import purge_user
    purge_user(db, u.id)
    purge_habits(db, u.id)
    from ..models import ApiKey
    db.execute(delete(ApiKey).where(ApiKey.user_id == u.id))
    from ..models import BodySegment
    db.execute(delete(BodySegment).where(BodySegment.user_id == u.id))
    db.delete(u)
    db.commit()
    audit.record(db, admin.email, "user.delete", email)


# ---------- Einladungen ----------

class InviteIn(BaseModel):
    note: str | None = Field(default=None, max_length=120)


@router.get("/invites")
def invites(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(Invite).order_by(Invite.id.desc()).limit(100))
    base = settings.public_url.rstrip("/")
    return [{"id": i.id, "code": i.code, "note": i.note, "used_by": i.used_by_email, "used_at": i.used_at.isoformat() + "Z" if i.used_at else None,
             "created_at": i.created_at.isoformat() + "Z", "link": f"{base}/login?invite={i.code}"} for i in rows]


@router.post("/invites", status_code=201)
def create_invite(data: InviteIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    code = secrets.token_hex(5).upper()
    db.add(Invite(code=code, created_by=admin.email, note=(data.note or "").strip() or None))
    db.commit()
    audit.record(db, admin.email, "invite.create", data.note or "")
    return {"code": code, "link": f"{settings.public_url.rstrip('/')}/login?invite={code}"}


@router.delete("/invites/{invite_id}", status_code=204)
def delete_invite(invite_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    i = db.get(Invite, invite_id)
    if i:
        db.delete(i)
        db.commit()


# ---------- Anbieter-Apps ----------

@router.get("/providers")
def provider_apps(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    out = []
    for p in providers.all_providers():
        if not p.app_fields:
            continue
        users_connected = db.scalar(select(func.count()).select_from(Connection).where(Connection.provider == p.key)) or 0
        out.append({**p.describe(server_settings.app_ready(db, p)), "values": server_settings.app_public(db, p),
                    "redirect_uri": sync.redirect_uri(p.key), "connections": users_connected})
    return {"providers": out, "public_url": settings.public_url,
            "https": settings.public_url.startswith("https://")}


class AppIn(BaseModel):
    values: dict = Field(default_factory=dict)


@router.put("/providers/{provider_key}")
def save_provider_app(provider_key: str, data: AppIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = providers.get(provider_key)
    if p is None or not p.app_fields:
        raise HTTPException(404, "Unbekannter Anbieter")
    server_settings.set_app(db, p, data.values)
    audit.record(db, admin.email, "provider.app", f"{p.name} eingerichtet")
    return {"ready": server_settings.app_ready(db, p), "values": server_settings.app_public(db, p)}


@router.delete("/providers/{provider_key}", status_code=204)
def clear_provider_app(provider_key: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    server_settings.clear_app(db, provider_key)
    audit.record(db, admin.email, "provider.app", f"{provider_key} entfernt")


# ---------- Server-Optionen ----------

@router.get("/settings")
def get_options(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"values": server_settings.options(db), "public_url": settings.public_url}


class OptionsIn(BaseModel):
    values: dict


@router.put("/settings")
def put_options(data: OptionsIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        values = server_settings.save_options(db, data.values)
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit.record(db, admin.email, "settings", ", ".join(sorted(data.values)))
    return {"values": values}


# ---------- Updates und Sicherungen ----------

def _updater(method: str, path: str, timeout: float = 90):
    if not settings.updater_url:
        raise HTTPException(503, "Der Update-Dienst ist nicht eingerichtet. Aktualisiere im Container mit: bodybase update")
    token = hashlib.sha256(("updater:" + settings.secret_key).encode()).hexdigest()
    req = urllib.request.Request(settings.updater_url.rstrip("/") + path, method=method, headers={"X-Updater-Token": token},
                                 data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", "")
        except ValueError:
            msg = ""
        raise HTTPException(409 if e.code == 409 else 502, msg or f"Der Update-Dienst antwortet mit Fehler {e.code}.")
    except (urllib.error.URLError, OSError):
        raise HTTPException(503, "Der Update-Dienst ist nicht erreichbar. Aktualisiere im Container mit: bodybase update")


@router.get("/update")
def update_status(check: bool = False, admin: User = Depends(require_admin)):
    return _updater("GET", "/status" + ("?check=1" if check else ""))


@router.post("/update", status_code=202)
def start_update(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = _updater("POST", "/update")
    audit.record(db, admin.email, "update.start", "")
    return r


@router.get("/backups")
def list_backups(admin: User = Depends(require_admin)):
    return _updater("GET", "/backups")


@router.post("/backups", status_code=201)
def create_backup(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = _updater("POST", "/backups", timeout=600)
    audit.record(db, admin.email, "backup.create", r.get("name", ""))
    return r


# ---------- Protokoll und Zustand ----------

@router.get("/audit")
def audit_log(limit: int = 150, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(max(1, min(limit, 500))))
    return [{"id": r.id, "at": r.at.isoformat() + "Z", "actor": r.actor, "action": r.action, "text": r.text} for r in rows]


def _db_size(db: Session) -> int | None:
    try:
        if db.bind.dialect.name == "postgresql":
            return int(db.scalar(text("select pg_database_size(current_database())")))
        if db.bind.dialect.name == "sqlite":
            path = db.bind.url.database
            return os.path.getsize(path) if path and os.path.exists(path) else None
    except Exception:
        return None
    return None


@router.get("/status")
def status(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    conns = db.scalars(select(Connection)).all()
    by_status: dict = {}
    for c in conns:
        by_status[c.status] = by_status.get(c.status, 0) + 1
    try:
        _updater("GET", "/status", timeout=5)
        updater = True
    except HTTPException:
        updater = False
    return {
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "samples": db.scalar(select(func.count()).select_from(Sample)) or 0,
        "activities": db.scalar(select(func.count()).select_from(Activity)) or 0,
        "sleep": db.scalar(select(func.count()).select_from(SleepSession)) or 0,
        "connections": by_status, "db_bytes": _db_size(db), "uptime_s": int(time.time() - STARTED), "updater": updater,
        "public_url": settings.public_url, "timezone": settings.timezone,
    }
