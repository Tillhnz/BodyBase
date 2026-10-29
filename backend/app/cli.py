"""Befehle für die Konsole im Container, z. B.:

    docker compose exec backend python -m app.cli reset-password du@example.de NeuesPasswort
    docker compose exec backend python -m app.cli demo-data du@example.de
    docker compose exec backend python -m app.cli set-url https://body.example.de
"""
import sys

from sqlalchemy import select

from .database import Base, SessionLocal, engine, ensure_columns
from .models import User
from .security import hash_password


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    Base.metadata.create_all(engine)
    ensure_columns()
    cmd = argv[1]
    with SessionLocal() as db:
        if cmd == "reset-password" and len(argv) == 4:
            u = db.scalar(select(User).where(User.email == argv[2].lower()))
            if not u:
                print("Konto nicht gefunden.")
                return 1
            u.password_hash = hash_password(argv[3])
            u.token_version = (u.token_version or 0) + 1
            u.active = True
            db.commit()
            print("Passwort gesetzt.")
            return 0
        if cmd == "make-admin" and len(argv) == 3:
            u = db.scalar(select(User).where(User.email == argv[2].lower()))
            if not u:
                print("Konto nicht gefunden.")
                return 1
            u.role = "admin"
            db.commit()
            print("Ist jetzt Administrator.")
            return 0
        if cmd == "set-url" and len(argv) == 3:
            from . import server_settings
            try:
                server_settings.save_options(db, {"public_url": argv[2]})
            except ValueError as e:
                print(e)
                return 1
            print("Öffentliche Adresse gespeichert.")
            return 0
        if cmd == "demo-data" and len(argv) >= 3:
            from .demo import generate
            u = db.scalar(select(User).where(User.email == argv[2].lower()))
            if not u:
                print("Konto nicht gefunden.")
                return 1
            print(generate(db, u, int(argv[3]) if len(argv) > 3 else 180))
            return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
