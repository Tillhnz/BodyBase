"""Blutwerte: Laborbefund (PDF oder Text) auslesen, einordnen und mit den übrigen Körperdaten verknüpfen.

Ablauf: PDF → Text (pypdf) → Zeilen mit bekannten Markern, Wert, Einheit → Umrechnung in eine feste Einheit →
Speichern als Messwerte (Quelle „lab“, Kennung lab_<marker>) → Auswertung gegen Referenz- und Zielbereiche und
gegen Training, Schlaf, Erholung und Körperwerte.

Referenzbereiche sind übliche Laborbereiche für Erwachsene; „Zielbereich“ ist, was Studien für Gesundheit und
Leistung als günstig ansehen. Das ersetzt keine ärztliche Beurteilung – maßgeblich ist der Bereich auf dem Befund.
"""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Sample, User
from .store import Writer, day_ts, daily_series
from .timeutil import today


@dataclass
class Marker:
    key: str
    label: str
    unit: str
    alias: str  # regulärer Ausdruck, Groß-/Kleinschreibung egal
    conv: dict = field(default_factory=dict)  # Einheit (klein, ohne Leerzeichen) -> Faktor zur Ziel-Einheit
    ref: tuple | dict = (None, None)  # (unten, oben) oder {"m": (..), "f": (..)}
    opt: tuple | dict | None = None  # Zielbereich
    plaus: tuple = (0, 1e6)
    group: str = "Sonstiges"
    what: str = ""
    low: str = ""
    high: str = ""
    decimals: int = 1


