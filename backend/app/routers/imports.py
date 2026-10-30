"""Datei-Importe (FIT/GPX/TCX, CSV, Apple-Health-Export) und Webhooks (Health Auto Export, eigenes JSON)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..importers import apple, parsers, tabular
from ..models import Connection, ImportJob, SyncRun, User
from ..security import current_user, user_from_ingest_token
from ..store import ActivityIn, Writer
from ..timeutil import utcnow

log = logging.getLogger("bodybase.imports")
router = APIRouter(prefix="/api", tags=["imports"])

MAX_FILE = 200 * 1024 * 1024
MAX_FILES = 500


def _touch(db: Session, user_id: int, provider: str, counts: dict | None, trigger: str, message: str | None = None) -> None:
    """Quelle als „verbunden“ führen und den Eingang protokollieren."""
    c = db.scalar(select(Connection).where(Connection.user_id == user_id, Connection.provider == provider))
    if c is None:
        c = Connection(user_id=user_id, provider=provider, enabled=True, status="ok", config={}, cursor={})
        db.add(c)
    c.status, c.last_sync_at, c.last_success_at, c.last_counts, c.last_error = "ok", utcnow(), utcnow(), counts, None
    db.flush()
    db.add(SyncRun(connection_id=c.id, finished_at=utcnow(), ok=True, counts=counts, trigger=trigger, message=message))
    db.commit()


# ---------- Trainingsdateien ----------

@router.post("/imports/files")
async def import_files(files: list[UploadFile] = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"Höchstens {MAX_FILES} Dateien auf einmal.")
    w = Writer(db, user.id, "file")
    results = []
    for f in files:
        data = await f.read(MAX_FILE + 1)
        name = f.filename or "datei"
        if len(data) > MAX_FILE:
            results.append({"file": name, "ok": False, "error": "Datei zu groß"})
            continue
        try:
            p = parsers.parse_activity_file(name, data)
        except parsers.ParseError as e:
            results.append({"file": name, "ok": False, "error": str(e)})
            continue
        except Exception as e:  # kaputte Dateien sollen den Rest nicht aufhalten
            results.append({"file": name, "ok": False, "error": f"Nicht lesbar ({type(e).__name__})"})
            continue
        d = p.details or {}
        w.activity(ActivityIn(
            source_id=hashlib.sha1(data).hexdigest()[:24], start=p.start, sport_raw=p.sport, name=p.name,
            duration_s=d.get("elapsed_s") or p.moving_time_s, moving_s=p.moving_time_s, distance_m=p.distance_km * 1000,
            elevation_m=p.elevation_m, avg_hr=d.get("avg_hr"), max_hr=d.get("max_hr"), avg_power=d.get("avg_power"),
            polyline=p.polyline, details={"profile": d.get("profile"), "max_speed": d.get("max_speed")} if d else None,
        ))
        results.append({"file": name, "ok": True, "name": p.name, "start": p.start.isoformat() + "Z", "km": round(p.distance_km, 2)})
    counts = w.flush()
    _touch(db, user.id, "file", counts, "import", f"{sum(1 for r in results if r['ok'])} Dateien")
    return {"results": results, "counts": counts}


# ---------- CSV ----------

@router.post("/imports/csv")
async def import_csv(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = await file.read(50 * 1024 * 1024 + 1)
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "Die CSV-Datei ist größer als 50 MB.")
    w = Writer(db, user.id, "csv")
    try:
        info = tabular.import_csv(w, data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    counts = w.flush()
    _touch(db, user.id, "csv", counts, "import", file.filename)
    return {"counts": counts, **info}


# ---------- Apple-Health-Export (groß, läuft im Hintergrund) ----------

def _upload_dir() -> str:
    path = os.path.join(settings.data_dir, "uploads")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = os.path.join(os.getcwd(), "uploads")
        os.makedirs(path, exist_ok=True)
    return path


@router.post("/imports/apple-health", status_code=202)
async def import_apple(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Der Körper der Anfrage ist die Datei selbst (export.zip oder export.xml), damit auch mehrere GB durchgehen."""
    running = db.scalar(select(ImportJob).where(ImportJob.user_id == user.id, ImportJob.status.in_(("queued", "running"))))
    if running:
        raise HTTPException(409, "Es läuft bereits ein Import. Bitte warte, bis er fertig ist.")
    limit = settings.max_upload_mb * 1024 * 1024
    path = os.path.join(_upload_dir(), f"{uuid.uuid4().hex}.upload")
    size = 0
    try:
        with open(path, "wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Die Datei ist größer als {settings.max_upload_mb} MB.")
                out.write(chunk)
    except HTTPException:
        os.remove(path)
        raise
    if size < 100:
        os.remove(path)
        raise HTTPException(422, "Die Datei ist leer.")
    name = request.headers.get("x-filename", "export.zip")[:255]
    job = ImportJob(user_id=user.id, kind="apple_health", filename=name, status="queued", progress=0)
    db.add(job)
    db.commit()
    threading.Thread(target=_run_apple, args=(job.id, path), daemon=True, name=f"import-{job.id}").start()
    return job_out(job)


