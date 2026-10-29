"""Installierte Version und Hinweis auf ein Update, für die Fußzeile der Seitenleiste."""
import threading
import time

from fastapi import APIRouter, Depends

from .. import __version__
from ..models import User
from ..security import current_user
from .admin import _updater

router = APIRouter(prefix="/api", tags=["version"])

CHECK_EVERY_S = 3600
_lock = threading.Lock()
_state = {"behind": None, "checked": 0.0, "running": False}


def _refresh() -> None:
    try:
        r = _updater("GET", "/status?check=1", timeout=120)
        behind = r.get("behind")
        with _lock:
            _state["behind"] = bool(behind) if behind is not None else None
    except Exception:  # kein Update-Dienst: dann gibt es keinen Hinweis
        with _lock:
            _state["behind"] = None
    finally:
        with _lock:
            _state["checked"], _state["running"] = time.time(), False


@router.get("/version")
def version(user: User = Depends(current_user)):
    with _lock:
        stale = time.time() - _state["checked"] > CHECK_EVERY_S and not _state["running"]
        if stale:
            _state["running"] = True
        behind = _state["behind"]
    if stale:
        threading.Thread(target=_refresh, daemon=True, name="version-check").start()
    return {"version": __version__, "update_available": behind}