M = [
    # Blutbild
    Marker("hemoglobin", "Hämoglobin", "g/dL", r"h[äa]e?moglobin(?!\s*a1c)|\bhgb\b|\bhb\b(?!\s*a1)", {"g/l": 0.1, "mmol/l": 1.611}, {"m": (13.5, 17.5), "f": (12.0, 15.5)},
           None, (5, 25), "Blutbild", "Sauerstoffträger im Blut – entscheidend für Ausdauer.",
           "Weniger Sauerstofftransport: schneller müde, höherer Puls bei gleicher Leistung. Häufig Eisenmangel.", "Oft durch Höhe, Flüssigkeitsmangel oder Rauchen."),
    Marker("hematocrit", "Hämatokrit", "%", r"h[äa]matokrit|\bhkt\b|\bhct\b|\bhk\b", {"l/l": 100}, {"m": (40, 52), "f": (36, 46)}, None, (15, 70), "Blutbild",
           "Anteil der Blutzellen am Blutvolumen.", "Passt oft zu niedrigem Hämoglobin.", "Häufig Flüssigkeitsmangel – Wert nach ausreichend Trinken kontrollieren."),
    Marker("rbc", "Erythrozyten", "/pL", r"erythrozyten|\brbc\b|\bery\b", {"mio/µl": 1, "mio/ul": 1, "t/l": 1, "10^12/l": 1, "/pl": 1, "10^6/µl": 1}, {"m": (4.3, 5.9), "f": (3.9, 5.2)},
           None, (1, 9), "Blutbild", "Rote Blutkörperchen.", "Kann auf Blutarmut hinweisen.", "Oft Flüssigkeitsmangel."),
    Marker("mcv", "MCV", "fL", r"\bmcv\b", {}, (80, 100), None, (50, 140), "Blutbild", "Größe der roten Blutkörperchen.",
           "Kleine Zellen: typisch für Eisenmangel.", "Große Zellen: häufig Mangel an B12 oder Folsäure, auch Alkohol."),
    Marker("mch", "MCH", "pg", r"\bmch\b(?!c)", {}, (27, 34), None, (10, 50), "Blutbild", "Hämoglobin je Blutkörperchen.", "Typisch für Eisenmangel.", "Passt zu B12-/Folsäuremangel."),
    Marker("mchc", "MCHC", "g/dL", r"\bmchc\b", {"g/l": 0.1}, (32, 36), None, (20, 45), "Blutbild", "Hämoglobinkonzentration der Zellen."),
    Marker("rdw", "RDW", "%", r"\brdw\b", {}, (11.5, 14.5), (11.5, 13.5), (5, 30), "Blutbild", "Wie unterschiedlich groß die roten Blutkörperchen sind; Teil des PhenoAge.",
           "", "Uneinheitliche Zellen – oft beginnender Eisen- oder Vitaminmangel; gilt auch als Altersmarker."),
    Marker("wbc", "Leukozyten", "/nL", r"leukozyten|\bwbc\b|\bleuko\b", {"g/l": 1, "10^9/l": 1, "/nl": 1, "tsd/µl": 1, "tsd/ul": 1, "10^3/µl": 1, "10^3/ul": 1}, (4.0, 10.0), (4.0, 7.5),
           (0.5, 60), "Blutbild", "Weiße Blutkörperchen (Abwehr).", "Kann nach Infekten oder bei sehr hohem Trainingsumfang vorkommen.",
           "Hinweis auf Entzündung oder Infekt – auch nach harten Einheiten kurzzeitig erhöht."),
    Marker("lymph_pct", "Lymphozyten", "%", r"lymphozyten(?!\s*(abs|absolut|#))|\blymph\b(?!.*#)", {}, (20, 45), None, (1, 90), "Blutbild",
           "Anteil der Lymphozyten an den Leukozyten; Teil des PhenoAge.", "Niedrig bei Stress, Übertraining oder Infekt.", ""),
    Marker("platelets", "Thrombozyten", "/nL", r"thrombozyten|\bplt\b|\bthrombo\b", {"g/l": 1, "10^9/l": 1, "/nl": 1, "tsd/µl": 1, "tsd/ul": 1, "10^3/µl": 1}, (150, 400), None,
           (10, 1500), "Blutbild", "Blutplättchen (Gerinnung)."),
    # Eisen & Vitamine
    Marker("ferritin", "Ferritin", "ng/mL", r"ferritin", {"µg/l": 1, "ug/l": 1, "ng/ml": 1}, {"m": (30, 400), "f": (15, 150)}, (50, 300), (1, 5000), "Eisen & Vitamine",
           "Eisenspeicher. Für Sportler gelten über 50 ng/ml als günstig.",
           "Leere Eisenspeicher: Müdigkeit, schlechtere Ausdauer und Erholung, oft schon bevor das Hämoglobin sinkt.",
           "Auch bei Entzündungen erhöht (mit CRP vergleichen); dauerhaft hohe Werte ärztlich abklären."),
    Marker("iron", "Eisen", "µg/dL", r"^\s*eisen\b(?!.*(bind|sätt))", {"µmol/l": 5.585, "umol/l": 5.585}, (60, 170), None, (5, 500), "Eisen & Vitamine",
           "Eisen im Blut – schwankt stark mit Tageszeit und Essen."),
    Marker("tsat", "Transferrinsättigung", "%", r"transferrins[äa]ttigung|\btsat\b", {}, (16, 45), (20, 45), (1, 100), "Eisen & Vitamine", "Wie viel Eisen gerade transportiert wird.",
           "Zu wenig verfügbares Eisen."),
    Marker("vitd", "Vitamin D (25-OH)", "ng/mL", r"25[-\s]?oh|vitamin\s*d|calcidiol|25-hydroxy", {"nmol/l": 0.4, "µg/l": 1, "ug/l": 1}, (20, 100), (30, 60), (2, 250),
           "Eisen & Vitamine", "Wichtig für Knochen, Muskeln und Abwehr; im Winter fast immer niedriger.",
           "Mangel: mehr Infekte, schwächere Muskeln, schlechtere Knochen. Von Oktober bis März bildet die Haut in Deutschland kaum Vitamin D.",
           "Sehr hohe Werte nur durch Präparate – Dosis prüfen."),
    Marker("b12", "Vitamin B12", "pg/mL", r"vitamin\s*b\s*12|\bb12\b|cobalamin", {"pmol/l": 1.355, "ng/l": 1}, (200, 900), (400, 900), (50, 5000), "Eisen & Vitamine",
           "Für Blutbildung und Nerven.", "Mangel: Müdigkeit, Kribbeln, Konzentrationsprobleme; häufig bei pflanzlicher Ernährung.", ""),
    Marker("folate", "Folsäure", "ng/mL", r"fols[äa]ure|folat", {"nmol/l": 0.441, "µg/l": 1}, (4, 20), None, (0.5, 60), "Eisen & Vitamine", "Für Zellteilung und Blutbildung.",
           "Wenig Gemüse und Hülsenfrüchte?"),
    Marker("magnesium", "Magnesium", "mmol/L", r"magnesium|\bmg\b(?=\s*[\d,.]+\s*mmol)", {"mg/dl": 0.4114}, (0.75, 1.05), (0.85, 1.05), (0.2, 3), "Mineralstoffe",
           "Für Muskeln und Nerven.", "Krämpfe, schlechter Schlaf; viel Schwitzen erhöht den Bedarf."),
    Marker("calcium", "Calcium", "mmol/L", r"calcium|kalzium", {"mg/dl": 0.2495}, (2.2, 2.6), None, (1, 4), "Mineralstoffe", "Knochen, Muskeln, Nerven."),
    Marker("sodium", "Natrium", "mmol/L", r"natrium", {}, (135, 145), None, (100, 180), "Mineralstoffe", "Salz- und Wasserhaushalt.",
           "Zu viel Wasser ohne Salz bei langen Belastungen?", "Oft Flüssigkeitsmangel."),
    Marker("potassium", "Kalium", "mmol/L", r"kalium", {}, (3.5, 5.1), None, (1.5, 9), "Mineralstoffe", "Herz und Muskeln.", "", "Häufig ein Messfehler durch zu lange gelagerte Probe."),
    # Stoffwechsel
    Marker("hba1c", "HbA1c", "%", r"hba1c|h[äa]moglobin\s*a1c", {"mmol/mol": "hba1c"}, (4.0, 5.6), (4.0, 5.4), (3, 20), "Zucker",
           "Langzeit-Blutzucker der letzten 2–3 Monate.", "", "Der Zuckerstoffwechsel ist belastet. Ab 5,7 % spricht man von Prädiabetes."),
    Marker("lab_glucose", "Glukose (nüchtern)", "mg/dL", r"glu[ck]ose|blutzucker", {"mmol/l": 18.016}, (70, 99), (70, 90), (20, 600), "Zucker",
           "Nüchtern-Blutzucker.", "Niedrig: zu lange nichts gegessen oder viel Training.", "Erhöht – nur aussagekräftig, wenn wirklich nüchtern (8 h nichts gegessen)."),
    Marker("insulin", "Insulin (nüchtern)", "µU/mL", r"insulin", {"pmol/l": 0.144, "mu/l": 1, "mU/l": 1}, (2.6, 24.9), (2, 10), (0.5, 300), "Zucker",
           "Wie viel Insulin der Körper braucht, um den Zucker zu halten.", "", "Hinweis auf Insulinresistenz – Bewegung und Gewichtsabnahme senken den Wert am stärksten."),
    Marker("chol", "Cholesterin gesamt", "mg/dL", r"^(?!.*\b(ldl|hdl|non)\b).*cholesterin|^(?!.*\b(ldl|hdl)\b).*cholesterol", {"mmol/l": 38.67}, (0, 200), (0, 190), (50, 600), "Blutfette",
           "Summe aller Cholesterine – allein wenig aussagekräftig."),
    Marker("ldl", "LDL-Cholesterin", "mg/dL", r"\bldl\b", {"mmol/l": 38.67}, (0, 116), (0, 100), (10, 500), "Blutfette",
           "„Schlechtes“ Cholesterin – wichtigster Blutfett-Risikofaktor für Herz und Gefäße.", "",
           "Je niedriger und je früher, desto besser für die Gefäße. Ernährung (gesättigte Fette), Ballaststoffe und Bewegung senken den Wert."),
    Marker("hdl", "HDL-Cholesterin", "mg/dL", r"\bhdl\b", {"mmol/l": 38.67}, {"m": (40, 200), "f": (50, 200)}, (55, 100), (5, 200), "Blutfette",
           "„Gutes“ Cholesterin.", "Niedrig bei Bewegungsmangel, Übergewicht und Rauchen; Ausdauertraining hebt den Wert.", ""),
    Marker("trig", "Triglyceride", "mg/dL", r"triglycerid", {"mmol/l": 88.57}, (0, 150), (0, 100), (10, 3000), "Blutfette",
           "Fette im Blut – stark abhängig von der letzten Mahlzeit.", "", "Zucker, Weißmehl und Alkohol treiben den Wert; nur nüchtern aussagekräftig."),
    Marker("lpa", "Lipoprotein(a)", "mg/dL", r"lipoprotein\s*\(?a\)?|\blp\s*\(a\)", {"nmol/l": 0.4167}, (0, 30), (0, 30), (0, 500), "Blutfette",
           "Erblich festgelegter Risikofaktor – muss nur einmal im Leben gemessen werden.", "", "Erhöhtes erbliches Risiko: die anderen Faktoren (LDL, Blutdruck) umso konsequenter niedrig halten."),
    Marker("apob", "Apolipoprotein B", "mg/dL", r"apo(lipoprotein)?\s*b", {"g/l": 100}, (0, 100), (0, 90), (10, 300), "Blutfette", "Anzahl der gefäßschädigenden Partikel – genauer als LDL."),
    Marker("uric", "Harnsäure", "mg/dL", r"harns[äa]ure", {"µmol/l": 0.0168, "umol/l": 0.0168}, {"m": (3.4, 7.0), "f": (2.4, 5.7)}, None, (0.5, 20), "Stoffwechsel",
           "Abbauprodukt; zu viel kann Gicht und Nierensteine auslösen.", "", "Fleisch, Alkohol (v. a. Bier) und Fruchtzucker erhöhen den Wert; viel trinken."),
    # Entzündung
    Marker("crp", "CRP", "mg/L", r"\b(hs-?)?crp\b|c-?reaktiv", {"mg/dl": 10}, (0, 5), (0, 1), (0, 500), "Entzündung",
           "Entzündungswert; hochsensitiv gemessen auch ein Herz-Kreislauf-Risikomarker.", "",
           "Entzündung im Körper – Infekt, Verletzung oder sehr harte Belastung. Bei erhöhtem Wert keine intensiven Einheiten."),
    # Schilddrüse
    Marker("tsh", "TSH", "mU/L", r"\btsh\b", {"µu/ml": 1, "uu/ml": 1, "mu/l": 1, "miu/l": 1}, (0.4, 4.0), (0.5, 2.5), (0.005, 100), "Schilddrüse",
           "Steuerhormon der Schilddrüse.", "Mögliche Überfunktion: hoher Ruhepuls, Gewichtsverlust, Unruhe.", "Mögliche Unterfunktion: Müdigkeit, Frieren, Gewichtszunahme."),
    Marker("ft4", "fT4", "ng/dL", r"\bft4\b|freies\s*t4", {"pmol/l": 0.0777}, (0.9, 1.7), None, (0.1, 8), "Schilddrüse", "Schilddrüsenhormon."),
    # Niere, Leber, Muskel
    Marker("creatinine", "Kreatinin", "mg/dL", r"kreatinin(?!.*(clear|kinase))|creatinin", {"µmol/l": 0.01131, "umol/l": 0.01131}, {"m": (0.7, 1.2), "f": (0.5, 1.0)}, None, (0.2, 15),
           "Niere", "Nierenwert – bei viel Muskelmasse und Kreatin-Einnahme natürlicherweise höher; Teil des PhenoAge.", "", "Viel Muskelmasse, Kreatin oder Fleisch vor der Messung? Sonst Nierenfunktion prüfen lassen."),
    Marker("egfr", "eGFR", "mL/min", r"\begfr\b|glomerul", {}, (90, 200), None, (5, 200), "Niere", "Geschätzte Filterleistung der Nieren.",
           "Niedriger als ideal – bei muskulösen Menschen oft unterschätzt (über Kreatinin berechnet). Cystatin C wäre genauer.", ""),
    Marker("urea", "Harnstoff", "mg/dL", r"harnstoff(?!.*stickstoff)", {"mmol/l": 6.006}, (17, 49), None, (2, 300), "Niere", "Eiweißabbau; steigt bei viel Eiweiß oder Flüssigkeitsmangel."),
    Marker("ast", "GOT (AST)", "U/L", r"\bgot\b|\basat\b|\bast\b", {"u/l": 1}, {"m": (0, 50), "f": (0, 35)}, None, (1, 5000), "Leber & Muskel",
           "Leber- und Muskelenzym.", "", "Nach hartem Training (v. a. Kraft, Bergab-Laufen) oft erhöht – sonst Leber prüfen."),
    Marker("alt", "GPT (ALT)", "U/L", r"\bgpt\b|\balat\b|\balt\b", {"u/l": 1}, {"m": (0, 50), "f": (0, 35)}, (0, 30), (1, 5000), "Leber & Muskel",
           "Leberenzym.", "", "Häufig durch Fettleber (Bauchfett, Zucker, Alkohol); auch nach sehr hartem Training."),
    Marker("ggt", "Gamma-GT", "U/L", r"gamma-?\s*gt|\bggt\b|γ-gt", {"u/l": 1}, {"m": (0, 60), "f": (0, 40)}, (0, 30), (1, 3000), "Leber & Muskel",
           "Leberenzym, reagiert empfindlich auf Alkohol.", "", "Alkohol, Fettleber oder Medikamente sind die häufigsten Ursachen."),
    Marker("alp", "Alkalische Phosphatase", "U/L", r"alkalische\s*phosphatase|\bap\b(?=\s*[\d,.])|\balp\b", {"u/l": 1}, (40, 130), None, (5, 2000), "Leber & Muskel",
           "Leber- und Knochenenzym; Teil des PhenoAge."),
    Marker("ck", "Kreatinkinase (CK)", "U/L", r"kreatin-?kinase|creatin-?kinase|\bck\b(?!-mb)", {"u/l": 1}, {"m": (0, 190), "f": (0, 170)}, None, (5, 100000), "Leber & Muskel",
           "Muskelenzym – zeigt, wie stark die Muskeln zuletzt belastet wurden.", "", "Nach Training völlig normal; aussagekräftig erst nach 3 Tagen ohne hartes Training."),
    Marker("albumin", "Albumin", "g/dL", r"^\s*albumin(?!.*(urin|krea|quot))", {"g/l": 0.1}, (3.5, 5.2), None, (1, 7), "Leber & Muskel", "Wichtigstes Bluteiweiß; Teil des PhenoAge.",
           "Kann auf zu wenig Eiweiß in der Ernährung oder eine Entzündung hinweisen."),
    # Hormone
    Marker("testosterone", "Testosteron", "ng/mL", r"testosteron(?!.*frei)", {"nmol/l": 0.2884, "ng/dl": 0.01}, {"m": (2.5, 8.5), "f": (0.1, 0.6)}, None, (0.01, 30), "Hormone",
           "Wichtig für Muskelaufbau, Energie und Libido.", "Zu wenig Schlaf, Energiemangel, sehr hohe Trainingsumfänge und Übergewicht senken den Wert.", ""),
]
BY_KEY = {m.key: m for m in M}


