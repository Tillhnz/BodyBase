"""Supplements: Katalog mit Einnahme-Hinweisen, Tracker (als Gewohnheit), Tagesempfehlung und Wirkungsanalyse.

- Jedes Supplement ist eine Gewohnheit (abhaken, Serien, Jahresübersicht, Abend-Erinnerung) mit Zusatzangaben
  (habit.supplement = {"key", "dose", "unit", "time"}).
- Jede Einnahme wird zusätzlich als Messwert supp_<key> (Menge am Tag) gespeichert. Dadurch tauchen Supplements in
  allen Auswertungen als Einflussfaktor auf (Gesundheitsbild → Statistik, Coach).
- Vitamin D: Empfehlung je Tag nach UV-Index und Sonnenstunden am aktuellen Ort (Open-Meteo, ohne Schlüssel),
  Jahreszeit/Breitengrad und dem letzten Blutwert.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import Habit, HabitLog, Sample, User
from .store import Writer, daily_series, day_ts
from .timeutil import today

log = logging.getLogger("bodybase.supplements")


@dataclass
class Supp:
    key: str
    label: str
    dose: float
    unit: str
    time: str  # morning | noon | evening | any
    how: str  # wie und wann nehmen
    avoid: str  # wann besser nicht / Wechselwirkungen
    why: str
    lab: str | None = None  # passender Blutwert (labs-Kennung)
    outcomes: list = field(default_factory=list)  # Messwerte, auf die eine Wirkung plausibel ist


CATALOG = [
    Supp("vitd", "Vitamin D3", 1000, "IE", "noon", "Zu einer Mahlzeit mit etwas Fett (fettlöslich), am besten morgens oder mittags.",
         "Nicht dauerhaft hoch dosieren ohne Blutwert; bei Werten über 60 ng/ml pausieren. Mit Vitamin K2 kombinieren, wenn über 2000 IE.",
         "Knochen, Muskeln, Abwehr – von Oktober bis März bildet die Haut in Deutschland kaum selbst Vitamin D.", "vitd",
         ["hrv", "bb_sleep", "bb_readiness"]),
    Supp("b12", "Vitamin B12", 500, "µg", "morning", "Morgens, unabhängig vom Essen; als Lutschtablette oder Tropfen gut aufgenommen.",
         "Abends eher nicht (kann wach halten). Bei Werten über 900 pg/ml nicht nötig.",
         "Blutbildung und Nerven – wichtig bei pflanzlicher Ernährung.", "b12", ["bb_readiness", "resting_hr"]),
    Supp("magnesium", "Magnesium", 300, "mg", "evening", "Abends, gern als Citrat oder Bisglycinat; kann den Schlaf unterstützen.",
         "Mindestens 2 Stunden Abstand zu Eisen und Zink. Bei Durchfall Dosis senken (vor allem Citrat).",
         "Muskeln und Nerven, viel Schweiß erhöht den Bedarf.", "magnesium", ["bb_sleep", "sleep_deep", "hrv", "resting_hr"]),
    Supp("iron", "Eisen", 50, "mg", "morning", "Morgens nüchtern mit Vitamin C (z. B. O-Saft), am besten nur jeden zweiten Tag – das wird besser aufgenommen.",
         "Nicht mit Kaffee, Tee, Milch, Calcium oder Magnesium; nicht in den Stunden nach hartem Training (das Hormon Hepcidin blockiert die Aufnahme); nicht bei Infekt oder Ferritin über 100.",
         "Füllt die Eisenspeicher – nur bei nachgewiesenem Mangel nehmen.", "ferritin", ["resting_hr", "bb_readiness", "hrv"]),
    Supp("zinc", "Zink", 10, "mg", "evening", "Abends oder mit einer kleinen Mahlzeit; als Kur bei Infekten.",
         "Nicht dauerhaft über 25 mg; Abstand zu Eisen und Calcium. Nicht nüchtern, wenn dir übel wird.", "Abwehr, Haut, Testosteron.",
         None, ["hrv", "resting_hr"]),
    Supp("omega3", "Omega-3 (EPA/DHA)", 1000, "mg", "any", "Zu einer Mahlzeit mit Fett.",
         "Vor Operationen pausieren (blutverdünnend).", "Herz, Gefäße, Entzündungen – wenn du selten fetten Fisch isst.", None,
         ["hrv", "resting_hr"]),
    Supp("creatine", "Kreatin", 5, "g", "any", "Täglich, auch an Ruhetagen; der Zeitpunkt ist egal (gern nach dem Training). Ausreichend trinken.",
         "Erhöht das Gewicht leicht (Wasser in den Muskeln) und den Kreatininwert im Blutbild – das ist kein Nierenproblem.",
         "Mehr Kraft und Muskelmasse, gut untersucht.", "creatinine", ["weight", "bb_readiness"]),
    Supp("vitc", "Vitamin C", 500, "mg", "morning", "Zusammen mit Eisen nehmen, das verbessert die Aufnahme.",
         "Hohe Dosen direkt nach dem Training können Trainingsanpassungen dämpfen.", "Abwehr, Eisenaufnahme.", None, ["hrv"]),
    Supp("folate", "Folsäure", 400, "µg", "morning", "Morgens, gern mit B12 zusammen.", "Nicht hoch dosiert ohne B12-Wert (kann einen B12-Mangel verdecken).",
         "Blutbildung und Zellteilung.", "folate", []),
    Supp("melatonin", "Melatonin", 0.5, "mg", "evening", "30–60 Minuten vor dem Schlafen, niedrig dosiert; vor allem gegen Jetlag.",
         "Nicht dauerhaft und nicht zusammen mit Alkohol; macht am nächsten Morgen manchmal benommen.", "Einschlafen, Jetlag.", None,
         ["bb_sleep", "sleep_duration", "sleep_deep", "hrv"]),
    Supp("electrolytes", "Elektrolyte", 1, "Portion", "any", "Bei langen Einheiten (über 90 min), Hitze oder viel Schweiß während und nach dem Training.",
         "An ruhigen Tagen ohne viel Schweiß nicht nötig (zusätzliches Salz).", "Ersetzt Natrium und Kalium aus dem Schweiß.", "sodium",
         ["bb_readiness", "resting_hr"]),
    Supp("protein", "Proteinpulver", 30, "g", "any", "Wenn du mit dem Essen nicht auf 1,6 g Eiweiß pro kg kommst, gern nach dem Training oder als Snack.",
         "Kein Muss, wenn die Ernährung reicht.", "Muskelaufbau und Erholung.", None, ["weight", "bb_readiness"]),
]
BY_KEY = {s.key: s for s in CATALOG}
TIME_LABEL = {"morning": "morgens", "noon": "mittags", "evening": "abends", "any": "jederzeit"}


def _register() -> None:
    from . import metrics as MT
    MT.CATEGORIES.setdefault("supplements", "Supplements")
    for s in CATALOG:
        MT.METRICS.setdefault(f"supp_{s.key}", MT.Metric(f"supp_{s.key}", s.label, s.unit, "supplements", "sum", 1 if s.dose < 10 else 0, None, 0, 1e6))


_register()


def info(s: Supp) -> dict:
    return {"key": s.key, "label": s.label, "dose": s.dose, "unit": s.unit, "time": s.time, "time_label": TIME_LABEL[s.time],
            "how": s.how, "avoid": s.avoid, "why": s.why, "lab": s.lab}


# ---------- Messwerte aus dem Tracker ----------

def sync_sample(db: Session, h: Habit, d: date, value: float | None) -> None:
    """Einnahme als Messwert supp_<key> spiegeln (für Auswertungen)."""
    sp = h.supplement or {}
    key = sp.get("key")
    if key not in BY_KEY:
        return
    metric = f"supp_{key}"
    t = day_ts(d)
    db.execute(delete(Sample).where(Sample.user_id == h.user_id, Sample.metric == metric, Sample.source == "habits",
                                    Sample.ts >= t - timedelta(hours=13), Sample.ts < t + timedelta(hours=12)))
    if value and value > 0:
        dose = float(sp.get("dose") or BY_KEY[key].dose)
        w = Writer(db, h.user_id, "habits")
        w.sample(metric, t, dose * (value if h.kind == "count" else 1))
        w.flush_samples()
    db.commit()


def resync(db: Session, h: Habit) -> None:
    for row in db.scalars(select(HabitLog).where(HabitLog.habit_id == h.id)):
        sync_sample(db, h, row.day, row.value)


# ---------- Ort und Wetter ----------

_weather: dict = {}
_wlock = threading.Lock()


def location(db: Session, user: User) -> dict | None:
    loc = (user.prefs or {}).get("location")
    if loc and loc.get("lat") is not None:
        return {**loc, "source": loc.get("source", "set")}
    # sonst: wo die meisten Aktivitäten starten (Zuhause)
    try:
        from . import explorer as E
        acts = E._load(db, user)
        if acts:
            from collections import Counter
            c = Counter((round(a["start"][0], 1), round(a["start"][1], 1)) for a in acts)
            (lat, lon), _ = c.most_common(1)[0]
            return {"lat": lat, "lon": lon, "name": "Zuhause (aus deinen Strecken)", "source": "activities"}
    except Exception:  # noqa: BLE001
        pass
    return None


def weather(lat: float, lon: float) -> dict | None:
    """UV-Index, Sonnenstunden und Temperatur für heute und morgen (Open-Meteo), eine Stunde zwischengespeichert."""
    k = (round(lat, 2), round(lon, 2))
    with _wlock:
        hit = _weather.get(k)
        if hit and time.time() - hit[0] < (3600 if hit[1] else 900):  # Fehlschläge 15 min merken, damit nichts hängt
            return hit[1]
    try:
        r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=6, params={
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 2,
            "daily": "uv_index_max,sunshine_duration,temperature_2m_max,precipitation_sum",
            "hourly": "uv_index"})
        r.raise_for_status()
        j = r.json()
        dd = j["daily"]
        hours = [(t[11:16], u) for t, u in zip(j["hourly"]["time"][:24], j["hourly"]["uv_index"][:24]) if u is not None]
        good = [h for h, u in hours if u >= 3]
        out = {"uv_max": dd["uv_index_max"][0], "sun_h": round((dd["sunshine_duration"][0] or 0) / 3600, 1),
               "temp_max": dd["temperature_2m_max"][0], "rain": dd["precipitation_sum"][0],
               "uv_window": [good[0], good[-1]] if good else None, "tomorrow_uv": dd["uv_index_max"][1]}
    except Exception as e:  # noqa: BLE001
        log.info("Wetter nicht abrufbar: %s", e)
        out = None
    with _wlock:
        _weather[k] = (time.time(), out)
    return out


def _lab(db: Session, user: User, key: str) -> tuple[float, date] | None:
    s = daily_series(db, user, f"lab_{key}", today() - timedelta(days=548), today())
    return (s[-1]["value"], date.fromisoformat(s[-1]["day"])) if s else None


def _vitd(db: Session, user: User, loc: dict | None, w: dict | None) -> dict:
    lab = _lab(db, user, "vitd")
    month = today().month
    lat = abs(loc["lat"]) if loc else 51
    winter = lat > 35 and (month in (10, 11, 12, 1, 2, 3) if (loc or {}).get("lat", 51) >= 0 else month in (4, 5, 6, 7, 8, 9))
    if lab and lab[0] >= 60:
        return {"take": False, "level": "pause", "title": "Pausieren", "text": f"Dein letzter Wert liegt bei {round(lab[0])} ng/ml – der Speicher ist voll. Erst nach einer neuen Messung wieder anfangen."}
    if w and w["uv_max"] is not None and w["uv_max"] >= 3 and w["sun_h"] >= 3:
        mins = max(10, min(40, round(90 / w["uv_max"] / 5) * 5))
        window = f" zwischen {w['uv_window'][0]} und {w['uv_window'][1]} Uhr" if w.get("uv_window") else " mittags"
        low = lab and lab[0] < 20
        return {"take": bool(low), "level": "optional" if not low else "take",
                "title": "Sonne reicht heute" if not low else "Trotz Sonne nehmen",
                "text": (f"UV-Index {w['uv_max']:.0f} und {w['sun_h']:.0f} h Sonne: Etwa {mins} min mit freien Armen und Gesicht{window} bilden rund 1000 IE. "
                         + ("Wenn du das schaffst, kannst du die Tablette heute weglassen." if not low else f"Dein Wert ({round(lab[0])} ng/ml) ist aber zu niedrig – nimm sie trotzdem."))}
    reason = []
    if w and w["uv_max"] is not None:
        reason.append(f"UV-Index heute nur {w['uv_max']:.0f}" + (f", {w['sun_h']:.0f} h Sonne" if w["sun_h"] else ""))
    if winter:
        reason.append("Vitamin-D-Winter: die Sonne steht zu tief, die Haut bildet kaum etwas")
    return {"take": True, "level": "take", "title": "Heute nehmen",
            "text": ("; ".join(reason) or "Wenig Sonne heute") + ". Unter UV-Index 3 entsteht in der Haut praktisch kein Vitamin D."
            + (f" Dein letzter Wert: {round(lab[0])} ng/ml." if lab else "")}


def today_advice(db: Session, user: User, lat: float | None = None, lon: float | None = None, name: str | None = None, want_weather: bool = False) -> dict:
    """Empfehlung für jedes eigene Supplement für heute: nehmen / optional / besser nicht – mit Grund."""
    from . import habits as H
    from .scores import Context
    loc = {"lat": lat, "lon": lon, "name": name or "aktueller Standort", "source": "device"} if lat is not None and lon is not None else location(db, user)
    t = today()
    habits = db.scalars(select(Habit).where(Habit.user_id == user.id, Habit.archived.isnot(True))).all()
    mine = [h for h in habits if (h.supplement or {}).get("key") in BY_KEY]
    need_weather = want_weather or lat is not None or any(h.supplement["key"] in ("vitd", "electrolytes") for h in mine)
    w = weather(loc["lat"], loc["lon"]) if loc and need_weather else None
    try:
        ctx = Context(db, user, t - timedelta(days=3), t)
        load_today = ctx.load(t)["value"] or 0
        long_today = max(((a.duration_s or a.moving_s or 0) for a in ctx.acts.get(t, [])), default=0)
    except Exception:  # noqa: BLE001
        load_today, long_today = 0, 0
    out = []
    for h in mine:
        s = BY_KEY[h.supplement["key"]]
        v = db.scalar(select(HabitLog.value).where(HabitLog.habit_id == h.id, HabitLog.day == t))
        a = {"take": True, "level": "take", "title": f"{TIME_LABEL[(h.supplement.get('time') or s.time)].capitalize()} nehmen", "text": s.how}
        if s.key == "vitd":
            a = _vitd(db, user, loc, w)
        elif s.key == "iron":
            fer, crp = _lab(db, user, "ferritin"), _lab(db, user, "crp")
            yday = db.scalar(select(HabitLog.value).where(HabitLog.habit_id == h.id, HabitLog.day == t - timedelta(days=1)))
            if fer and fer[0] > 100:
                a = {"take": False, "level": "pause", "title": "Nicht nötig", "text": f"Ferritin {round(fer[0])} ng/ml – die Speicher sind voll."}
            elif crp and crp[0] > 5 and (t - crp[1]).days < 14:
                a = {"take": False, "level": "pause", "title": "Pausieren", "text": "Bei Entzündung/Infekt wird Eisen schlecht aufgenommen und kann Bakterien nützen."}
            elif yday:
                a = {"take": False, "level": "optional", "title": "Heute auslassen", "text": "Gestern genommen – jeden zweiten Tag wird Eisen besser aufgenommen (das Hormon Hepcidin bremst sonst)."}
            elif load_today >= 60:
                a = {"take": True, "level": "take", "title": "Vor dem Training nehmen", "text": "Heute hartes Training: Eisen morgens vor dem Training nehmen, nicht danach (Hepcidin)."}
            else:
                a["text"] = s.how
        elif s.key == "electrolytes":
            hot = w and w.get("temp_max") is not None and w["temp_max"] >= 25
            if long_today >= 5400 or hot:
                a = {"take": True, "level": "take", "title": "Heute sinnvoll", "text": ("Lange Einheit heute. " if long_today >= 5400 else "") + (f"Bis {w['temp_max']:.0f} °C heute. " if hot else "") + "Während und nach dem Training."}
            else:
                a = {"take": False, "level": "optional", "title": "Heute nicht nötig", "text": "Keine lange Einheit und keine Hitze."}
        elif s.key == "magnesium":
            a = {"take": True, "level": "take", "title": "Abends nehmen", "text": s.how + (" Hartes Training heute – Magnesium hilft beim Entspannen." if load_today >= 60 else "")}
        elif s.key == "melatonin":
            a = {"take": False, "level": "optional", "title": "Nur bei Bedarf", "text": "Für Jetlag oder einzelne Nächte – nicht als Dauerlösung."}
        elif s.key == "vitc":
            a = {"take": True, "level": "take", "title": "Morgens nehmen", "text": s.how + (" Nicht direkt nach dem harten Training heute." if load_today >= 60 else "")}
        lab = _lab(db, user, s.lab) if s.lab and s.key not in ("vitd", "iron") else None
        if lab and s.key in ("b12", "magnesium", "folate"):
            from . import labs as Lb
            m = Lb.BY_KEY.get(s.lab)
            hi = m and Lb._rng(m.ref, user.sex or "m")[1]
            if hi and lab[0] > hi:
                a = {"take": False, "level": "pause", "title": "Pausieren", "text": f"Dein letzter Wert ({lab[0]:g} {m.unit}) liegt über dem Normbereich."}
        out.append({"habit_id": h.id, **info(s), "dose": h.supplement.get("dose") or s.dose, "unit": h.supplement.get("unit") or s.unit,
                    "time": h.supplement.get("time") or s.time, "taken": bool(v), "advice": a,
                    "streak": H.streak(h, {r.day: r.value for r in db.scalars(select(HabitLog).where(HabitLog.habit_id == h.id, HabitLog.day >= t - timedelta(days=400)))}, t)})
    order = {"morning": 0, "noon": 1, "any": 2, "evening": 3}
    out.sort(key=lambda x: order.get(x["time"], 2))
    return {"location": loc, "weather": w, "items": out, "catalog": [info(s) for s in CATALOG]}


# ---------- Wirkung ----------

def effects(db: Session, user: User) -> list[dict]:
    """Je Supplement: Werte in den 4 Wochen vor dem Start gegenüber der Zeit danach, und Tage mit/ohne Einnahme."""
    from .analysis import _label, _mean, _welch, fmt_metric
    from .metrics import METRICS as MM
    out = []
    t = today()
    habits = db.scalars(select(Habit).where(Habit.user_id == user.id)).all()
    for h in habits:
        key = (h.supplement or {}).get("key")
        if key not in BY_KEY:
            continue
        s = BY_KEY[key]
        first = db.scalar(select(func.min(HabitLog.day)).where(HabitLog.habit_id == h.id))
        if not first:
            continue
        taken = {r for r in db.scalars(select(HabitLog.day).where(HabitLog.habit_id == h.id, HabitLog.value > 0))}
        rows = []
        for m in s.outcomes or ["hrv", "resting_hr", "bb_sleep"]:
            ser = {date.fromisoformat(p["day"]): p["value"] for p in daily_series(db, user, m, first - timedelta(days=42), t)}
            if not ser:
                continue
            before = [v for d, v in ser.items() if first - timedelta(days=28) <= d < first]
            after = [v for d, v in ser.items() if d >= first + timedelta(days=7)]  # erste Woche Eingewöhnung
            row = {"key": m, "label": _label(m), "unit": MM[m].unit if m in MM else ""}
            if len(before) >= 7 and len(after) >= 7:
                diff, d_eff, p = _welch(after, before)
                better = MM[m].better if m in MM else None
                row["before_after"] = {"before": fmt_metric(m, _mean(before)), "after": fmt_metric(m, _mean(after)), "diff": fmt_metric(m, diff, signed=True),
                                       "d": round(d_eff, 2), "p": p, "clear": abs(d_eff) >= 0.3 and p is not None and p < 0.1,
                                       "good": (diff > 0) == (better == "up") if better and abs(d_eff) >= 0.3 else None}
            lag = 1 if m in ("hrv", "resting_hr", "bb_readiness", "bb_sleep", "sleep_duration", "sleep_deep") else 0
            on = [ser[d + timedelta(days=lag)] for d in taken if d + timedelta(days=lag) in ser]
            off = [ser[d + timedelta(days=lag)] for d in ser if d >= first and d - timedelta(days=lag) not in taken and d - timedelta(days=lag) >= first]
            if len(on) >= 5 and len(off) >= 5:
                diff, d_eff, p = _welch(on, off)
                row["on_off"] = {"on": fmt_metric(m, _mean(on)), "off": fmt_metric(m, _mean(off)), "diff": fmt_metric(m, diff, signed=True),
                                 "n_on": len(on), "n_off": len(off), "d": round(d_eff, 2), "clear": abs(d_eff) >= 0.3 and p is not None and p < 0.1}
            if "before_after" in row or "on_off" in row:
                rows.append(row)
        lab = None
        if s.lab:
            series = daily_series(db, user, f"lab_{s.lab}", first - timedelta(days=548), t)
            pre = [p for p in series if date.fromisoformat(p["day"]) < first]
            post = [p for p in series if date.fromisoformat(p["day"]) >= first + timedelta(days=28)]
            if pre or post:
                lab = {"key": s.lab, "before": pre[-1] if pre else None, "after": post[-1] if post else None}
        out.append({"habit_id": h.id, "key": key, "label": s.label, "since": first.isoformat(), "days_taken": len(taken),
                    "days_since": (t - first).days + 1, "rows": rows, "lab": lab})
    return out


def comparisons_for(data) -> list[tuple]:
    """Für analysis.comparisons: (Titel, Tage mit, Tage ohne, Messwerte) je Supplement seit Beginn."""
    out = []
    for key in data.keys:
        if not key.startswith("supp_"):
            continue
        s = BY_KEY.get(key[5:])
        ser = data.series.get(key, {})
        if not s or not ser:
            continue
        first = min(ser)
        days = [d for d in data.days_list() if d >= first]
        on = [d for d in days if ser.get(d, 0) > 0]
        off = [d for d in days if not ser.get(d)]
        outs = [(m, 1 if m in ("hrv", "resting_hr", "bb_readiness", "bb_sleep", "sleep_duration", "sleep_deep") else 0,
                 "nächster Morgen/Nacht" if m in ("hrv", "resting_hr", "bb_readiness", "bb_sleep", "sleep_duration", "sleep_deep") else "am selben Tag")
                for m in (s.outcomes or ["hrv", "resting_hr", "bb_sleep"])]
        out.append((f"{s.label} – mit und ohne Einnahme", "eingenommen", on, "ausgelassen", off, outs))
    return out
