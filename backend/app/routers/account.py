import csv
import io
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import audit, metrics as M
from ..config import settings
from ..database import get_db
from ..models import Activity, Sample, SleepSession, User
from ..security import current_user, ingest_token, new_ingest_token, verify_password
from ..store import DEFAULT_PRIORITY, Writer
from ..timeutil import parse_iso, utcnow
from .auth import admins_left, user_out

router = APIRouter(prefix="/api", tags=["account"])

DEFAULT_GOALS = {"steps": 8000, "sleep_duration": 450, "active_minutes": 30, "weight": None}


class ProfileIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    height_cm: float | None = Field(default=None, ge=80, le=250)
    birth_year: int | None = Field(default=None, ge=1900, le=2030)
    sex: str | None = Field(default=None, pattern="^(f|m|d)?$")


class PrefsIn(BaseModel):
    goals: dict | None = None
    priority: dict | None = None
    home: list[str] | None = None
    tour_done: bool | None = None


@router.put("/me/profile")
def update_profile(data: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.name = (data.name or "").strip() or None
    user.height_cm, user.birth_year, user.sex = data.height_cm, data.birth_year, data.sex or None
    db.commit()
    return user_out(user)


@router.get("/me/goals")
def goals(user: User = Depends(current_user)):
    return {**DEFAULT_GOALS, **((user.prefs or {}).get("goals") or {})}


@router.put("/me/prefs")
def update_prefs(data: PrefsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prefs = dict(user.prefs or {})
    if data.goals is not None:
        goals = {}
        for k, v in data.goals.items():
            if k in M.METRICS and (v is None or isinstance(v, (int, float))):
                goals[k] = v
        prefs["goals"] = goals
    if data.priority is not None:
        pr = {}
        for k, order in data.priority.items():
            if (k in M.METRICS or k == "_activities") and isinstance(order, list):
                pr[k] = [str(s)[:40] for s in order][:40]
        prefs["priority"] = pr
    if data.home is not None:
        prefs["home"] = [k for k in data.home if k in M.METRICS][:12]
    if data.tour_done is not None:
        user.tour_done = data.tour_done
    user.prefs = prefs
    db.commit()
    return user_out(user)


# ---------- Webhook-Schlüssel ----------

def ingest_info(user: User) -> dict:
    token = ingest_token(user)
    base = settings.public_url.rstrip("/")
    return {
        "token": token,
        "urls": {
            "health_auto_export": f"{base}/api/ingest/health-auto-export",
            "json": f"{base}/api/ingest/json",
        },
        "header": "Authorization: Bearer <Schlüssel>",
    }


@router.get("/me/ingest")
def get_ingest(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.ingest_token:
        new_ingest_token(user)
        db.commit()
    return ingest_info(user)


@router.post("/me/ingest/rotate")
def rotate_ingest(user: User = Depends(current_user), db: Session = Depends(get_db)):
    new_ingest_token(user)
    db.commit()
    audit.record(db, user.email, "ingest.rotate", "Webhook-Schlüssel erneuert")
    return ingest_info(user)


# ---------- Eigene Eingaben ----------

class ManualIn(BaseModel):
    metric: str
    value: float
    time: str | None = None  # ISO, Ortszeit erlaubt; leer = jetzt


@router.post("/entries", status_code=201)
def add_entry(data: ManualIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.metric not in M.METRICS:
        raise HTTPException(422, "Unbekannte Messgröße")
    if not M.plausible(data.metric, data.value):
        raise HTTPException(422, "Der Wert liegt außerhalb des möglichen Bereichs.")
    ts = parse_iso(data.time) if data.time else utcnow()
    if ts is None:
        raise HTTPException(422, "Zeitpunkt nicht lesbar")
    w = Writer(db, user.id, "manual")
    w.sample(data.metric, ts, data.value)
    w.flush()
    return {"ok": True}


@router.get("/entries")
def list_entries(metric: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Sample).where(Sample.user_id == user.id, Sample.source == "manual").order_by(Sample.ts.desc()).limit(200)
    if metric:
        q = q.where(Sample.metric == metric)
    return [{"id": s.id, "metric": s.metric, "value": s.value, "ts": s.ts.isoformat() + "Z"} for s in db.scalars(q)]


@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(Sample, entry_id)
    if s is None or s.user_id != user.id or s.source != "manual":
        raise HTTPException(404, "Nicht gefunden")
    db.delete(s)
    db.commit()


# ---------- Daten löschen und exportieren ----------

class SourceDeleteIn(BaseModel):
    source: str = Field(max_length=40)


@router.post("/me/data/delete-source")
def delete_source_data(data: SourceDeleteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Alle Daten einer Quelle löschen (z. B. nach einem fehlerhaften Import)."""
    n = db.execute(delete(Sample).where(Sample.user_id == user.id, Sample.source == data.source)).rowcount or 0
    acts = db.scalars(select(Activity).where(Activity.user_id == user.id, Activity.source == data.source)).all()
    ids = [a.id for a in acts]
    for a in acts:
        db.delete(a)
    if ids:
        for a in db.scalars(select(Activity).where(Activity.duplicate_of.in_(ids))).all():
            a.duplicate_of = None
    m = db.execute(delete(SleepSession).where(SleepSession.user_id == user.id, SleepSession.source == data.source)).rowcount or 0
    db.commit()
    audit.record(db, user.email, "data.delete", f"Quelle {data.source}: {n} Werte, {len(ids)} Aktivitäten, {m} Nächte")
    return {"samples": n, "activities": len(ids), "sleep": m}


@router.get("/me/export")
def export(fmt: str = "json", user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Alle eigenen Daten herunterladen (JSON oder CSV mit Messwerten)."""
    stamp = date.today().isoformat()
    if fmt == "csv":
        def rows():
            buf = io.StringIO()
            wr = csv.writer(buf)
            wr.writerow(["time_utc", "day", "metric", "value", "unit", "source"])
            yield buf.getvalue()
            q = select(Sample).where(Sample.user_id == user.id).order_by(Sample.ts).execution_options(yield_per=5000)
            for s in db.scalars(q):
                buf.seek(0)
                buf.truncate()
                m = M.METRICS.get(s.metric)
                wr.writerow([s.ts.isoformat(), s.day.isoformat(), s.metric, s.value, m.unit if m else "", s.source])
                yield buf.getvalue()
        return StreamingResponse(rows(), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="bodybase-{stamp}.csv"'})

    def gen():
        yield '{"profile": ' + json.dumps(user_out(user)) + ', "samples": ['
        first = True
        for s in db.scalars(select(Sample).where(Sample.user_id == user.id).order_by(Sample.ts).execution_options(yield_per=5000)):
            yield ("" if first else ",") + json.dumps({"metric": s.metric, "ts": s.ts.isoformat() + "Z", "value": s.value, "source": s.source})
            first = False
        yield '], "activities": ['
        first = True
        for a in db.scalars(select(Activity).where(Activity.user_id == user.id).order_by(Activity.start)):
            yield ("" if first else ",") + json.dumps({
                "source": a.source, "source_id": a.source_id, "sport": a.sport, "name": a.name, "start": a.start.isoformat() + "Z",
                "duration_s": a.duration_s, "distance_m": a.distance_m, "elevation_m": a.elevation_m, "calories": a.calories,
                "avg_hr": a.avg_hr, "max_hr": a.max_hr, "avg_power": a.avg_power, "load": a.load, "duplicate_of": a.duplicate_of})
            first = False
        yield '], "sleep": ['
        first = True
        for s in db.scalars(select(SleepSession).where(SleepSession.user_id == user.id).order_by(SleepSession.start)):
            yield ("" if first else ",") + json.dumps({
                "source": s.source, "start": s.start.isoformat() + "Z", "end": s.end.isoformat() + "Z", "asleep_min": s.asleep_min,
                "deep_min": s.deep_min, "rem_min": s.rem_min, "light_min": s.light_min, "awake_min": s.awake_min, "score": s.score})
            first = False
        yield "]}"
    return StreamingResponse(gen(), media_type="application/json",
                             headers={"Content-Disposition": f'attachment; filename="bodybase-{stamp}.json"'})


class DeleteAccountIn(BaseModel):
    password: str = Field(max_length=200)


@router.post("/me/delete", status_code=204)
def delete_account(data: DeleteAccountIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(403, "Passwort falsch")
    others = (db.scalar(select(User.id).where(User.id != user.id).limit(1))) is not None
    if user.role == "admin" and admins_left(db) <= 1 and others:
        raise HTTPException(409, "Du bist der letzte Administrator. Ernenne zuerst jemand anderen.")
    email = user.email
    for model in (Sample, SleepSession, Activity):
        db.execute(delete(model).where(model.user_id == user.id))
    db.delete(user)
    db.commit()
    audit.record(db, email, "account.delete", "Konto gelöscht")


@router.post("/me/demo", status_code=201)
def load_demo(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Beispieldaten laden, um BodyBase ohne eigene Geräte auszuprobieren."""
    from ..demo import generate
    if db.scalar(select(Sample.id).where(Sample.user_id == user.id).limit(1)) is not None:
        raise HTTPException(409, "Es sind schon Daten vorhanden. Beispieldaten gibt es nur für ein leeres Konto.")
    return generate(db, user)


@router.delete("/me/demo", status_code=204)
def remove_demo(user: User = Depends(current_user), db: Session = Depends(get_db)):
    from ..models import Connection
    for c in db.scalars(select(Connection).where(Connection.user_id == user.id)).all():
        if (c.config or {}).get("demo"):
            for model in (Sample, SleepSession, Activity):
                db.execute(delete(model).where(model.user_id == user.id, model.source == c.provider))
            db.delete(c)
    db.commit()


@router.get("/meta")
def meta(user: User = Depends(current_user)):
    """Metriken, Kategorien und Sportarten für die Oberfläche."""
    from ..sports import SPORTS
    return {"metrics": M.catalog(), "categories": M.CATEGORIES, "sports": SPORTS, "default_priority": DEFAULT_PRIORITY,
            "default_goals": DEFAULT_GOALS, "timezone": settings.timezone}