def _register() -> None:
    """Blutwerte als eigene Messgrößen (Kategorie „Blutwerte“), damit sie in Verläufen und Trends auftauchen."""
    from . import metrics as MT
    MT.CATEGORIES.setdefault("blood", "Blutwerte")
    for m in M:
        better = "down" if m.key in ("ldl", "apob", "lpa", "trig", "hba1c", "crp", "lab_glucose", "insulin", "ggt", "alt") else "up" if m.key in ("hdl", "ferritin", "vitd") else None
        MT.METRICS.setdefault(f"lab_{m.key}", MT.Metric(f"lab_{m.key}", m.label, m.unit, "blood", "avg", m.decimals if m.decimals else 0, better, m.plaus[0], m.plaus[1]))


_register()
METRIC = {m.key: f"lab_{m.key}" for m in M}
GROUPS = ["Blutbild", "Eisen & Vitamine", "Mineralstoffe", "Zucker", "Blutfette", "Stoffwechsel", "Entzündung", "Schilddrüse", "Niere", "Leber & Muskel", "Hormone", "Sonstiges"]

NUM = r"([<>≤≥]?\s*\d+(?:[.,]\d+)?)"
DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")


def _f(s: str) -> float:
    return float(s.replace(",", ".").replace("<", "").replace(">", "").replace("≤", "").replace("≥", "").strip())


