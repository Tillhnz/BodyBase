"""Verschlüsselung für Zugangsdaten der Anbieter (Tokens, API-Schlüssel, Passwörter).

Der Schlüssel wird aus SECRET_KEY abgeleitet. Wer SECRET_KEY ändert, muss die Verbindungen neu herstellen.
"""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


def _fernet() -> Fernet:
    key = hashlib.sha256(("bodybase-secrets:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(text: str | None) -> str | None:
    if text is None or text == "":
        return None
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def encrypt_json(data: dict | None) -> str | None:
    return encrypt(json.dumps(data)) if data else None


def decrypt_json(token: str | None) -> dict:
    raw = decrypt(token)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}
