"""Abend-Erinnerung an offene Gewohnheiten, per Push über ntfy (mit Link zur Gewohnheiten-Seite).

Einstellung je Nutzer in prefs["habit_reminder"] = {"enabled": bool, "time": "HH:MM", "topic": "…"}.
Ohne eigenes Thema wird das Server-Thema genutzt (nur für Admins, damit fremde Nutzer dort nichts bekommen).
"""
from __future__ import annotations

import logging
import threading
import time as _time
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import Habit, HabitLog, User
from .timeutil import today, tz

log = logging.getLogger("bodybase.reminders")
DEFAULT_TIME = "20:00"


def config(user: User) -> dict:
    c = dict((user.prefs or {}).get("habit_reminder") or {})
    return {"enabled": bool(c.get("enabled")), "time": c.get("time") or DEFAULT_TIME, "topic": c.get("topic") or "",
            "last_sent": c.get("last_sent")}


def topic_for(user: User) -> str:
    c = config(user)
    return c["topic"] or (settings.ntfy_topic if user.role == "admin" else "")


def open_habits(db: Session, user: User, d=None) -> list[dict]:
    from . import habits as H
    d = d or today()
    out = []
    for h in db.scalars(select(Habit).where(Habit.user_id == user.id, Habit.archived.isnot(True))):
        if not H.due_on(h, d):
            continue
        v = db.scalar(select(HabitLog.value).where(HabitLog.habit_id == h.id, HabitLog.day == d))
        if H.is_done(h, d, v):
            continue
        t = H.target_for(h, d)
        rest = f"{(f"{t - (v or 0):g}".replace(".", ","))} {h.unit or ''}".strip() if h.kind == "count" and t else None
        out.append({"id": h.id, "name": h.name, "rest": rest})
    return out


def message(items: list[dict]) -> tuple[str, str]:
    n = len(items)
    title = f"{n} Gewohnheit{'en' if n > 1 else ''} noch offen"
    lines = [f"• {i['name']}" + (f" (noch {i['rest']})" if i["rest"] else "") for i in items[:8]]
    return title, "\n".join(lines) + ("\n…" if n > 8 else "")


def send(topic: str, title: str, body: str) -> None:
    url = settings.public_url.rstrip("/") + "/habits"
    payload = {"topic": topic, "title": title, "message": body, "priority": 3, "tags": ["white_check_mark"], "click": url,
               "actions": [{"action": "view", "label": "Gewohnheiten öffnen", "url": url, "clear": True}]}
    r = httpx.post(settings.ntfy_url.rstrip("/"), json=payload, timeout=15)
    r.raise_for_status()


def run_once(now: datetime | None = None, sender=send) -> int:
    """Verschickt fällige Erinnerungen; gibt die Anzahl zurück."""
    now = now or datetime.now(tz())
    hhmm = now.strftime("%H:%M")
    sent = 0
    with SessionLocal() as db:
        for user in db.scalars(select(User)):
            c = config(user)
            if not c["enabled"] or hhmm < c["time"] or c["last_sent"] == now.date().isoformat():
                continue
            topic = topic_for(user)
            if not topic:
                continue
            items = open_habits(db, user, now.date())
            prefs = dict(user.prefs or {})
            hr = dict(prefs.get("habit_reminder") or {})
            hr["last_sent"] = now.date().isoformat()  # auch ohne offene Gewohnheiten: heute erledigt
            if items:
                try:
                    sender(topic, *message(items))
                    sent += 1
                except Exception as e:  # noqa: BLE001
                    log.warning("Erinnerung an %s fehlgeschlagen: %s", user.id, e)
                    continue  # nächste Minute erneut versuchen
            prefs["habit_reminder"] = hr
            user.prefs = prefs
            db.commit()
    return sent


def start_background() -> None:
    def loop() -> None:
        while True:
            try:
                run_once()
            except Exception:
                log.exception("Erinnerungen fehlgeschlagen")
            _time.sleep(60)
    threading.Thread(target=loop, daemon=True, name="habit-reminders").start()