def _norm_unit(u: str) -> str:
    return u.lower().replace(" ", "").replace("μ", "µ").replace("x", "").replace("10e", "10^").replace("·", "")


def _rng(r, sex):
    return r.get("f" if sex == "f" else "m") if isinstance(r, dict) else r


def _convert(m: Marker, v: float, unit: str | None) -> float | None:
    u = _norm_unit(unit or "")
    if u and u == _norm_unit(m.unit):
        return v
    for cu, fac in m.conv.items():
        if u and u == _norm_unit(cu):
            return (v / 10.929 + 2.15) if fac == "hba1c" else v * fac
    lo, hi = m.plaus
    if lo <= v <= hi:  # Einheit fehlt oder unbekannt: ohne Umrechnung, wenn plausibel
        return v
    for cu, fac in m.conv.items():  # sonst die Umrechnung nehmen, die einen plausiblen Wert ergibt
        x = (v / 10.929 + 2.15) if fac == "hba1c" else v * fac
        if lo <= x <= hi:
            return x
    return None


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in r.pages)


OCR_MAX_PAGES = 8


def ocr_available() -> bool:
    import shutil
    return bool(shutil.which("tesseract"))


def _tesseract(png: bytes) -> str:
    import subprocess
    # psm 6: ein Textblock – hält Tabellenzeilen (Name, Wert, Einheit, Bereich) zusammen
    r = subprocess.run(["tesseract", "stdin", "stdout", "-l", "deu+eng", "--psm", "6", "-c", "preserve_interword_spaces=1"],
                       input=png, capture_output=True, timeout=120, check=False)
    return r.stdout.decode("utf-8", "ignore")


