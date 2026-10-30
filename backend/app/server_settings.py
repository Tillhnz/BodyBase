"""Einstellungen aus der Administration: Zugangsdaten der Anbieter-Apps und einige Server-Optionen.

Werte aus der Oberfläche haben Vorrang vor der .env. Geheimnisse werden verschlüsselt gespeichert und nie
zurückgegeben (die Oberfläche sieht nur, ob ein Wert gesetzt ist).
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from . import crypto
from .config import settings
from .models import ServerSetting

# Optionen, die der Administrator in der Oberfläche ändern darf: Name -> (Typ, Grenzen)
OPTIONS = {
    "public_url": ("url", 300),
    "map_tile_url": ("str", 300),
    "carto_api_key": ("str", 128),
    "allow_registration": ("bool", None),
    "frame_ancestors": ("str", 500),
    "sync_interval_minutes": ("int", (15, 1440)),
    "backfill_days": ("int", (7, 3650)),
    "timezone": ("str", 60),
}


def _get(db: Session, key: str) -> str | None:
    row = db.get(ServerSetting, key)
    return row.value if row else None


def _set(db: Session, key: str, value: str | None) -> None:
    row = db.get(ServerSetting, key)
    if value is None:
        if row:
            db.delete(row)
        return
    if row is None:
        db.add(ServerSetting(key=key, value=value))
    else:
        row.value = value


# ---------- Anbieter-Apps ----------

def get_app(db: Session, provider_key: str) -> dict:
    return crypto.decrypt_json(_get(db, f"app:{provider_key}"))


def set_app(db: Session, provider, values: dict) -> dict:
    current = get_app(db, provider.key)
    out = {}
    for f in provider.app_fields:
        v = values.get(f.key)
        if v is None or (f.secret and v == ""):
            if f.key in current:
                out[f.key] = current[f.key]  # leeres Geheimnis-Feld = unverändert lassen
            continue
        v = str(v).strip()
        if v:
            out[f.key] = v
    _set(db, f"app:{provider.key}", crypto.encrypt_json(out) if out else None)
    db.commit()
    return out


def clear_app(db: Session, provider_key: str) -> None:
    _set(db, f"app:{provider_key}", None)
    db.commit()


def app_ready(db: Session, provider) -> bool:
    if not provider.app_fields:
        return True
    app = get_app(db, provider.key)
    return all(app.get(f.key) for f in provider.app_fields if f.required)


def app_public(db: Session, provider) -> dict:
    app = get_app(db, provider.key)
    return {f.key: ("" if f.secret else app.get(f.key, f.default or "")) for f in provider.app_fields} | \
        {f"{f.key}__set": bool(app.get(f.key)) for f in provider.app_fields}


# ---------- Server-Optionen ----------

def apply_overrides(db: Session) -> None:
    """Gespeicherte Optionen beim Start in settings übernehmen."""
    raw = _get(db, "options")
    if not raw:
        return
    try:
        values = json.loads(raw)
    except ValueError:
        return
    for k, v in values.items():
        if k in OPTIONS:
            setattr(settings, k, v)


def options(db: Session) -> dict:
    return {k: getattr(settings, k) for k in OPTIONS}


def save_options(db: Session, values: dict) -> dict:
    raw = _get(db, "options")
    try:
        stored = json.loads(raw) if raw else {}
    except ValueError:
        stored = {}
    for k, v in values.items():
        if k not in OPTIONS:
            continue
        typ, lim = OPTIONS[k]
        if typ == "url":
            from urllib.parse import urlsplit
            v = str(v or "").strip().rstrip("/")
            parts = urlsplit(v)
            if parts.scheme not in ("http", "https") or not parts.hostname or len(v) > lim or parts.query or parts.fragment:
                raise ValueError("Die öffentliche Adresse muss mit http:// oder https:// beginnen, z. B. https://body.example.de")
            if parts.path not in ("",):
                raise ValueError("Bitte nur die Adresse ohne Pfad angeben, z. B. https://body.example.de")
        elif typ == "bool":
            v = bool(v)
        elif typ == "int":
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
            v = max(lim[0], min(lim[1], v))
        else:
            v = str(v or "").strip()[:lim]
            if k == "timezone":
                try:
                    from zoneinfo import ZoneInfo
                    ZoneInfo(v)
                except Exception:
                    continue
        stored[k] = v
        setattr(settings, k, v)
    _set(db, "options", json.dumps(stored))
    db.commit()
    return options(db)
