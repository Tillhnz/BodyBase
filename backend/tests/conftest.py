import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="bodybase-test-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["BACKGROUND_JOBS"] = "false"
os.environ["ALLOW_REGISTRATION"] = "true"
os.environ["SECRET_KEY"] = "test-secret-key-0123456789abcdef"
os.environ["DATA_DIR"] = _tmp
os.environ["PUBLIC_URL"] = "https://bodybase.example.de"
os.environ["TIMEZONE"] = "Europe/Berlin"

import itertools  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_n = itertools.count()


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    from app import ratelimit
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture(scope="session")
def app():
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def register(client, email=None, password="geheim-123"):
    email = email or f"user{next(_n)}@example.de"
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, email


@pytest.fixture()
def auth(client):
    headers, _ = register(client)
    return headers


@pytest.fixture()
def db():
    from app.database import SessionLocal
    with SessionLocal() as s:
        yield s


@pytest.fixture()
def user(db):
    from app.models import User
    u = User(email=f"p{next(_n)}@example.de", password_hash="x", role="user", prefs={})
    db.add(u)
    db.commit()
    return u


@pytest.fixture(scope="session", autouse=True)
def _tables():
    from app.database import Base, engine
    from app import models  # noqa: F401
    Base.metadata.create_all(engine)
    yield


def make_ctx(db, user, provider, handler, auth=None, config=None, cursor=None):
    """SyncContext mit nachgebildeten Antworten (httpx.MockTransport)."""
    import httpx

    from app.models import Connection
    from app.providers.base import SyncContext
    from app import crypto
    conn = Connection(user_id=user.id, provider=provider.key, enabled=True, status="ok", config=config or {}, cursor=cursor or {},
                      auth=crypto.encrypt_json(auth or {"access_token": "tok", "refresh_token": "ref", "expires_at": 9999999999}))
    db.add(conn)
    db.commit()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return SyncContext(db, conn, user, provider, {"client_id": "cid", "client_secret": "sec"}, "https://x/cb", client=client)


@pytest.fixture()
def admin(client, db):
    from app.models import User
    from app.security import create_token, hash_password
    u = User(email=f"admin{next(_n)}@example.de", password_hash=hash_password("geheim-123"), role="admin", prefs={}, active=True,
             token_version=0)
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {create_token(u)}"}
