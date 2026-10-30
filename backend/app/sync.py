"""Sync-Engine: holt regelmäßig neue Daten von allen verbundenen Anbietern."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import delete, select, update

from . import audit, crypto, providers, server_settings, tracks
from .config import settings
from .database import SessionLocal
from .models import Connection, SyncRun, User
from .providers.base import AuthError, RateLimited, SyncContext, SyncError
from .timeutil import utcnow

log = logging.getLogger("bodybase.sync")

_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="sync")
_running: set[int] = set()
_lock = threading.Lock()
KEEP_RUNS = 30


def redirect_uri(provider_key: str) -> str:
    return f"{settings.public_url.rstrip('/')}/api/oauth/{provider_key}/callback"


def make_context(db, conn: Connection | None, user: User, provider, client=None) -> SyncContext:
    app = server_settings.get_app(db, provider.key)
    return SyncContext(db, conn, user, provider, app, redirect_uri(provider.key), client=client, backfill_days=settings.backfill_days)


def interval_for(provider) -> int:
    return provider.interval_minutes or settings.sync_interval_minutes


def run_connection(conn_id: int, trigger: str = "auto", client=None) -> dict:
    """Gleicht eine Verbindung ab. Läuft synchron; für Hintergrundaufrufe siehe submit()."""
    with _lock:
        if conn_id in _running:
            return {"ok": False, "message": "Läuft bereits."}
        _running.add(conn_id)
    try:
        with SessionLocal() as db:
            conn = db.get(Connection, conn_id)
            if conn is None:
                return {"ok": False, "message": "Verbindung nicht gefunden."}
            provider = providers.get(conn.provider)
            user = db.get(User, conn.user_id)
            if (conn.config or {}).get("demo"):
                return {"ok": True, "message": "Beispieldaten werden nicht abgeglichen."}
            if provider is None or user is None or provider.kind in ("push", "file"):
                return {"ok": False, "message": "Für diese Quelle gibt es keinen Abgleich."}
            run = SyncRun(connection_id=conn.id, trigger=trigger)
            db.add(run)
            conn.syncing = True
            conn.last_sync_at = utcnow()
            db.commit()
            ctx = make_context(db, conn, user, provider, client)
            started = utcnow()
            ok, message = True, None
            try:
                provider.sync(ctx)
                ctx.writer.flush()
                tracks.backfill(ctx)
                counts = ctx.writer.flush()
                conn.status = "ok"
                conn.last_error = None
                conn.last_success_at = started
                ctx.cursor["last_success"] = started.isoformat()
                message = " ".join(ctx.notes) or None
            except AuthError as e:
                db.rollback()
                ok, message = False, str(e)
                conn.status = "auth"
                counts = ctx.writer.counts
            except RateLimited as e:
                db.rollback()
                ctx.writer.flush()
                ok, message = False, str(e)
                conn.status = "ok"
                counts = ctx.writer.counts
            except SyncError as e:
                db.rollback()
                ok, message = False, str(e)
                conn.status = "error"
                counts = ctx.writer.counts
            except Exception as e:  # unerwartet: protokollieren, aber den Dienst nicht anhalten
                db.rollback()
                log.exception("Abgleich %s (Verbindung %s) fehlgeschlagen", provider.key, conn.id)
                ok, message = False, f"Unerwarteter Fehler: {type(e).__name__}: {e}"[:500]
                conn.status = "error"
                counts = ctx.writer.counts
            conn = db.get(Connection, conn_id)
            run = db.get(SyncRun, run.id)
            if not ok:
                conn.last_error = message
            conn.cursor = ctx.cursor
            if ctx._dirty_auth:
                conn.auth = crypto.encrypt_json(ctx.auth)
            conn.last_counts = counts
            conn.syncing = False
            minutes = interval_for(provider)
            if not ok and conn.status == "error":
                minutes = max(minutes, 120)  # bei Fehlern seltener versuchen
            conn.next_sync_at = utcnow() + timedelta(minutes=minutes)
            run.finished_at, run.ok, run.message, run.counts = utcnow(), ok, message, counts
            db.commit()
            _trim_runs(db, conn.id)
            if not ok and conn.status == "auth" and trigger != "manual":
                audit.record(db, user.email, "sync.auth", f"{provider.name}: Zugang abgelaufen")
            return {"ok": ok, "message": message, "counts": counts, "status": conn.status}
    finally:
        with _lock:
            _running.discard(conn_id)


def _trim_runs(db, conn_id: int) -> None:
    ids = db.scalars(select(SyncRun.id).where(SyncRun.connection_id == conn_id).order_by(SyncRun.id.desc()).offset(KEEP_RUNS)).all()
    if ids:
        db.execute(delete(SyncRun).where(SyncRun.id.in_(ids)))
        db.commit()


def is_running(conn_id: int) -> bool:
    with _lock:
        return conn_id in _running


def submit(conn_id: int, trigger: str = "manual") -> None:
    _pool.submit(run_connection, conn_id, trigger)


def _tick() -> None:
    with SessionLocal() as db:
        now = utcnow()
        rows = db.scalars(select(Connection).where(
            Connection.enabled.is_(True), Connection.status.in_(("ok", "error", "pending")),
            (Connection.next_sync_at.is_(None)) | (Connection.next_sync_at <= now),
        )).all()
        due = [c.id for c in rows if (p := providers.get(c.provider)) and p.kind not in ("push", "file")
               and not (c.config or {}).get("demo")]
    for cid in due:
        if not is_running(cid):
            _pool.submit(run_connection, cid, "auto")


def _loop() -> None:
    time.sleep(20)
    # nach einem Neustart hängengebliebene Markierungen lösen
    with SessionLocal() as db:
        db.execute(update(Connection).values(syncing=False))
        db.commit()
    while True:
        try:
            _tick()
        except Exception:
            log.exception("Planung der Abgleiche fehlgeschlagen")
        time.sleep(60)


def start_background() -> None:
    if settings.background_jobs:
        threading.Thread(target=_loop, daemon=True, name="sync-scheduler").start()