def ocr_pdf(data: bytes) -> str:
    """Eingescannte PDF: Seiten mit 300 dpi in Bilder umwandeln (pdftoppm) und Text erkennen (Tesseract)."""
    import subprocess
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        src.write_bytes(data)
        subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", "-l", str(OCR_MAX_PAGES), str(src), str(Path(tmp) / "p")],
                       capture_output=True, timeout=180, check=True)
        pages = sorted(Path(tmp).glob("p*.png"))
        return "\n".join(_tesseract(p.read_bytes()) for p in pages)


def ocr_image(data: bytes) -> str:
    """Foto oder Scan als Bild (JPG/PNG): direkt an Tesseract."""
    return _tesseract(data)


def parse(text: str) -> dict:
    """Findet Marker in einem Laborbefund. Gibt Werte (schon umgerechnet), das Datum und nicht erkannte Zeilen zurück."""
    found: dict[str, dict] = {}
    for raw in text.splitlines():
        line = raw.replace(" ", " ").strip()
        if len(line) < 3 or len(line) > 200:
            continue
        for m in M:
            if m.key in found:
                continue
            mt = re.search(m.alias, line, re.I)
            if not mt:
                continue
            rest = line[mt.end():]
            nm = re.search(NUM + r"(?:\s*(\S+))?", rest)
            if not nm:
                continue
            try:
                v = _f(nm.group(1))
            except ValueError:
                continue
            unit = (nm.group(2) or "").strip().strip(",;()[]")
            if not re.search(r"[a-zA-Zµμ%]", unit) or unit.lower() in ("bis", "und", "h", "uhr", "n", "l", "h+", "-", "+"):
                unit = ""
            if m.key == "lymph_pct" and unit and "%" not in unit:
                continue
            x = _convert(m, v, unit)
            if x is None:
                continue
            ref = re.search(r"(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)", rest[nm.end():])
            found[m.key] = {"key": m.key, "label": m.label, "value": round(x, 3), "unit": m.unit, "raw": line,
                            "raw_value": nm.group(1).strip(), "raw_unit": unit, "ref_text": ref.group(0) if ref else None}
            break
    d = None
    ctx = re.search(r"(entnahme|abnahme|eingang|probe|befund|datum)[^\n]{0,40}?" + DATE_RE.pattern, text, re.I)
    mt = ctx.groups()[1:] if ctx else (DATE_RE.search(text).groups() if DATE_RE.search(text) else None)
    if mt:
        dd, mm, yy = (int(x) for x in mt)
        yy = yy + 2000 if yy < 100 else yy
        try:
            d = date(yy, mm, dd)
            if d > today() or d.year < 1990:
                d = None
        except ValueError:
            d = None
    return {"markers": list(found.values()), "day": (d or today()).isoformat(), "day_detected": d is not None,
            "chars": len(text)}


def save(db: Session, user: User, day: date, values: dict[str, float]) -> int:
    w = Writer(db, user.id, "lab")
    t = day_ts(day)
    n = 0
    for k, v in values.items():
        if k in METRIC and v is not None:
            w.sample(METRIC[k], t, float(v))
            n += 1
    w.flush_samples()
    db.commit()
    return n


def remove_day(db: Session, user: User, day: date) -> None:
    t = day_ts(day)
    db.execute(delete(Sample).where(Sample.user_id == user.id, Sample.source == "lab", Sample.ts >= t - timedelta(hours=13), Sample.ts < t + timedelta(hours=12)))
    db.commit()


def history(db: Session, user: User) -> dict[str, list]:
    rows = db.execute(select(Sample.metric, Sample.ts, Sample.value).where(Sample.user_id == user.id, Sample.source == "lab").order_by(Sample.ts)).all()
    out: dict[str, list] = {}
    inv = {v: k for k, v in METRIC.items()}
    for metric, ts, v in rows:
        if metric in inv:
            out.setdefault(inv[metric], []).append({"day": ts.date().isoformat(), "value": v})
    return out


def status(m: Marker, v: float, sex: str) -> str:
    lo, hi = _rng(m.ref, sex)
    if lo is not None and v < lo:
        return "low"
    if hi is not None and v > hi:
        return "high"
    o = _rng(m.opt, sex) if m.opt else None
    if o and ((o[0] is not None and v < o[0]) or (o[1] is not None and v > o[1])):
        return "ok"  # im Referenzbereich, aber nicht im Zielbereich
    return "optimal"


