"""Verbindungen zu den Anbietern: verbinden (OAuth oder Schlüssel), abgleichen, trennen."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import audit, crypto, providers, server_settings, sync
from ..database import get_db
from ..models import Activity, Connection, Sample, SleepSession, SyncRun, User
from ..providers.base import SyncError, authorize_url, pkce_pair, token_request
from ..providers.homeassistant import parse_mapping
from ..security import current_user, read_state, sign_state
from ..timeutil import utcnow

router = APIRouter(prefix="/api", tags=["connections"])


def conn_out(db: Session, c: Connection) -> dict:
    p = providers.get(c.provider)
    counts = {
        "samples": db.scalar(select(func.count()).select_from(Sample).where(Sample.user_id == c.user_id, Sample.source == c.provider)) or 0,
        "activities": db.scalar(select(func.count()).select_from(Activity).where(Activity.user_id == c.user_id, Activity.source == c.provider)) or 0,
        "sleep": db.scalar(select(func.count()).select_from(SleepSession).where(SleepSession.user_id == c.user_id, SleepSession.source == c.provider)) or 0,
    }
    last_day = db.scalar(select(func.max(Sample.day)).where(Sample.user_id == c.user_id, Sample.source == c.provider))
    config = dict(c.config or {})
    if c.provider == "homeassistant":
        config["mapping_text"] = "\n".join(f"{k} = {v}" for k, v in (config.get("mapping") or {}).items())
    return {
        "id": c.id, "provider": c.provider, "name": p.name if p else c.provider, "kind": p.kind if p else None,
        "enabled": c.enabled, "status": c.status, "account": c.account, "config": config,
        "last_sync_at": c.last_sync_at.isoformat() + "Z" if c.last_sync_at else None,
        "last_success_at": c.last_success_at.isoformat() + "Z" if c.last_success_at else None,
        "next_sync_at": c.next_sync_at.isoformat() + "Z" if c.next_sync_at else None,
        "last_error": c.last_error, "last_counts": c.last_counts, "syncing": sync.is_running(c.id) or bool(c.syncing),
        "data": counts, "last_data_day": last_day.isoformat() if last_day else None,
        "created_at": c.created_at.isoformat() + "Z",
    }


@router.get("/providers")
def list_providers(user: User = Depends(current_user), db: Session = Depends(get_db)):
    conns = {c.provider: c for c in db.scalars(select(Connection).where(Connection.user_id == user.id))}
    out = []
    for p in providers.all_providers():
        d = p.describe(server_settings.app_ready(db, p))
        d["redirect_uri"] = sync.redirect_uri(p.key) if p.kind == "oauth" else None
        c = conns.get(p.key)
        d["connection"] = conn_out(db, c) if c else None
        if p.kind in ("push", "file"):
            has = db.scalar(select(Sample.id).where(Sample.user_id == user.id, Sample.source == p.key).limit(1)) or \
                db.scalar(select(Activity.id).where(Activity.user_id == user.id, Activity.source == p.key).limit(1))
            d["has_data"] = bool(has)
        out.append(d)
    return out


def _get_conn(db: Session, user: User, conn_id: int) -> Connection:
    c = db.get(Connection, conn_id)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "Verbindung nicht gefunden")
    return c


def _provider(key: str):
    p = providers.get(key)
    if p is None:
        raise HTTPException(404, "Unbekannter Anbieter")
    return p


def _upsert(db: Session, user: User, provider_key: str) -> Connection:
    c = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == provider_key))
    if c is None:
        c = Connection(user_id=user.id, provider=provider_key, enabled=True, status="pending", config={}, cursor={})
        db.add(c)
        db.flush()
    elif (c.config or {}).get("demo"):
        c.config, c.cursor = {}, {}  # echte Verbindung ersetzt die Beispielquelle
    return c


# ---------- OAuth ----------

@router.post("/connections/{provider_key}/authorize")
def oauth_start(provider_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _provider(provider_key)
    if p.kind != "oauth":
        raise HTTPException(400, "Dieser Anbieter nutzt keine Anmeldung per Weiterleitung.")
    if not server_settings.app_ready(db, p):
        raise HTTPException(409, f"{p.name} ist noch nicht eingerichtet. Der Administrator muss unter Administration → Anbieter die Zugangsdaten der App eintragen.")
    app = server_settings.get_app(db, p.key)
    verifier, challenge = pkce_pair()
    spec = p.oauth_spec(app)
    state = sign_state({"u": user.id, "p": p.key, "v": verifier if spec.pkce else None}, minutes=20)
    return {"url": authorize_url(p, app, sync.redirect_uri(p.key), state, challenge if spec.pkce else None)}


def _back(provider_key: str, error: str | None = None) -> RedirectResponse:
    base = "/sources"
    if error:
        return RedirectResponse(f"{base}?provider={provider_key}&error={quote(error[:300])}", status_code=303)
    return RedirectResponse(f"{base}?provider={provider_key}&connected=1", status_code=303)


@router.get("/oauth/{provider_key}/callback", include_in_schema=False)
def oauth_callback(provider_key: str, code: str | None = None, state: str | None = None, error: str | None = None,
                   error_description: str | None = None, db: Session = Depends(get_db)):
    """Rücksprung vom Anbieter. Das Anmelde-Cookie kommt hier wegen SameSite nicht mit; der signierte Zustand nennt den Nutzer."""
    p = providers.get(provider_key)
    if p is None or p.kind != "oauth":
        return _back(provider_key, "Unbekannter Anbieter")
    if error:
        return _back(provider_key, f"{p.name}: {error_description or error}")
    data = read_state(state or "")
    if not data or data.get("p") != provider_key or not code:
        return _back(provider_key, "Die Anmeldung ist abgelaufen oder ungültig. Bitte versuche es erneut.")
    user = db.get(User, int(data["u"]))
    if user is None or user.active is False:
        return _back(provider_key, "Konto nicht gefunden")
    app = server_settings.get_app(db, p.key)
    conn = _upsert(db, user, p.key)
    ctx = sync.make_context(db, conn, user, p)
    try:
        payload = {"grant_type": "authorization_code", "code": code, "redirect_uri": sync.redirect_uri(p.key)}
        if data.get("v"):
            payload["code_verifier"] = data["v"]
        raw = token_request(ctx.http, p.oauth_spec(app), app, payload, p)
        token = p.parse_token(raw)
        if not token.get("access_token"):
            raise SyncError(f"{p.name} hat kein Zugriffstoken geliefert.")
        ctx.auth = token
        account = p.after_token(ctx, token)
        ctx.auth = token
    except SyncError as e:
        db.rollback()
        return _back(provider_key, str(e))
    except Exception as e:  # unerwartete Antwort
        db.rollback()
        return _back(provider_key, f"Verbindung fehlgeschlagen: {type(e).__name__}")
    conn = db.get(Connection, conn.id)
    conn.auth = crypto.encrypt_json(ctx.auth)
    conn.account = (account or "")[:160] or conn.account
    conn.status, conn.enabled, conn.last_error, conn.next_sync_at = "ok", True, None, utcnow()
    conn.cursor = {}
    db.commit()
    audit.record(db, user.email, "connect", p.name)
    sync.submit(conn.id, "manual")
    return _back(provider_key)


# ---------- Schlüssel, Login, Webhook ----------

class ConnectIn(BaseModel):
    values: dict = Field(default_factory=dict)


@router.post("/connections/{provider_key}/connect")
def connect(provider_key: str, data: ConnectIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _provider(provider_key)
    if p.kind == "oauth":
        raise HTTPException(400, "Bitte über „Verbinden“ beim Anbieter anmelden.")
    conn = _upsert(db, user, p.key)
    if p.kind in ("push", "file"):
        conn.status, conn.enabled = "ok", True
        db.commit()
        return conn_out(db, conn)
    values = {k: (str(v) if v is not None else "") for k, v in (data.values or {}).items()}
    # leere Geheimnisfelder = bisherigen Wert behalten (beim Bearbeiten)
    old = crypto.decrypt_json(conn.auth)
    for f in p.fields:
        if f.secret and not values.get(f.key) and f.key in old:
            values[f.key] = old[f.key]
    missing = [f.label for f in p.fields if f.required and not values.get(f.key) and not (f.secret and old)]
    if missing and p.kind != "login":
        raise HTTPException(422, "Bitte ausfüllen: " + ", ".join(missing))
    ctx = sync.make_context(db, conn, user, p)
    try:
        account = p.connect(ctx, values)
    except SyncError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    conn = db.get(Connection, conn.id)
    conn.auth = crypto.encrypt_json(ctx.auth)
    conn.config = ctx.config
    conn.account = (str(account) if account else "")[:160] or None
    conn.status, conn.enabled, conn.last_error, conn.next_sync_at = "ok", True, None, utcnow()
    db.commit()
    audit.record(db, user.email, "connect", p.name)
    sync.submit(conn.id, "manual")
    return conn_out(db, conn)


# ---------- Verwaltung ----------

@router.get("/connections")
def list_connections(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [conn_out(db, c) for c in db.scalars(select(Connection).where(Connection.user_id == user.id).order_by(Connection.id))]


class ConnUpdateIn(BaseModel):
    enabled: bool | None = None
    mapping: str | None = Field(default=None, max_length=5000)
    backfill_days: int | None = Field(default=None, ge=1, le=3650)


@router.put("/connections/{conn_id}")
def update_connection(conn_id: int, data: ConnUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get_conn(db, user, conn_id)
    cfg = dict(c.config or {})
    if data.enabled is not None:
        c.enabled = data.enabled
        if data.enabled:
            c.next_sync_at = utcnow()
    if data.mapping is not None and c.provider == "homeassistant":
        cfg["mapping"] = parse_mapping(data.mapping)
    if data.backfill_days is not None:
        cfg["backfill_days"] = data.backfill_days
    c.config = cfg
    db.commit()
    return conn_out(db, c)


@router.post("/connections/{conn_id}/sync", status_code=202)
def sync_now(conn_id: int, full: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get_conn(db, user, conn_id)
    p = providers.get(c.provider)
    if p is None or p.kind in ("push", "file"):
        raise HTTPException(400, "Diese Quelle wird nicht abgefragt, die Daten kommen von selbst.")
    if c.status == "auth":
        raise HTTPException(409, "Der Zugang ist abgelaufen. Bitte verbinde dich erneut.")
    if full:  # alles erneut holen (Zeitraum aus den Einstellungen)
        cur = dict(c.cursor or {})
        cur.pop("last_success", None)
        cur.pop("garmin_next", None)
        c.cursor = cur
        db.commit()
    sync.submit(c.id, "manual")
    return {"ok": True}


@router.get("/connections/{conn_id}/runs")
def runs(conn_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get_conn(db, user, conn_id)
    rows = db.scalars(select(SyncRun).where(SyncRun.connection_id == c.id).order_by(SyncRun.id.desc()).limit(20))
    return [{"started_at": r.started_at.isoformat() + "Z", "finished_at": r.finished_at.isoformat() + "Z" if r.finished_at else None,
             "ok": r.ok, "message": r.message, "counts": r.counts, "trigger": r.trigger} for r in rows]


@router.delete("/connections/{conn_id}", status_code=204)
def disconnect(conn_id: int, delete_data: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get_conn(db, user, conn_id)
    p = providers.get(c.provider)
    if p is not None and p.kind == "oauth":
        try:
            p.disconnect(sync.make_context(db, c, user, p))
        except Exception:  # Widerruf beim Anbieter ist optional
            pass
    if delete_data:
        db.execute(delete(Sample).where(Sample.user_id == user.id, Sample.source == c.provider))
        db.execute(delete(SleepSession).where(SleepSession.user_id == user.id, SleepSession.source == c.provider))
        acts = db.scalars(select(Activity).where(Activity.user_id == user.id, Activity.source == c.provider)).all()
        ids = [a.id for a in acts]
        for a in acts:
            db.delete(a)
        if ids:
            for a in db.scalars(select(Activity).where(Activity.duplicate_of.in_(ids))):
                a.duplicate_of = None
    name = p.name if p else c.provider
    db.delete(c)
    db.commit()
    audit.record(db, user.email, "disconnect", name + (" (mit Daten)" if delete_data else ""))

