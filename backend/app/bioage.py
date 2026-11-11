"""Biologisches Alter aus allen verfügbaren Messwerten.

Ansatz (wie bei Phänotyp-Altern-Modellen, z. B. Levine 2018 „PhenoAge“): Jeder Messwert verändert laut großen
Kohortenstudien das Sterberisiko um einen Faktor (Hazard Ratio, HR). Das Risiko steigt mit dem Alter etwa um 8–9 %
pro Jahr (Gompertz-Gesetz, Verdopplung etwa alle 8 Jahre). Ein Messwert mit HR 1,09 entspricht damit grob einem
Jahr „mehr“, HR 0,92 einem Jahr „weniger“:  Jahre = ln(HR) / 0,085.

Weil viele Werte miteinander zusammenhängen (Fitness senkt den Ruhepuls und steigert die HRV), wird die Summe um
25 % gedämpft, jeder einzelne Beitrag ist begrenzt und das Ergebnis höchstens ±15 Jahre vom tatsächlichen Alter
entfernt. Es ist eine Schätzung zur Orientierung, keine medizinische Diagnose: Blutwerte (die genauesten Marker)
fehlen in Wearable-Daten.

Quellen der Effektgrößen:
- VO₂max: Kodama et al. 2009 (JAMA), je 1 MET (3,5 ml/kg/min) mehr ≈ 13 % weniger Sterblichkeit; Normwerte nach Alter
  und Geschlecht angelehnt an die HUNT-Fitnessstudie (Loe et al. 2013; „Fitnessalter“ nach Nes et al. 2014).
- Ruhepuls: Zhang et al. 2016 (CMAJ), je 10 Schläge/min ≈ +9 % Sterblichkeit.
- HRV: Hillebrand et al. 2013 (Europace), niedrigste gegenüber höchster HRV ≈ +40 % Herz-Kreislauf-Risiko.
- Schritte: Paluch et al. 2022 (Lancet Public Health), Banach et al. 2023: je 1000 Schritte ≈ 12–15 % weniger, Plateau ab ~10 000.
- Training: Lee et al. 2022 (Circulation), 150–300 min Bewegung/Woche ≈ 20 % weniger, darüber kaum zusätzlicher Nutzen.
- Schlafdauer: Cappuccio et al. 2010 (Sleep), < 6 h ≈ +12 %, lange Schlafdauer ebenfalls erhöht (U-Kurve, Optimum 7–8 h).
- Schlafregelmäßigkeit: Windred et al. 2024 (Sleep), unregelmäßiger Schlaf ≈ +20–50 %.
- BMI: Global BMI Mortality Collaboration 2016 (Lancet), je 5 Punkte über 25 ≈ +31 %.
- Taillenumfang: Jayedi et al. 2020 (BMJ), je 10 cm ≈ +11 %.
- Blutdruck: Lewington et al. 2002 (Lancet), deutlicher Anstieg ab 115–120 mmHg systolisch.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Activity, SleepSession, User
from .store import daily_series
from .timeutil import today

GOMPERTZ = 0.085  # ln(Risiko) pro Lebensjahr
OVERLAP = 0.75  # Dämpfung, weil Messwerte zusammenhängen
CAP_FACTOR = 8.0  # Jahre je Messwert höchstens
CAP_TOTAL = 15.0

# Mittlere VO₂max (ml/kg/min) nach Alter, angelehnt an HUNT (Loe et al. 2013)
VO2_NORM = {"m": [(20, 54.4), (30, 49.4), (40, 46.7), (50, 42.6), (60, 39.0), (70, 34.9), (80, 30.5)],
            "f": [(20, 43.0), (30, 40.0), (40, 38.4), (50, 34.9), (60, 31.6), (70, 28.4), (80, 25.0)]}
# Typische nächtliche HRV (RMSSD, ms) von Wearables nach Alter (Mittel aus veröffentlichten Bevölkerungsdaten)
HRV_NORM = [(20, 70), (30, 55), (40, 44), (50, 36), (60, 30), (70, 26), (80, 23)]
METRICS = ["vo2max", "resting_hr", "hrv", "steps", "sleep_duration", "weight", "bmi", "body_fat", "waist", "bp_systolic"]


def _interp(table, x):
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def _inverse(table, y):
    """Alter, zu dem der Normwert y passt (Tabelle fällt mit dem Alter)."""
    if y >= table[0][1]:
        return table[0][0] - (y - table[0][1]) / ((table[0][1] - table[1][1]) / (table[1][0] - table[0][0]))
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if y >= y1:
            return x0 + (y0 - y) * (x1 - x0) / (y0 - y1)
    (x0, y0), (x1, y1) = table[-2], table[-1]
    return x1 + (y1 - y) * (x1 - x0) / (y0 - y1)


def years(ln_hr: float) -> float:
    return max(-CAP_FACTOR, min(CAP_FACTOR, ln_hr / GOMPERTZ))


class Data:
    """Alle benötigten Tageswerte einmal geladen; Fenster werden daraus geschnitten (schnell für den Verlauf)."""

    def __init__(self, db: Session, user: User, start: date, end: date):
        self.series = {}
        for m in METRICS:
            self.series[m] = {date.fromisoformat(r["day"]): r["value"] for r in daily_series(db, user, m, start, end)}
        acts = db.execute(select(Activity.day, Activity.sport, Activity.moving_s, Activity.duration_s).where(
            Activity.user_id == user.id, Activity.duplicate_of.is_(None), Activity.day >= start, Activity.day <= end)).all()
        self.minutes: dict[date, float] = {}
        for d, sport, mv, du in acts:
            m = (mv or du or 0) / 60
            if sport == "walk":
                m *= 0.5  # zügiges Gehen zählt, aber nicht voll
            self.minutes[d] = self.minutes.get(d, 0) + min(m, 360)
        rows = db.execute(select(SleepSession.day, SleepSession.start, SleepSession.end).where(
            SleepSession.user_id == user.id, SleepSession.day >= start, SleepSession.day <= end)).all()
        self.bedtimes: dict[date, float] = {}
        for d, s, e in rows:
            if s and e and (e - s).total_seconds() > 3 * 3600:  # Nickerchen ignorieren
                h = s.hour + s.minute / 60
                self.bedtimes[d] = h - 24 if h >= 12 else h  # 23:30 → -0,5
        self.first_activity = min(self.minutes) if self.minutes else None

    def window(self, metric: str, end: date, days: int) -> list[float]:
        s = self.series[metric]
        return [v for d, v in s.items() if end - timedelta(days=days) < d <= end]

    def latest(self, metric: str, end: date, days: int) -> float | None:
        s = self.series[metric]
        cand = [(d, v) for d, v in s.items() if end - timedelta(days=days) < d <= end]
        return max(cand)[1] if cand else None


def _f(key, label, value, unit, ln_hr, text, source, n=None, extra=None):
    y = years(ln_hr)
    return {"key": key, "label": label, "value": value, "unit": unit, "years": round(y, 1), "text": text, "source": source,
            "n": n, **(extra or {})}


def factors(data: Data, end: date, age: float, sex: str, height_cm: float | None) -> tuple[list[dict], list[dict]]:
    sex = "f" if sex == "f" else "m"
    out, missing = [], []

    # --- Herz-Kreislauf-Fitness ---
    vo2 = data.latest("vo2max", end, 180)
    if vo2:
        norm = _interp(VO2_NORM[sex], age)
        fit_age = _inverse(VO2_NORM[sex], vo2)
        d = vo2 - norm
        out.append(_f("vo2max", "VO₂max", round(vo2, 1), "ml/kg/min", -0.0398 * d,
                      f"{'Über' if d >= 0 else 'Unter'} dem Schnitt deiner Altersgruppe ({norm:.0f}). Dein Fitnessalter liegt bei etwa {max(18, round(fit_age))} Jahren. "
                      "Ausdauerfitness ist der stärkste einzelne Vorhersagewert für ein langes Leben.",
                      "Kodama 2009; HUNT-Fitnessstudie", extra={"norm": round(norm, 1), "fitness_age": max(18, round(fit_age)),
                                                               "goal": round(vo2 + 3, 1), "goal_text": "+3 ml/kg/min (z. B. 8–12 Wochen Intervalltraining)",
                                                               "goal_years": round(years(-0.0398 * 3) * OVERLAP, 1)}))
    else:
        missing.append({"key": "vo2max", "label": "VO₂max", "how": "Fahrten mit Wattmesser, Läufe mit Pulsmessung oder ein Wert aus Garmin/Apple Health"})

    w = data.window("resting_hr", end, 90)
    if len(w) >= 14:
        rhr = median(w)
        d = rhr - 60
        out.append(_f("resting_hr", "Ruhepuls", round(rhr), "bpm", math.log(1.09) / 10 * d,
                      "Niedriger Ruhepuls zeigt ein effizientes Herz." if d <= 0 else "Ein höherer Ruhepuls hängt mit höherem Herz-Kreislauf-Risiko zusammen; Ausdauertraining und guter Schlaf senken ihn.",
                      "Zhang 2016", len(w), {"norm": 60, "goal": round(rhr - 4), "goal_text": "−4 bpm", "goal_years": round(years(math.log(1.09) / 10 * -4) * OVERLAP, 1)}))
    else:
        missing.append({"key": "resting_hr", "label": "Ruhepuls", "how": "eine Uhr oder ein Ring, der nachts misst"})

    w = data.window("hrv", end, 90)
    if len(w) >= 14:
        hrv = median(w)
        norm = _interp(HRV_NORM, age)
        r = math.log(max(hrv, 5) / norm)
        out.append(_f("hrv", "HRV", round(hrv), "ms", -0.35 * r,
                      f"{'Höher' if r >= 0 else 'Niedriger'} als typisch für dein Alter ({norm:.0f} ms) – entspricht einem HRV-Alter von etwa {max(18, round(_inverse(HRV_NORM, hrv)))} Jahren. "
                      "Die HRV spiegelt, wie gut sich das Nervensystem erholt. Werte verschiedener Geräte sind nur grob vergleichbar.",
                      "Hillebrand 2013", len(w), {"norm": round(norm), "goal": round(hrv * 1.15), "goal_text": "+15 % (Schlaf, Ausdauer, weniger Alkohol)",
                                                  "goal_years": round(years(-0.35 * math.log(1.15)) * OVERLAP, 1)}))
    else:
        missing.append({"key": "hrv", "label": "HRV", "how": "WHOOP, Oura, Garmin oder eine Apple Watch"})

    # --- Bewegung ---
    w = data.window("steps", end, 90)
    if len(w) >= 14:
        st = median(w)
        cl = lambda s: max(2500, min(11000, s))  # noqa: E731
        ln = -0.13 * (cl(st) - 7500) / 1000
        out.append(_f("steps", "Schritte", round(st), "/Tag", ln,
                      "Mehr Alltagsbewegung senkt das Risiko deutlich, bis etwa 10 000 Schritte; darüber kaum zusätzlicher Nutzen." if st < 10000
                      else "Du bist im Bereich, in dem zusätzliche Schritte kaum noch mehr bringen.",
                      "Paluch 2022; Banach 2023", len(w), {"norm": 7500, "goal": round(st + 2000) if st < 9500 else None, "goal_text": "+2000 Schritte am Tag",
                                                           "goal_years": round(years(-0.13 * (cl(st + 2000) - cl(st)) / 1000) * OVERLAP, 1) if st < 9500 else None}))
    else:
        missing.append({"key": "steps", "label": "Schritte", "how": "Handy (Health Connect) oder Uhr"})

    if data.first_activity and data.first_activity <= end - timedelta(days=28):
        days = min(84, (end - max(data.first_activity, end - timedelta(days=84))).days + 1)
        mins = sum(v for d, v in data.minutes.items() if end - timedelta(days=days) < d <= end) / days * 7
        f = lambda m: -0.24 * min(m, 300) / 300 - 0.04 * min(max(m - 300, 0), 300) / 300  # noqa: E731
        out.append(_f("training", "Training", round(mins), "min/Woche", f(mins) - f(150),
                      "Die WHO empfiehlt 150–300 Minuten Bewegung pro Woche; der größte Effekt kommt von den ersten 150." if mins < 300
                      else "Mehr als 300 Minuten in der Woche – damit holst du das Meiste heraus.",
                      "Lee 2022", None, {"norm": 150, "goal": round(mins + 60) if mins < 300 else None, "goal_text": "+60 min pro Woche",
                                         "goal_years": round(years(f(mins + 60) - f(mins)) * OVERLAP, 1) if mins < 300 else None}))
    else:
        missing.append({"key": "training", "label": "Training", "how": "Aktivitäten von Strava, Garmin, intervals.icu o. Ä."})

    # --- Schlaf ---
    w = data.window("sleep_duration", end, 90)
    if len(w) >= 14:
        h = median(w) / 60
        ln = 0.06 * max(0, 7 - h) * 1.6 + 0.08 * max(0, h - 8.5)
        out.append(_f("sleep", "Schlafdauer", round(h, 1), "h", ln,
                      "Im günstigen Bereich von 7–8,5 Stunden." if ln == 0 else ("Weniger als 7 Stunden Schlaf hängen mit höherem Risiko zusammen." if h < 7
                                                                                  else "Sehr langer Schlaf ist statistisch ebenfalls ungünstig (oft als Zeichen anderer Ursachen)."),
                      "Cappuccio 2010", len(w), {"norm": 7.5, "goal": 7.5 if h < 7 else None, "goal_text": "7–8 h Schlaf",
                                                 "goal_years": round(-years(ln) * OVERLAP, 1) if ln and h < 7 else None}))
    else:
        missing.append({"key": "sleep", "label": "Schlaf", "how": "WHOOP, Oura, Uhr oder Health Connect"})

    bt = [v for d, v in data.bedtimes.items() if end - timedelta(days=60) < d <= end]
    if len(bt) >= 14:
        sd = (sum((x - sum(bt) / len(bt)) ** 2 for x in bt) / (len(bt) - 1)) ** 0.5 * 60  # Minuten
        ln = 0.3 * max(0, min(sd, 120) - 30) / 90 - 0.05 * max(0, 30 - sd) / 30
        out.append(_f("sleep_regular", "Schlafrhythmus", round(sd), "min Streuung", ln,
                      "Du gehst sehr regelmäßig ins Bett – das ist laut neuen Studien fast so wichtig wie die Schlafdauer." if sd <= 30
                      else "Die Einschlafzeit schwankt stark. Regelmäßiger Schlaf senkt das Risiko teils mehr als längerer Schlaf.",
                      "Windred 2024", len(bt), {"norm": 30, "goal": 30 if sd > 45 else None, "goal_text": "Einschlafzeit ±30 min",
                                                "goal_years": round(-years(ln) * OVERLAP, 1) if sd > 45 else None}))

    # --- Körper ---
    bf = data.latest("body_fat", end, 365)
    if bf:
        lo, hi = (18, 30) if sex == "f" else (10, 21)
        ln = 0.025 * max(0, bf - hi) + 0.03 * max(0, lo - 4 - bf)
        out.append(_f("body_fat", "Körperfett", round(bf, 1), "%", ln,
                      f"Im gesunden Bereich ({lo}–{hi} %)." if ln == 0 else f"Über dem gesunden Bereich ({lo}–{hi} %). Viszerales Fett erhöht Entzündungen und Stoffwechselrisiken.",
                      "Padwal 2016; Jayedi 2020", None, {"norm": hi}))
    weight = data.latest("weight", end, 365)
    bmi = data.latest("bmi", end, 365) or (weight / (height_cm / 100) ** 2 if weight and height_cm else None)
    if bmi and not bf:
        ln = 0.054 * max(0, bmi - 25) + 0.08 * max(0, 20 - bmi)
        out.append(_f("bmi", "BMI", round(bmi, 1), "", ln,
                      "Im günstigen Bereich (20–25)." if ln == 0 else "Außerhalb von 20–25. Bei viel Muskelmasse überschätzt der BMI das Risiko – ein Körperfettwert wäre genauer.",
                      "Global BMI Mortality Collaboration 2016", None, {"norm": 22.5}))
    elif not bmi and not bf:
        missing.append({"key": "body", "label": "Gewicht/Körperfett", "how": "Waage (Withings, Garmin, Health Connect) und Körpergröße im Konto"})
    waist = data.latest("waist", end, 365)
    if waist:
        ref = 80 if sex == "f" else 94
        out.append(_f("waist", "Taillenumfang", round(waist), "cm", 0.0104 * max(0, waist - ref),
                      "Im günstigen Bereich." if waist <= ref else f"Über {ref} cm steigt das Risiko, unabhängig vom BMI.", "Jayedi 2020", None, {"norm": ref}))

    w = data.window("bp_systolic", end, 180)
    if len(w) >= 2:
        sbp = median(w)
        ln = math.log(1.2) / 20 * max(0, sbp - 120) - 0.02 * max(0, min(120, 120 - sbp)) / 10
        out.append(_f("bp", "Blutdruck", round(sbp), "mmHg systolisch", ln,
                      "Optimaler Blutdruck." if sbp <= 120 else "Erhöhter Blutdruck ist einer der wichtigsten veränderbaren Risikofaktoren.",
                      "Lewington 2002", len(w), {"norm": 120}))
    else:
        missing.append({"key": "bp", "label": "Blutdruck", "how": "Blutdruckmessgerät mit App (Withings, Omron) oder manuell eintragen"})
    return out, missing


def compute(db: Session, user: User, end: date | None = None, history_months: int = 24) -> dict:
    end = end or today()
    if not user.birth_year:
        return {"ready": False, "reason": "Bitte trage unter Konto → Profil dein Geburtsjahr ein, damit das biologische Alter berechnet werden kann."}
    data = Data(db, user, end - timedelta(days=history_months * 31 + 370), end)
    age = end.year - user.birth_year + (end.timetuple().tm_yday / 366) - 0.5
    fs, missing = factors(data, end, age, user.sex or "m", user.height_cm)
    if len(fs) < 3:
        return {"ready": False, "reason": "Noch zu wenige Messwerte: Es braucht mindestens drei der Bereiche Fitness, Ruhepuls, HRV, Schritte, Schlaf und Körper (je etwa zwei Wochen Daten).",
                "missing": missing, "age": round(age, 1)}
    raw = sum(f["years"] for f in fs)
    delta = max(-CAP_TOTAL, min(CAP_TOTAL, raw * OVERLAP))
    for f in fs:
        f["impact"] = round(f["years"] * OVERLAP, 1)
    fs.sort(key=lambda f: f["impact"])
    weights = {"vo2max": 3, "resting_hr": 2, "hrv": 1.5, "steps": 2, "training": 2, "sleep": 1.5, "body_fat": 1.5, "bmi": 1,
               "waist": 1, "bp": 2, "sleep_regular": 1}
    have = sum(weights.get(f["key"], 1) for f in fs)
    total = sum(weights.values()) - 1  # BMI und Körperfett schließen sich aus
    confidence = round(min(1, have / total), 2)
    levers = sorted([{"key": f["key"], "label": f["label"], "goal": f.get("goal"), "text": f["goal_text"], "years": f["goal_years"]}
                     for f in fs if f.get("goal_years") and f["goal_years"] < -0.05], key=lambda x: x["years"])[:4]

    history = []
    m_end = date(end.year, end.month, 1) - timedelta(days=1)
    for i in range(history_months):
        if data.first_activity is None and not any(data.series[k] for k in METRICS):
            break
        d = m_end
        a = d.year - user.birth_year + (d.timetuple().tm_yday / 366) - 0.5
        f2, _ = factors(data, d, a, user.sex or "m", user.height_cm)
        if len(f2) >= 3:
            history.append({"day": d.isoformat(), "age": round(a, 1),
                            "bio_age": round(a + max(-CAP_TOTAL, min(CAP_TOTAL, sum(x["years"] for x in f2) * OVERLAP)), 1)})
        m_end = date(m_end.year, m_end.month, 1) - timedelta(days=1)
    history.reverse()
    history.append({"day": end.isoformat(), "age": round(age, 1), "bio_age": round(age + delta, 1)})

    return {"ready": True, "age": round(age, 1), "bio_age": round(age + delta, 1), "delta": round(delta, 1),
            "confidence": confidence, "factors": fs, "missing": missing,
            "levers": levers, "history": history, "day": end.isoformat()}
