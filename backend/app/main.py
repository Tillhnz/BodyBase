import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from . import __version__, audit, server_settings, sync
from .config import settings
from .database import Base, SessionLocal, engine, ensure_columns
from .routers import account, admin, apikeys, auth, connections, data, habits, imports, mapconfig, segments, strength, version

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bodybase")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.secret_key in ("dev-secret-change-me", "bitte-aendern") or len(settings.secret_key) < 16:
        log.warning("SECRET_KEY ist unsicher. Setze einen langen Zufallswert (openssl rand -hex 32).")
    Base.metadata.create_all(engine)
    ensure_columns()
    with SessionLocal() as db:
        server_settings.apply_overrides(db)
        from . import sports
        from .strength import assign_unknown_muscles, seed_catalog
        seed_catalog(db)
        assign_unknown_muscles(db)
        from .strength import assign_media
        assign_media(db)
        sports.migrate(db)
    audit.event("System", "server.start", f"BodyBase {__version__} gestartet")
    sync.start_background()
    yield


API_DESCRIPTION = """Schnittstelle von BodyBase: alle Fitness- und Gesundheitsdaten an einem Ort.

**Anmelden:** Einen persönlichen API-Schlüssel unter *Einstellungen → API* erzeugen und mitschicken:
`Authorization: Bearer bbk_…` oder `X-API-Key: bbk_…`. Schlüssel mit Leserecht dürfen nur GET-Anfragen.
Zeiten sind UTC im ISO-8601-Format, Tage im Format JJJJ-MM-TT, Gewichte in kg, Strecken in Metern.
"""

TAGS = [
    {"name": "data", "description": "Messwerte, Tageswerte, Aktivitäten, Schlaf, Vergleiche"},
    {"name": "strength", "description": "Krafttraining: Übungen, Routinen, Trainings, Auswertungen"},
    {"name": "habits", "description": "Gewohnheiten und Hinweise des Coaches"},
    {"name": "account", "description": "Profil, Einstellungen, eigene Einträge"},
    {"name": "connections", "description": "Verbundene Quellen und Abgleich"},
    {"name": "imports", "description": "Dateien hochladen und Daten empfangen (Webhooks)"},
]

app = FastAPI(title="BodyBase", version=__version__, lifespan=lifespan, description=API_DESCRIPTION, openapi_tags=TAGS,
              docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def guard(request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        log.exception("Unbehandelter Fehler bei %s %s", request.method, request.url.path)
        response = JSONResponse({"detail": "Interner Serverfehler"}, status_code=500)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


for r in (auth.router, account.router, data.router, connections.router, imports.router, admin.router, mapconfig.router, strength.router, habits.router, apikeys.router, segments.router, version.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}
