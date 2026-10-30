import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crypto
from .config import settings
from .database import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)
SESSION_COOKIE = "bb_session"
APP_HEADER = "x-bb-request"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=settings.token_expire_days)
    claims = {"sub": str(user.id), "exp": exp, "tv": user.token_version or 0}
    return jwt.encode(claims, settings.secret_key, algorithm="HS256")


def sign_state(data: dict, minutes: int = 15) -> str:
    """Kurzlebiger, signierter Zustand (z. B. für den OAuth-Rücksprung)."""
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return jwt.encode({**data, "exp": exp, "typ": "state"}, settings.secret_key, algorithm="HS256")


def read_state(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("typ") == "state" else None


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")
    token = creds.credentials if creds is not None else request.cookies.get(SESSION_COOKIE)
    header_key = request.headers.get("x-api-key")
    if header_key and not token:
        token = header_key
    if token and token.startswith(API_KEY_PREFIX):
        return _user_from_api_key(request, db, token)
    if not token:
        raise unauthorized
    if creds is None and request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(APP_HEADER) != "1":
        # Schutz gegen untergeschobene Formulare fremder Seiten (CSRF): die App schickt diesen Kopf immer mit
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Anfrage ohne Kennung der App abgelehnt")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        if payload.get("typ"):
            raise unauthorized
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    if user is None or payload.get("tv", 0) != (user.token_version or 0) or user.active is False:
        raise unauthorized
    request.state.actor = user.email
    return user


# ---------- Persönliche API-Schlüssel ----------

API_KEY_PREFIX = "bbk_"
# Mit einem Schlüssel nicht erreichbar: Konto, Anmeldung, Schlüsselverwaltung, Administration
KEY_FORBIDDEN = ("/api/admin", "/api/auth/", "/api/me/api-keys", "/api/me/delete", "/api/me/ingest")


def hash_api_key(key: str) -> str:
    return hashlib.sha256(("apikey:" + key).encode()).hexdigest()


def new_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def _user_from_api_key(request: Request, db: Session, key: str) -> User:
    from .models import ApiKey
    from .timeutil import utcnow
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Ungültiger API-Schlüssel")
    if len(key) > 120:
        raise unauthorized
    row = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(key)))
    now = utcnow()
    if row is None or (row.expires_at and row.expires_at < now):
        raise unauthorized
    user = db.get(User, row.user_id)
    if user is None or user.active is False:
        raise unauthorized
    path = request.url.path
    if any(path.startswith(p) for p in KEY_FORBIDDEN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Mit einem API-Schlüssel nicht erlaubt. Bitte in BodyBase anmelden.")
    if row.scope != "write" and request.method not in ("GET", "HEAD", "OPTIONS"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Dieser API-Schlüssel darf nur lesen.")
    if row.last_used_at is None or (now - row.last_used_at).total_seconds() > 300:
        row.last_used_at = now
        db.commit()
    request.state.actor = f"{user.email} (API: {row.name})"
    request.state.api_key = row.id
    return user


def require_session(request: Request, user: User = Depends(current_user)) -> User:
    """Nur mit Anmeldung in der App, nicht mit API-Schlüssel."""
    if getattr(request.state, "api_key", None):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Mit einem API-Schlüssel nicht erlaubt.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur für den Administrator")
    return user


# ---------- Schlüssel für Webhooks (Apple Health, eigene Skripte) ----------

def _hash_ingest(token: str) -> str:
    return hashlib.sha256(("ingest:" + token).encode()).hexdigest()


def new_ingest_token(user: User) -> str:
    token = "bb_" + secrets.token_urlsafe(30)
    user.ingest_token = crypto.encrypt(token)
    user.ingest_hash = _hash_ingest(token)
    return token


def ingest_token(user: User) -> str | None:
    return crypto.decrypt(user.ingest_token)


def user_from_ingest_token(db: Session, token: str | None) -> User | None:
    if not token or len(token) > 200:
        return None
    user = db.scalar(select(User).where(User.ingest_hash == _hash_ingest(token.strip())))
    if user is None or user.active is False:
        return None
    return user