def phenoage(vals: dict, age: float) -> float | None:
    """Levine et al. 2018 (Aging): biologisches Alter aus 9 Blutwerten und dem Alter."""
    need = ["albumin", "creatinine", "lab_glucose", "crp", "lymph_pct", "mcv", "rdw", "alp", "wbc"]
    if not all(vals.get(k) is not None for k in need):
        return None
    alb = vals["albumin"] * 10  # g/L
    cre = vals["creatinine"] / 0.01131  # µmol/L
    glu = vals["lab_glucose"] / 18.016  # mmol/L
    crp = max(vals["crp"], 0.01) / 10  # mg/dL
    xb = (-19.907 - 0.0336 * alb + 0.0095 * cre + 0.1953 * glu + 0.0954 * math.log(crp) - 0.0120 * vals["lymph_pct"]
          + 0.0268 * vals["mcv"] + 0.3306 * vals["rdw"] + 0.00188 * vals["alp"] + 0.0554 * vals["wbc"] + 0.0804 * age)
    mort = 1 - math.exp(-math.exp(xb) * (math.exp(120 * 0.0076927) - 1) / 0.0076927)
    if not 0 < mort < 1:
        return None
    return 141.50225 + math.log(-0.00553 * math.log(1 - mort)) / 0.090165


def _body(db: Session, user: User) -> dict:
    """Aktuelle Körper- und Trainingswerte für die Verknüpfung."""
    from .scores import Context
    t = today()
    out = {}
    for k in ["resting_hr", "hrv", "sleep_duration", "steps", "body_fat", "weight", "vo2max", "protein", "bmi", "waist"]:
        s = daily_series(db, user, k, t - timedelta(days=60), t)
        if s:
            vals = [r["value"] for r in s[-30:]]
            out[k] = sorted(vals)[len(vals) // 2]
            if k in ("resting_hr", "hrv") and len(s) >= 20:
                base = sorted(r["value"] for r in s[:-7])
                out[k + "_base"] = base[len(base) // 2] if base else None
    try:
        ctx = Context(db, user, t - timedelta(days=40), t)
        out["acwr"] = ctx.acwr(t - timedelta(days=1))
        out["load7"] = sum(ctx.load(t - timedelta(days=i))["load"] for i in range(1, 8))
        out["hard_recent"] = max((ctx.load(t - timedelta(days=i))["load"] for i in range(0, 3)), default=0)
    except Exception:  # noqa: BLE001
        pass
    return out


def links(latest: dict, sex: str, body: dict, age: float | None, lab_day: date | None) -> list[dict]:
    """Verknüpfungen zwischen Blutwerten und Körperdaten – mit Handlungsempfehlung."""
    v = {k: x["value"] for k, x in latest.items()}
    out = []

    def add(kind, title, text, advice, keys):
        out.append({"type": kind, "title": title, "text": text, "advice": advice, "markers": keys})

    fer, hb = v.get("ferritin"), v.get("hemoglobin")
    if fer is not None and fer < 50:
        extra = []
        if body.get("load7", 0) > 300:
            extra.append("dein Trainingsumfang ist hoch (Eisen geht über Schweiß und Muskelarbeit verloren)")
        if body.get("resting_hr") and body.get("resting_hr_base") and body["resting_hr"] > body["resting_hr_base"] + 2:
            extra.append("dein Ruhepuls ist zuletzt gestiegen")
        add("warn" if fer < 30 else "tip", f"Eisenspeicher niedrig (Ferritin {round(fer)})",
            "Niedrige Eisenspeicher senken die Ausdauerleistung und verlangsamen die Erholung, lange bevor eine Blutarmut sichtbar ist"
            + (f"; zudem {' und '.join(extra)}." if extra else "."),
            "Eisenreich essen (rotes Fleisch, Hülsenfrüchte, Haferflocken) mit Vitamin C, Kaffee/Tee nicht zu den Mahlzeiten. Ein Präparat nur nach Rücksprache mit der Ärztin – Kontrolle in 8–12 Wochen.",
            ["ferritin"] + (["hemoglobin"] if hb else []))
    if fer is not None and fer > 300 and v.get("crp", 0) > 3:
        add("tip", "Ferritin hoch bei Entzündung", "Ferritin steigt bei Entzündungen mit an – der Eisenspeicher ist dann schwer zu beurteilen.",
            "Ferritin wiederholen, wenn das CRP wieder normal ist.", ["ferritin", "crp"])
    vd = v.get("vitd")
    if vd is not None and vd < 30:
        month = (lab_day or today()).month
        add("warn" if vd < 20 else "tip", f"Vitamin D {'Mangel' if vd < 20 else 'knapp'} ({round(vd)} ng/ml)",
            "Vitamin D ist wichtig für Muskelkraft, Knochen und Abwehr." + (" Im Winterhalbjahr bildet die Haut in Deutschland praktisch keins." if month in (10, 11, 12, 1, 2, 3) else ""),
            "Üblich sind 1000–2000 IE Vitamin D3 pro Tag im Winter; bei deutlichem Mangel die Dosis ärztlich festlegen lassen und nach 3 Monaten kontrollieren.", ["vitd"])
    crp = v.get("crp")
    if crp is not None and crp > 3:
        low_hrv = body.get("hrv") and body.get("hrv_base") and body["hrv"] < body["hrv_base"] * 0.92
        add("warn", f"Entzündung (CRP {crp:.1f} mg/l)".replace(".", ","),
            "Ein erhöhter Entzündungswert" + (" passt zu deiner zuletzt gesunkenen HRV" if low_hrv else "") + " – häufig ein Infekt oder eine sehr harte Belastung in den Tagen vor der Blutabnahme.",
            "Keine intensiven Einheiten, bis der Wert normal ist; bei Fieber oder anhaltend erhöhtem Wert ärztlich abklären.", ["crp"])
    elif crp is not None and crp < 1:
        add("good", "Kaum Entzündung", "CRP unter 1 mg/l – günstig für Herz und Gefäße.", None, ["crp"])
    glu = v.get("lab_glucose")
    meta_bad = [k for k, lim in (("hba1c", 5.6), ("lab_glucose", 99), ("trig", 150), ("insulin", 15)) if v.get(k) is not None and v[k] > lim]
    if meta_bad:
        bits = []
        if body.get("steps") and body["steps"] < 7000:
            bits.append(f"wenig Alltagsbewegung (~{round(body['steps']):,} Schritte)".replace(",", "."))
        if body.get("body_fat") and body["body_fat"] > (30 if sex == "f" else 22):
            bits.append(f"Körperfett {round(body['body_fat'])} %")
        add("warn", "Zuckerstoffwechsel belastet", "Mehrere Werte deuten auf eine beginnende Insulinresistenz"
            + (f"; dazu passen {' und '.join(bits)}." if bits else "."),
            "Am wirksamsten: täglich 8000+ Schritte, 2× pro Woche Krafttraining, 10 min Gehen nach dem Essen, weniger Zucker und Weißmehl. Kontrolle in 3 Monaten.", meta_bad)
    if v.get("insulin") is not None and glu is not None:
        homa = v["insulin"] * glu / 405
        if homa > 2:
            add("tip", f"HOMA-Index {homa:.1f}".replace(".", ","), "Der HOMA-Index aus Nüchtern-Insulin und -Zucker liegt über 2 – die Zellen sprechen schlechter auf Insulin an.",
                "Bewegung nach den Mahlzeiten und Krafttraining verbessern die Insulinwirkung schnell.", ["insulin", "lab_glucose"])
    ldl, apob = v.get("ldl"), v.get("apob")
    if (ldl is not None and ldl > 116) or (apob is not None and apob > 100):
        fit = body.get("vo2max")
        add("tip", "Blutfette erhöht", f"{'LDL ' + str(round(ldl)) + ' mg/dl' if ldl else ''}{' · ' if ldl and apob else ''}{'ApoB ' + str(round(apob)) if apob else ''}. "
            "Das LDL wirkt über Jahrzehnte auf die Gefäße – entscheidend ist die Summe der Jahre."
            + (f" Deine gute Fitness (VO₂max {round(fit)}) senkt das Gesamtrisiko deutlich, ersetzt aber keine niedrigeren Blutfette." if fit and fit > 45 else ""),
            "Weniger gesättigte Fette (Butter, Wurst, Käse), mehr Ballaststoffe (Hafer, Hülsenfrüchte), Nüsse; Lipoprotein(a) einmal bestimmen lassen. Mit der Hausärztin das persönliche Risiko besprechen.",
            [k for k in ("ldl", "apob") if v.get(k) is not None])
    hdl = v.get("hdl")
    if hdl is not None and hdl >= 60:
        add("good", "Hohes HDL", "Ein hohes HDL passt zu regelmäßigem Ausdauertraining.", None, ["hdl"])
    ck = v.get("ck")
    if ck is not None and ck > (170 if sex == "f" else 190):
        hard = body.get("hard_recent", 0) > 60
        add("tip", f"CK erhöht ({round(ck)} U/l)", "Die Kreatinkinase zeigt Muskelarbeit." + (" Du hast kurz vor der Blutabnahme hart trainiert – das erklärt den Wert meist vollständig." if hard else ""),
            "Für eine aussagekräftige Messung 3 Tage vorher kein hartes Training; nur bei sehr hohen Werten (> 1000) oder dunklem Urin ärztlich abklären.", ["ck"])
    for k in ("ast", "alt", "ggt"):
        m = BY_KEY[k]
        if v.get(k) is not None and v[k] > _rng(m.ref, sex)[1]:
            muscle = k == "ast" and ck and ck > 300
            add("tip", f"{m.label} erhöht", "Erhöht" + (" – zusammen mit der hohen CK wahrscheinlich aus den Muskeln" if muscle else "; häufigste Ursachen sind Fettleber und Alkohol")
                + (f", dein Körperfett liegt bei {round(body['body_fat'])} %." if body.get("body_fat") and not muscle else "."),
                "Alkohol reduzieren, Bauchfett senken; nach 4–6 Wochen kontrollieren lassen.", [k] + (["ck"] if muscle else []))
            break
    cr = v.get("creatinine")
    if cr is not None and cr > _rng(BY_KEY["creatinine"].ref, sex)[1]:
        add("tip", "Kreatinin erhöht", "Viel Muskelmasse, Kreatin-Präparate, eine eiweißreiche Mahlzeit oder hartes Training vor der Messung erhöhen den Wert ohne Nierenproblem.",
            "Wenn nichts davon zutrifft: Cystatin C bestimmen lassen, das ist muskelunabhängig.", ["creatinine"])
    tsh = v.get("tsh")
    if tsh is not None and not 0.4 <= tsh <= 4.0:
        rhr = body.get("resting_hr")
        add("warn", f"TSH {'erhöht' if tsh > 4 else 'erniedrigt'}",
            ("Passt zu einer Unterfunktion: Müdigkeit, Frieren, Gewichtszunahme." if tsh > 4 else "Passt zu einer Überfunktion: Unruhe, Gewichtsverlust, hoher Puls.")
            + (f" Dein Ruhepuls liegt bei {round(rhr)} bpm." if rhr else ""),
            "fT3/fT4 und Schilddrüsen-Antikörper bestimmen lassen.", ["tsh"])
    te = v.get("testosterone")
    if te is not None and sex != "f" and te < 3.5:
        bits = []
        if body.get("sleep_duration") and body["sleep_duration"] < 420:
            bits.append(f"kurzer Schlaf ({round(body['sleep_duration'] / 60, 1)} h)".replace(".", ","))
        if body.get("acwr") and body["acwr"] > 1.3:
            bits.append("stark gestiegene Trainingsbelastung")
        add("tip", "Testosteron eher niedrig", "Schlafmangel, Energiedefizit und sehr hoher Trainingsumfang senken Testosteron" + (f" – bei dir: {', '.join(bits)}." if bits else "."),
            "7–9 h schlafen, genug essen (kein großes Kaloriendefizit), Vitamin D auffüllen; morgens nüchtern nachmessen.", ["testosterone"])
    if hb is not None and hb < _rng(BY_KEY["hemoglobin"].ref, sex)[0]:
        add("warn", "Hämoglobin niedrig", "Weniger Sauerstofftransport: höherer Puls bei gleicher Leistung, schnellere Ermüdung.",
            "Eisen, B12 und Folsäure bestimmen lassen (falls nicht im Befund) und ärztlich abklären.", ["hemoglobin"])
    b12 = v.get("b12")
    if b12 is not None and b12 < 300:
        add("tip", "Vitamin B12 knapp", "Unter 300 pg/ml kann schon ein funktioneller Mangel bestehen (Müdigkeit, Konzentration).",
            "Holo-Transcobalamin bestimmen lassen; bei pflanzlicher Ernährung B12 ergänzen.", ["b12"])
    order = {"warn": 0, "tip": 1, "good": 2}
    out.sort(key=lambda x: order[x["type"]])
    return out


def supplement_links(db: Session, user: User, latest: dict) -> list[dict]:
    """Blutwerte und eingenommene Supplements zusammen betrachten."""
    from . import supplements as SP
    from .models import Habit
    mine = {(h.supplement or {}).get("key"): h for h in db.scalars(select(Habit).where(Habit.user_id == user.id, Habit.archived.isnot(True))) if h.supplement}
    out = []
    pairs = [("vitd", "vitd", 30, 60), ("b12", "b12", 400, 900), ("iron", "ferritin", 50, 150), ("magnesium", "magnesium", 0.85, 1.05), ("folate", "folate", 4, 20)]
    for sk, lk, lo, hi in pairs:
        if lk not in latest:
            continue
        v = latest[lk]["value"]
        name = SP.BY_KEY[sk].label
        if sk in mine and v > hi:
            out.append({"type": "tip", "title": f"{name}: Wert hoch trotz/wegen Einnahme", "text": f"Du nimmst {name} und der Wert liegt bei {v:g} – über dem Zielbereich.",
                        "advice": "Dosis senken oder pausieren und in 2–3 Monaten neu messen.", "markers": [lk]})
        elif sk in mine and v < lo:
            out.append({"type": "tip", "title": f"{name}: trotz Einnahme niedrig", "text": f"Der Wert ({v:g}) ist noch unter dem Ziel – Dosis, Regelmäßigkeit oder Aufnahme prüfen ({SP.BY_KEY[sk].how})",
                        "advice": "Regelmäßig abhaken hilft zu sehen, ob es an der Einnahme liegt.", "markers": [lk]})
        elif sk in mine:
            out.append({"type": "good", "title": f"{name} wirkt", "text": f"Mit Einnahme im Zielbereich ({v:g}).", "advice": None, "markers": [lk]})
    return out


def overview(db: Session, user: User) -> dict:
    sex = user.sex or "m"
    hist = history(db, user)
    t = today()
    age = (t.year - user.birth_year) if user.birth_year else None
    latest, markers = {}, []
    for m in M:
        h = hist.get(m.key)
        if not h:
            continue
        cur = h[-1]
        prev = h[-2] if len(h) > 1 else None
        st = status(m, cur["value"], sex)
        lo, hi = _rng(m.ref, sex)
        opt = _rng(m.opt, sex) if m.opt else None
        latest[m.key] = cur
        markers.append({"key": m.key, "metric": METRIC[m.key], "label": m.label, "unit": m.unit, "group": m.group, "value": cur["value"], "day": cur["day"],
                        "prev": prev, "status": st, "ref": [lo, hi], "opt": list(opt) if opt else None, "what": m.what,
                        "note": m.low if st == "low" else m.high if st == "high" else "", "history": h, "decimals": m.decimals})
    days = sorted({x["day"] for h in hist.values() for x in h}, reverse=True)
    last_day = date.fromisoformat(days[0]) if days else None
    body = _body(db, user) if markers else {}
    pheno = None
    if age and last_day:
        vals = {k: x["value"] for k, x in latest.items() if date.fromisoformat(x["day"]) >= last_day - timedelta(days=60)}
        p = phenoage(vals, age - (t - last_day).days / 365)
        if p:
            pheno = {"value": round(p, 1), "age": round(age - (t - last_day).days / 365, 1), "day": last_day.isoformat()}
    missing_pheno = [BY_KEY[k].label for k in ["albumin", "creatinine", "lab_glucose", "crp", "lymph_pct", "mcv", "rdw", "alp", "wbc"] if k not in latest]
    try:
        extra = supplement_links(db, user, latest)
    except Exception:  # noqa: BLE001
        extra = []
    return {"markers": markers, "groups": GROUPS, "reports": days, "links": links(latest, sex, body, age, last_day) + extra, "phenoage": pheno,
            "phenoage_missing": missing_pheno, "catalog": [{"key": m.key, "label": m.label, "unit": m.unit, "group": m.group} for m in M]}
