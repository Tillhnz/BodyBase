import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from . import __version__, audit, server_settings, sync
from .config import settings
from .database import Base, SessionLocal, engine, ensure_columns
from .routers import account, admin, auth, connections, data, imports, mapconfig, strength, version

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
        from .strength import seed_catalog
        seed_catalog(db)
    audit.event("System", "server.start", f"BodyBase {__version__} gestartet")
    sync.start_background()
    yield


app = FastAPI(title="BodyBase", version=__version__, lifespan=lifespan)
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


for r in (auth.router, account.router, data.router, connections.router, imports.router, admin.router, mapconfig.router, strength.router, version.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}
