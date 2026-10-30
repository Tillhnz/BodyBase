"""Gemeinsame Grundlage aller Anbieter.

Ein Anbieter beschreibt sich selbst (Name, Art der Verbindung, Felder, Einrichtungsschritte) und implementiert sync().
In sync() holt er Daten über ctx.get()/ctx.post() und gibt sie normalisiert an ctx.writer weiter. Den Rest
(Tokens erneuern, Fehler, Zeitfenster, Status) erledigt die Sync-Engine.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import httpx

from .. import crypto
from ..store import Writer
from ..timeutil import utcnow

USER_AGENT = "BodyBase/1.0 (+https://github.com/Tillhnz/BodyBase)"


class SyncError(Exception):
    """Fehler mit verständlicher Meldung für die Oberfläche."""


class AuthError(SyncError):
    """Zugang abgelaufen oder widerrufen: Die Verbindung muss neu hergestellt werden."""


class RateLimited(SyncError):
    """Der Anbieter bremst. Beim nächsten Durchlauf geht es weiter."""


@dataclass
class Field:
    key: str
    label: str
    type: str = "text"  # text | password | url | number | select | textarea
    required: bool = True
    secret: bool = False
    help: str | None = None
    placeholder: str | None = None
    options: list[dict] | None = None
    default: str | None = None

    def public(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class OAuthSpec:
    authorize_url: str
    token_url: str
    scopes: list[str] = field(default_factory=list)
    scope_sep: str = " "
    pkce: bool = False
    token_auth: str = "body"  # body | basic
    extra_authorize: dict = field(default_factory=dict)
    send_redirect_on_refresh: bool = False


class Provider:
    key: str = ""
    name: str = ""
    kind: str = "oauth"  # oauth | apikey | login | push | file
    color: str = "#8fa2ff"
    initials: str = ""
    website: str = ""
    official: bool = True
    delivers: list[str] = []  # Kategorien: activity, sleep, body, heart, recovery, nutrition, metabolic, workouts
    summary: str = ""
    note: str | None = None
    setup: list[str] = []  # Schritte für den Nutzer
    app_setup: list[str] = []  # Schritte für den Administrator (Entwickler-App anlegen)
    app_fields: list[Field] = []  # vom Administrator einmal eingetragen (Client-ID, Secret …)
    fields: list[Field] = []  # vom Nutzer beim Verbinden eingetragen (API-Schlüssel, Adresse …)
    oauth: OAuthSpec | None = None
    interval_minutes: int | None = None  # None = Standard aus den Einstellungen
    overlap_days: int = 3  # wie weit vor dem letzten Stand erneut geholt wird (spät synchronisierte Geräte)

    # ---------- Beschreibung ----------

    def describe(self, app_ready: bool) -> dict:
        return {
            "key": self.key, "name": self.name, "kind": self.kind, "color": self.color,
            "initials": self.initials or self.name[:2], "website": self.website, "official": self.official,
            "delivers": self.delivers, "summary": self.summary, "note": self.note, "setup": self.setup,
            "app_setup": self.app_setup, "app_fields": [f.public() for f in self.app_fields],
            "fields": [f.public() for f in self.fields], "app_ready": app_ready,
            "needs_app": bool(self.app_fields),
        }

    # ---------- Haken für die Engine ----------

    def oauth_spec(self, app: dict) -> OAuthSpec | None:
        """OAuth-Adressen; einzelne Anbieter hängen sie von der Region ab."""
        return self.oauth

    def connect(self, ctx: "SyncContext", values: dict) -> str | None:
        """Prüft Zugangsdaten (API-Schlüssel, Login) und gibt den Kontonamen zurück. Wirft SyncError bei Fehlern."""
        return None

    def after_token(self, ctx: "SyncContext", token: dict) -> str | None:
        """Nach dem OAuth-Rücksprung: Kontoname bestimmen, Nutzer registrieren usw."""
        return None

    def parse_token(self, data: dict) -> dict:
        """Antwort des Token-Endpunkts -> {access_token, refresh_token, expires_at, ...}."""
        out = {k: v for k, v in data.items() if k not in ("access_token", "refresh_token", "expires_in", "expires_at")}
        out["access_token"] = data.get("access_token")
        out["refresh_token"] = data.get("refresh_token")
        if data.get("expires_at"):
            out["expires_at"] = float(data["expires_at"])
        elif data.get("expires_in"):
            out["expires_at"] = time.time() + float(data["expires_in"])
        return out

    def sync(self, ctx: "SyncContext") -> None:
        raise NotImplementedError

    has_tracks: bool = False  # liefert GPS-Strecke und Verlauf über track()

    def track(self, ctx: "SyncContext", row) -> tuple | None:
        """GPS-Strecke und Verlauf einer gespeicherten Aktivität holen (siehe tracks.py)."""
        return None

    def disconnect(self, ctx: "SyncContext") -> None:
        """Optional: Zugang beim Anbieter widerrufen."""
        return None


# ---------- Zustand einer laufenden Synchronisierung ----------

class SyncContext:
    def __init__(self, db, conn, user, provider: Provider, app: dict, redirect_uri: str, client: httpx.Client | None = None,
                 backfill_days: int = 90):
        self.db = db
        self.conn = conn
        self.user = user
        self.provider = provider
        self.app = app  # Client-ID usw. aus der Administration (entschlüsselt)
        self.redirect_uri = redirect_uri
        self.auth = crypto.decrypt_json(conn.auth) if conn is not None else {}
        self.config = dict(conn.config or {}) if conn is not None else {}
        self.cursor = dict(conn.cursor or {}) if conn is not None else {}
        self.http = client or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), headers={"User-Agent": USER_AGENT},
                                          follow_redirects=True)
        self.writer = Writer(db, user.id, provider.key) if user is not None else None
        self.backfill_days = backfill_days
        self.notes: list[str] = []
        self.track_budget = 15  # Detailabrufe für GPS-Strecken je Abgleich (siehe tracks.py)
        self.track_pending = 0
        self._dirty_auth = False
        last = self.cursor.get("last_success")
        now = utcnow()
        if last:
            try:
                self.since = datetime.fromisoformat(last) - timedelta(days=provider.overlap_days)
            except ValueError:
                self.since = now - timedelta(days=backfill_days)
        else:
            self.since = now - timedelta(days=int(self.config.get("backfill_days") or backfill_days))
        self.until = now

    # ---------- Zeitfenster ----------

    @property
    def since_date(self) -> date:
        return self.since.date()

    @property
    def until_date(self) -> date:
        return (self.until + timedelta(days=1)).date()

    def days(self, chunk: int):
        """Teilt das Zeitfenster in Abschnitte von höchstens chunk Tagen (für APIs mit begrenzter Spanne)."""
        start = self.since_date
        end = self.until_date
        while start <= end:
            stop = min(end, start + timedelta(days=chunk - 1))
            yield start, stop
            start = stop + timedelta(days=1)

    # ---------- Zugang ----------

    def save_auth(self) -> None:
        self._dirty_auth = True
        if self.conn is not None:
            self.conn.auth = crypto.encrypt_json(self.auth)
            self.db.commit()

    def token(self) -> str:
        tok = self.auth.get("access_token")
        if not tok:
            raise AuthError("Kein Zugang gespeichert. Bitte verbinde dich erneut.")
        exp = self.auth.get("expires_at")
        if exp and float(exp) - 120 < time.time() and self.auth.get("refresh_token"):
            self.refresh()
        return self.auth["access_token"]

    def refresh(self) -> None:
        spec = self.provider.oauth_spec(self.app)
        if spec is None or not self.auth.get("refresh_token"):
            raise AuthError("Der Zugang ist abgelaufen. Bitte verbinde dich erneut.")
        data = {"grant_type": "refresh_token", "refresh_token": self.auth["refresh_token"]}
        if spec.send_redirect_on_refresh:
            data["redirect_uri"] = self.redirect_uri
        payload = token_request(self.http, spec, self.app, data, self.provider)
        new = self.provider.parse_token(payload)
        if not new.get("access_token"):
            raise AuthError("Der Zugang konnte nicht erneuert werden. Bitte verbinde dich erneut.")
        if not new.get("refresh_token"):
            new["refresh_token"] = self.auth.get("refresh_token")
        self.auth.update(new)
        self.save_auth()

    # ---------- HTTP ----------

    def request(self, method: str, url: str, *, auth: str = "bearer", retry_auth: bool = True, expect_json: bool = True,
                ok_status: tuple = (), basic: tuple | None = None, **kw):
        """auth: "bearer" (OAuth-Token), "none" (Schlüssel steckt in Kopf/Parametern) oder "basic" (mit basic=(user, pw))."""
        headers = dict(kw.pop("headers", None) or {})
        if auth == "bearer":
            headers["Authorization"] = f"Bearer {self.token()}"
        if auth == "basic" and basic:
            kw["auth"] = basic
        try:
            r = self.http.request(method, url, headers=headers, **kw)
        except httpx.TimeoutException as e:
            raise SyncError(f"{self.provider.name} antwortet nicht (Zeitüberschreitung).") from e
        except httpx.HTTPError as e:
            raise SyncError(f"{self.provider.name} ist nicht erreichbar ({type(e).__name__}).") from e
        if r.status_code in ok_status:
            return r
        if r.status_code == 401 and auth == "bearer" and retry_auth and self.auth.get("refresh_token"):
            self.refresh()
            return self._retry(method, url, auth, expect_json, ok_status, headers, kw)
        check_response(self.provider.name, r)
        if not expect_json:
            return r
        if r.status_code == 204 or not r.content:
            return None
        try:
            return r.json()
        except ValueError as e:
            raise SyncError(f"{self.provider.name} lieferte keine lesbare Antwort.") from e

    def _retry(self, method, url, auth, expect_json, ok_status, headers, kw):
        headers = {k: v for k, v in headers.items() if k != "Authorization"}
        return self.request(method, url, auth=auth, retry_auth=False, expect_json=expect_json, ok_status=ok_status, headers=headers, **kw)

    def get(self, url: str, **kw):
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw):
        return self.request("POST", url, **kw)

    def note(self, text: str) -> None:
        self.notes.append(text)


def check_response(name: str, r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    snippet = (r.text or "")[:200].replace("\n", " ")
    if r.status_code in (401, 403):
        raise AuthError(f"{name} hat den Zugang abgelehnt ({r.status_code}). Bitte verbinde dich erneut. {snippet}".strip())
    if r.status_code == 429:
        raise RateLimited(f"{name} begrenzt gerade die Anfragen. Der nächste Abgleich holt den Rest nach.")
    raise SyncError(f"{name} meldet Fehler {r.status_code}. {snippet}".strip())


# ---------- OAuth ----------

def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def authorize_url(provider: Provider, app: dict, redirect_uri: str, state: str, challenge: str | None) -> str:
    spec = provider.oauth_spec(app)
    params = {"response_type": "code", "client_id": app.get("client_id", ""), "redirect_uri": redirect_uri, "state": state}
    if spec.scopes:
        params["scope"] = spec.scope_sep.join(spec.scopes)
    if spec.pkce and challenge:
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    params.update(spec.extra_authorize)
    sep = "&" if "?" in spec.authorize_url else "?"
    return spec.authorize_url + sep + urlencode(params)


def token_request(http: httpx.Client, spec: OAuthSpec, app: dict, data: dict, provider: Provider) -> dict:
    data = dict(data)
    headers = {"Accept": "application/json"}
    auth = None
    if spec.token_auth == "basic":
        auth = (app.get("client_id", ""), app.get("client_secret", ""))
        data.setdefault("client_id", app.get("client_id", ""))
    else:
        data["client_id"] = app.get("client_id", "")
        if app.get("client_secret"):
            data["client_secret"] = app["client_secret"]
    data = provider_token_extras(provider, data)
    try:
        r = http.post(spec.token_url, data=data, headers=headers, auth=auth)
    except httpx.HTTPError as e:
        raise SyncError(f"{provider.name} ist nicht erreichbar ({type(e).__name__}).") from e
    if r.status_code in (400, 401):
        raise AuthError(f"{provider.name} hat die Anmeldung abgelehnt ({r.status_code}): {(r.text or '')[:200]}")
    check_response(provider.name, r)
    try:
        return r.json()
    except ValueError as e:
        raise SyncError(f"{provider.name} lieferte keine lesbare Token-Antwort.") from e


def provider_token_extras(provider: Provider, data: dict) -> dict:
    extra = getattr(provider, "token_extra", None)
    return extra(data) if callable(extra) else data


# ---------- kleine Helfer für Anbieter ----------

def num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def iso_duration_s(value: str | None) -> float | None:
    """ISO-8601-Dauer wie PT1H2M3.5S -> Sekunden."""
    if not value or not isinstance(value, str) or not value.startswith("P"):
        return num(value)
    import re
    m = re.match(r"P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$", value)
    if not m:
        return None
    d, h, mi, s = (float(x) if x else 0.0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def epoch(dt: datetime) -> int:
    """UTC-Zeit ohne Zone -> Unix-Sekunden."""
    import calendar
    return calendar.timegm(dt.timetuple())
