import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, ratelimit
from ..config import settings
from ..database import get_db
from ..models import Invite, User
from ..security import SESSION_COOKIE, create_token, current_user, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


class Credentials(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Keine gültige E-Mail-Adresse")
        return v


class RegisterIn(Credentials):
    password: str = Field(min_length=8, max_length=200)
    invite: str | None = Field(default=None, max_length=32)
    name: str | None = Field(default=None, max_length=80)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


def user_out(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "name": u.name, "role": u.role, "is_admin": u.role == "admin",
        "height_cm": u.height_cm, "birth_year": u.birth_year, "sex": u.sex, "prefs": u.prefs or {},
        "tour_done": bool(u.tour_done),
    }


def token_out(user: User, response: Response, request: Request) -> dict:
    token = create_token(user)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
    samesite = settings.cookie_samesite.lower() if settings.cookie_samesite.lower() in ("strict", "lax", "none") else "strict"
    if samesite == "none" and not secure:
        samesite = "lax"
    response.set_cookie(SESSION_COOKIE, token, max_age=settings.token_expire_days * 86400, httponly=True, samesite=samesite,
                        secure=secure or samesite == "none", path="/api")
    return {"access_token": token, "token_type": "bearer"}


_DUMMY_HASH = hash_password("dummy-password-for-timing")


@router.get("/frame-policy", include_in_schema=False)
def frame_policy():
    fa = settings.frame_ancestors.strip()
    headers = {"X-BB-Frame-Ancestors": "'self' " + fa} if fa else {}
    return Response(status_code=204, headers=headers)


@router.get("/config")
def public_config(db: Session = Depends(get_db)):
    first = db.scalar(select(User.id).limit(1)) is None
    return {"allow_registration": settings.allow_registration or first, "first_user": first}


@router.post("/auth/register", status_code=201)
def register(data: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ratelimit.check_register(ratelimit.client_ip(request))
    first_user = db.scalar(select(User.id).limit(1)) is None
    invite = None
    if not first_user and not settings.allow_registration:
        code = (data.invite or "").strip().upper()
        invite = db.scalar(select(Invite).where(Invite.code == code, Invite.used_at.is_(None))) if code else None
        if invite is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Registrierung nur mit gültigem Einladungscode")
    if db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "E-Mail bereits vergeben")
    user = User(email=data.email, password_hash=hash_password(data.password), token_version=0, active=True,
                role="admin" if first_user else "user", name=(data.name or "").strip() or None, prefs={})
    db.add(user)
    if invite is not None:
        invite.used_by_email, invite.used_at = data.email, datetime.utcnow()
    db.commit()
    audit.record(db, data.email, "user.register", "erstes Konto (Administrator)" if first_user else (f"Einladung {invite.code}" if invite else ""))
    return token_out(user, response, request)


@router.post("/auth/login")
def login(data: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = ratelimit.client_ip(request)
    ratelimit.check_login(data.email, ip)
    user = db.scalar(select(User).where(User.email == data.email))
    ok = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        ratelimit.record_failure(data.email, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-Mail oder Passwort falsch")
    if user.active is False:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Dieses Konto ist gesperrt.")
    ratelimit.record_success(data.email)
    return token_out(user, response, request)


@router.post("/auth/logout", status_code=204)
def logout(response: Response):
    attrs = {"path": "/api", "httponly": True}
    if settings.cookie_samesite.lower() == "none":
        attrs.update(secure=True, samesite="none")
    response.delete_cookie(SESSION_COOKIE, **attrs)


@router.put("/auth/password")
def change_password(data: PasswordChangeIn, request: Request, response: Response, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    ip = ratelimit.client_ip(request)
    ratelimit.check_login(user.email, ip)
    if not verify_password(data.current_password, user.password_hash):
        ratelimit.record_failure(user.email, ip)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Passwort falsch")
    user.password_hash = hash_password(data.new_password)
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    audit.record(db, user.email, "password", "Passwort geändert")
    return token_out(user, response, request)


@router.post("/auth/logout-all")
def logout_all(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    return token_out(user, response, request)


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


def admins_left(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.active.isnot(False))) or 0
