"""Blutwerte: Laborbefund hochladen, prüfen, speichern und auswerten."""
from __future__ import annotations

from datetime import date

import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import labs as L
from ..database import get_db
from ..models import User
from ..security import current_user
from ..timeutil import today

router = APIRouter(prefix="/api", tags=["labs"])
MAX_BYTES = 15 * 1024 * 1024


@router.get("/labs")
def labs_overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Alle Blutwerte mit Einordnung, Verlauf, Verknüpfungen zu den Körperdaten und PhenoAge."""
    return L.overview(db, user)


@router.post("/labs/parse")
async def labs_parse(file: UploadFile | None = File(None), text: str | None = Form(None), user: User = Depends(current_user)):
    """Liest einen Befund (PDF oder Text) und gibt die erkannten Werte zur Kontrolle zurück – gespeichert wird noch nichts."""
    if file is None and not text:
        raise HTTPException(422, "Bitte eine PDF-Datei oder Text schicken.")
    if file is not None:
        data = await file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "Die Datei ist größer als 15 MB.")
        name = (file.filename or "").lower()
        ocr = False
        if name.endswith(".pdf") or data[:4] == b"%PDF":
            try:
                text = L.pdf_text(data)
            except Exception as e:  # noqa: BLE001
                raise HTTPException(422, f"Die PDF-Datei ließ sich nicht lesen ({type(e).__name__}).") from e
            if len(re.sub(r"\s", "", text or "")) < 80 and L.ocr_available():  # kein Text drin: eingescannt
                try:
                    text = await run_in_threadpool(L.ocr_pdf, data)
                    ocr = True
                except Exception as e:  # noqa: BLE001
                    raise HTTPException(422, f"Die Texterkennung ist fehlgeschlagen ({type(e).__name__}).") from e
        elif data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or name.endswith((".jpg", ".jpeg", ".png")):
            if not L.ocr_available():
                raise HTTPException(422, "Texterkennung ist auf diesem Server nicht installiert – bitte „bodybase update“ ausführen.")
            text = await run_in_threadpool(L.ocr_image, data)
            ocr = True
        else:
            text = data.decode("utf-8", "ignore")
        res = L.parse(text or "")
        res["ocr"] = ocr
        if not res["markers"]:
            res["hint"] = ("Auch mit Texterkennung wurden keine Blutwerte gefunden – ist der Scan scharf und gerade? Sonst bitte von Hand eintragen."
                           if ocr else "In der Datei steht kein auslesbarer Text. Bitte „bodybase update“ ausführen (Texterkennung) oder die Werte von Hand eintragen."
                           if res["chars"] < 50 else "Keine bekannten Blutwerte gefunden. Du kannst sie unten von Hand eintragen.")
        return res
    res = L.parse(text or "")
    if not res["markers"]:
        res["hint"] = ("In der Datei steht kein auslesbarer Text – vermutlich ein eingescannter Befund. Bitte die Werte von Hand eintragen."
                       if res["chars"] < 50 else "Keine bekannten Blutwerte gefunden. Du kannst sie unten von Hand eintragen.")
    return res


class SaveIn(BaseModel):
    day: date
    values: dict[str, float] = Field(default_factory=dict)


@router.post("/labs")
def labs_save(data: SaveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.day > today():
        raise HTTPException(422, "Das Datum liegt in der Zukunft.")
    unknown = [k for k in data.values if k not in L.BY_KEY]
    if unknown:
        raise HTTPException(422, f"Unbekannte Werte: {', '.join(unknown)}")
    n = L.save(db, user, data.day, data.values)
    return {"saved": n}


@router.delete("/labs/{day}", status_code=204)
def labs_delete(day: date, user: User = Depends(current_user), db: Session = Depends(get_db)):
    L.remove_day(db, user, day)