def _run_apple(job_id: int, path: str) -> None:
    with SessionLocal() as db:
        job = db.get(ImportJob, job_id)
        job.status = "running"
        db.commit()
        last = [0.0]

        def progress(p: float):
            if p - last[0] >= 0.02:
                last[0] = p
                with SessionLocal() as db2:
                    j = db2.get(ImportJob, job_id)
                    j.progress = round(p, 3)
                    db2.commit()
        try:
            w = Writer(db, job.user_id, "apple_health")
            info = apple.import_export_xml(w, path, progress)
            counts = {**w.flush(), **info}
            job = db.get(ImportJob, job_id)
            job.status, job.progress, job.counts, job.finished_at = "done", 1.0, counts, utcnow()
            db.commit()
            _touch(db, job.user_id, "apple_health", counts, "import", job.filename)
        except Exception as e:
            log.exception("Apple-Health-Import fehlgeschlagen")
            db.rollback()
            job = db.get(ImportJob, job_id)
            job.status, job.message, job.finished_at = "failed", str(e)[:500], utcnow()
            db.commit()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


def job_out(j: ImportJob) -> dict:
    return {"id": j.id, "kind": j.kind, "filename": j.filename, "status": j.status, "progress": j.progress, "message": j.message,
            "counts": j.counts, "created_at": j.created_at.isoformat() + "Z",
            "finished_at": j.finished_at.isoformat() + "Z" if j.finished_at else None}


@router.get("/imports/jobs")
def jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ImportJob).where(ImportJob.user_id == user.id).order_by(ImportJob.id.desc()).limit(10))
    return [job_out(j) for j in rows]


# ---------- Webhooks ----------

def _ingest_user(request: Request, db: Session) -> User:
    token = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    token = token or request.headers.get("x-api-key") or request.headers.get("api-key") or request.query_params.get("token")
    user = user_from_ingest_token(db, token)
    if user is None and token and token.startswith("bbk_"):
        from ..models import ApiKey
        from ..security import hash_api_key
        key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(token)))
        if key is not None and key.scope == "write":
            user = db.get(User, key.user_id)
    if user is None:
        raise HTTPException(401, "Ungültiger oder fehlender Schlüssel. Du findest ihn in BodyBase unter Quellen.")
    return user


async def _json_body(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > 100 * 1024 * 1024:
        raise HTTPException(413, "Zu groß")
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(422, "Kein gültiges JSON")
    if not isinstance(data, dict):
        raise HTTPException(422, "Erwartet wird ein JSON-Objekt")
    return data


@router.post("/ingest/health-auto-export")
async def ingest_hae(request: Request, db: Session = Depends(get_db)):
    user = _ingest_user(request, db)
    data = await _json_body(request)
    w = Writer(db, user.id, "apple_health")
    apple.ingest_health_auto_export(w, data)
    counts = w.flush()
    _touch(db, user.id, "apple_health", counts, "webhook")
    return {"ok": True, "counts": counts}


ALLOWED_PUSH_SOURCES = {"api", "health_connect"}


@router.post("/ingest/json")
async def ingest_generic(request: Request, db: Session = Depends(get_db)):
    user = _ingest_user(request, db)
    data = await _json_body(request)
    source = data.get("source") if data.get("source") in ALLOWED_PUSH_SOURCES else "api"
    w = Writer(db, user.id, source)
    tabular.ingest_json(w, data)
    counts = w.flush()
    _touch(db, user.id, source, counts, "webhook")
    return {"ok": True, "counts": counts}

