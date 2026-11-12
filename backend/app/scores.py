"""Eigene Tageswerte von BodyBase: Bereitschaft, Auslastung und Schlaf (je 0–100).

Bewusst unabhängig von den Werten der Anbieter (intervals.icu, Oura, WHOOP, Garmin), damit sie für alle Quellen gleich
gerechnet werden und vergleichbar bleiben.

Schlaf      Dauer gegenüber dem Schlafziel (45 %), erholsame Phasen Tief + REM (20 %), Effizienz (15 %) und
            Regelmäßigkeit der Einschlafzeit gegenüber den 7 Nächten davor (20 %).
Auslastung  Trainingslast nach Banister (TRIMP): Minuten × Pulsreserve, exponentiell gewichtet. Ohne Puls wird die
            Pulsreserve je Sportart geschätzt. Schritte außerhalb von Trainings zählen leicht mit. Die Tageslast wird auf
            0–100 abgebildet (100 · (1 − e^(−Last/140))): etwa 30 lockerer Tag, 60 ordentliches Training, 85+ sehr hart.
Bereitschaft  HRV (35 %) und Ruhepuls (20 %) gegenüber deinem eigenen Verlauf der letzten 60 Tage, der Schlafwert der
            Nacht (30 %) und das Verhältnis der Last der letzten 7 Tage zu den 4 Wochen davor (15 %).
            Deutlich erhöhte Atemfrequenz zieht zusätzlich ab (oft ein frühes Krankheitszeichen).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Activity, Sample, SleepSession, User
from .store import Writer, daily_series, day_ts, priority_for, rank
from .timeutil import today, tz, utcnow

METRICS = ("bb_readiness", "bb_load", "bb_sleep")
LOAD_K = 140.0
# geschätzte Pulsreserve (0–1), wenn ein Training keinen Puls hat
SPORT_INTENSITY = {
    "run": 0.72, "ride": 0.62, "swim": 0.65, "row": 0.68, "ski": 0.6, "cardio": 0.7, "strength": 0.5, "climb": 0.55,
    "hike": 0.45, "walk": 0.3, "yoga": 0.2, "team": 0.65, "other": 0.5,
}
STEP_LOAD = 0.002  # Last je Schritt außerhalb von Trainings (10 000 Schritte ≈ 20)


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _weighted(parts: list[dict]) -> float | None:
    w = sum(p["weight"] for p in parts)
    return sum(p["score"] * p["weight"] for p in parts) / w if w else None


def _z(values: list[float], v: float) -> float | None:
    if len(values) < 7:
        return None
    mean = sum(values) / len(values)
    sd = math.sqrt(sum((x - mean) ** 2 for x in values) / len(values))
    return (v - mean) / max(sd, abs(mean) * 0.03, 1e-6)


def load_score(load: float) -> float:
    return 100 * (1 - math.exp(-max(0.0, load) / LOAD_K))


class Context:
    """Lädt alle nötigen Daten einmal und rechnet dann beliebig viele Tage."""

    def __init__(self, db: Session, user: User, start: date, end: date):
        self.user, self.start, self.end = user, start, end
        first = start - timedelta(days=70)
        self.series = {k: {date.fromisoformat(p["day"]): p["value"] for p in daily_series(db, user, k, first, end)}
                       for k in ("hrv", "resting_hr", "steps", "respiratory_rate")}
        goals = (user.prefs or {}).get("goals") or {}
        # Grundbedarf: eigener Wert aus den Einstellungen, sonst nach Alter (Empfehlung der National Sleep Foundation)
        age = (datetime.now().year - user.birth_year) if user.birth_year else 35
        self.sleep_base = float(goals.get("sleep_duration") or (540 if age < 18 else 480 if age < 65 else 450))
        self.sleep_need = self.sleep_base
        self._need: dict[date, dict] = {}
        # Schlaf: je Nacht die bevorzugte Quelle (wie in der Schlafansicht)
        order = priority_for(user, "sleep_duration")
        best: dict[date, SleepSession] = {}
        for r in db.scalars(select(SleepSession).where(SleepSession.user_id == user.id, SleepSession.day >= first,
                                                       SleepSession.day <= end, SleepSession.nap.isnot(True))):
            cur = best.get(r.day)
            if cur is None or rank(order, r.source) < rank(order, cur.source) or \
                    (r.source == cur.source and (r.asleep_min or 0) > (cur.asleep_min or 0)):
                best[r.day] = r
        self.nights = best
        self.acts = defaultdict(list)
        for a in db.scalars(select(Activity).where(Activity.user_id == user.id, Activity.duplicate_of.is_(None),
                                                   Activity.day >= first, Activity.day <= end)):
            self.acts[a.day].append(a)
        # Pulsgrenzen: Ruhepuls als Median, Maximalpuls aus Alter oder dem höchsten gemessenen Wert
        rhr = sorted(self.series["resting_hr"].values())
        self.hr_rest = rhr[len(rhr) // 2] if rhr else 60.0
        age_max = 208 - 0.7 * (datetime.now().year - user.birth_year) if user.birth_year else 190.0
        seen = sorted(a.max_hr for day in self.acts.values() for a in day if a.max_hr and 120 < a.max_hr < 225)
        # dritthöchster gemessener Wert, damit einzelne Messfehler nicht alles verschieben
        self.hr_max = max(age_max, seen[-3]) if len(seen) >= 3 else age_max
        self.female = (user.sex or "").lower().startswith(("f", "w"))
        self._sleep: dict[date, dict | None] = {}
        self._load: dict[date, dict] = {}

    # ---------- Auslastung ----------

    def activity_load(self, a: Activity) -> float:
        minutes = (a.duration_s or a.moving_s or 0) / 60
        if minutes <= 0:
            return 0.0
        if a.avg_hr and self.hr_max > self.hr_rest:
            hrr = _clamp((a.avg_hr - self.hr_rest) / (self.hr_max - self.hr_rest), 0, 1)
        else:
            hrr = SPORT_INTENSITY.get(a.sport or "other", 0.5)
        b, c = (0.86, 1.67) if self.female else (0.64, 1.92)
        return minutes * hrr * b * math.exp(c * hrr)

    def load(self, d: date) -> dict:
        if d in self._load:
            return self._load[d]
        acts = self.acts.get(d, [])
        training = sum(self.activity_load(a) for a in acts)
        walked_in_training = sum((a.duration_s or 0) / 60 * 100 for a in acts if a.sport in ("walk", "hike", "run"))
        steps = max(0.0, (self.series["steps"].get(d) or 0) - walked_in_training)
        total = training + steps * STEP_LOAD
        out = {"value": round(load_score(total)), "load": round(total, 1), "training": round(training, 1),
               "steps": round(steps * STEP_LOAD, 1), "count": len(acts)}
        self._load[d] = out
        return out

    def acwr(self, d: date) -> float | None:
        """Last der 7 Tage bis d im Verhältnis zum Tagesmittel der 28 Tage davor."""
        acute = sum(self.load(d - timedelta(days=i))["load"] for i in range(7)) / 7
        chronic = sum(self.load(d - timedelta(days=i))["load"] for i in range(7, 35)) / 28
        return acute / chronic if chronic >= 5 else None

    # ---------- Schlaf ----------

    def need(self, d: date) -> dict:
        """Dynamischer Schlafbedarf für die Nacht, die am Morgen von d endet.

        Grundbedarf + Belastung am Vortag + ein Teil der Schlafschuld der letzten 7 Nächte
        + Erholungsbedarf (HRV unter, Ruhepuls oder Atemfrequenz über dem eigenen Normalwert). Höchstens +2 h.
        """
        if d in self._need:
            return self._need[d]
        base = self.sleep_base
        parts = [{"key": "base", "label": "Grundbedarf", "min": round(base)}]
        # Belastung: je Belastungspunkt etwa 15 s, höchstens 1 h (ähnlich WHOOP)
        ld = self.load(d - timedelta(days=1))
        extra_load = min(60.0, ld["load"] * 0.25)
        if extra_load >= 3:
            parts.append({"key": "load", "label": "Belastung gestern", "min": round(extra_load),
                          "text": f"Auslastung {ld['value']}"})
        # Schlafschuld: Fehlbetrag der letzten 7 Nächte, davon wird pro Nacht etwa ein Fünftel nachgeholt
        short, nights = 0.0, 0
        for i in range(1, 8):
            n = self.nights.get(d - timedelta(days=i))
            if n and n.asleep_min and n.asleep_min > 60:
                nights += 1
                short += max(0.0, base - n.asleep_min) * (1 - i * 0.08)  # ältere Nächte zählen weniger
        extra_debt = min(45.0, short * 0.2) if nights >= 2 else 0.0
        if extra_debt >= 3:
            parts.append({"key": "debt", "label": "Schlafschuld", "min": round(extra_debt),
                          "text": f"etwa {round(short / 60, 1)} h zu wenig in den letzten {nights} Nächten".replace(".", ",")})
        # Erholung: Vortageswerte gegenüber dem 30-Tage-Median
        extra_rec, why = 0.0, []

        def base_of(key):
            vals = sorted(v for k, v in self.series[key].items() if d - timedelta(days=31) <= k < d - timedelta(days=1))
            return vals[len(vals) // 2] if len(vals) >= 7 else None

        y = d - timedelta(days=1)
        hb, hv = base_of("hrv"), self.series["hrv"].get(y) or self.series["hrv"].get(d)
        if hb and hv and hv < hb * 0.9:
            extra_rec += min(25.0, (1 - hv / hb) * 100)
            why.append(f"HRV {round((1 - hv / hb) * 100)} % unter normal")
        rb, rv = base_of("resting_hr"), self.series["resting_hr"].get(y) or self.series["resting_hr"].get(d)
        if rb and rv and rv > rb + 3:
            extra_rec += min(15.0, (rv - rb - 3) * 4)
            why.append(f"Ruhepuls {round(rv - rb)} bpm erhöht")
        ab, av = base_of("respiratory_rate"), self.series["respiratory_rate"].get(y) or self.series["respiratory_rate"].get(d)
        if ab and av and av > ab + 1:
            extra_rec += 10.0
            why.append("Atemfrequenz erhöht")
        extra_rec = min(30.0, extra_rec)
        if extra_rec >= 3:
            parts.append({"key": "recovery", "label": "Erholung", "min": round(extra_rec), "text": ", ".join(why)})
        total = base + min(120.0, extra_load + extra_debt + extra_rec)
        out = {"need": round(total), "base": round(base), "parts": parts, "custom_base": bool(((self.user.prefs or {}).get("goals") or {}).get("sleep_duration"))}
        self._need[d] = out
        return out

    @staticmethod
    def _bed_minutes(s: SleepSession) -> float:
        """Einschlafzeit als Minuten ab 12 Uhr mittags (Ortszeit), damit 23:30 und 0:30 nah beieinander liegen."""
        local = s.start.replace(tzinfo=timezone.utc).astimezone(tz())
        return ((local.hour - 12) % 24) * 60 + local.minute

    def sleep(self, d: date) -> dict | None:
        if d in self._sleep:
            return self._sleep[d]
        n = self.nights.get(d)
        out = None
        if n and (n.asleep_min or 0) > 60:
            asleep = n.asleep_min
            in_bed = max(asleep, (n.end - n.start).total_seconds() / 60)
            need = self.need(d)["need"]
            ratio = asleep / need
            parts = [{"key": "duration", "label": "Dauer", "weight": 45, "score": _clamp((ratio - 0.5) / 0.5 * 100),
                      "text": f"{int(asleep // 60)}:{int(asleep % 60):02d} h von {int(need // 60)}:{int(need % 60):02d} h Bedarf"}]
            if n.deep_min is not None and n.rem_min is not None:
                share = (n.deep_min + n.rem_min) / asleep
                parts.append({"key": "restorative", "label": "Tief + REM", "weight": 20, "score": _clamp(share / 0.4 * 100),
                              "text": f"{round(share * 100)} % der Schlafzeit"})
            eff = (n.efficiency / 100 if n.efficiency and n.efficiency > 1 else n.efficiency) or (asleep / in_bed if in_bed else None)
            if eff:
                parts.append({"key": "efficiency", "label": "Effizienz", "weight": 15, "score": _clamp((eff - 0.7) / 0.25 * 100),
                              "text": f"{round(eff * 100)} % der Zeit im Bett geschlafen"})
            prev = [self._bed_minutes(self.nights[d - timedelta(days=i)]) for i in range(1, 8) if (d - timedelta(days=i)) in self.nights]
            if len(prev) >= 3:
                prev.sort()
                dev = abs(self._bed_minutes(n) - prev[len(prev) // 2])
                parts.append({"key": "consistency", "label": "Regelmäßigkeit", "weight": 20, "score": _clamp(100 - dev / 1.2),
                              "text": f"{round(dev)} min von deiner üblichen Einschlafzeit"})
            out = {"value": round(_weighted(parts)), "parts": _round_parts(parts), "asleep_min": asleep}
        self._sleep[d] = out
        return out

    # ---------- Bereitschaft ----------

    def readiness(self, d: date) -> dict | None:
        parts = []
        hrv = self.series["hrv"]
        if d in hrv and hrv[d] > 0:
            base = [math.log(v) for k, v in hrv.items() if d - timedelta(days=60) <= k < d and v > 0]
            z = _z(base, math.log(hrv[d]))
            if z is not None:
                parts.append({"key": "hrv", "label": "HRV", "weight": 35, "score": _clamp(65 + z * 18),
                              "text": f"{round(hrv[d])} ms, {_rel(z)}"})
        rhr = self.series["resting_hr"]
        if d in rhr:
            base = [v for k, v in rhr.items() if d - timedelta(days=60) <= k < d]
            z = _z(base, rhr[d])
            if z is not None:
                parts.append({"key": "resting_hr", "label": "Ruhepuls", "weight": 20, "score": _clamp(65 - z * 18),
                              "text": f"{round(rhr[d])} bpm, {_rel(z)}"})
        sl = self.sleep(d)
        if sl:
            parts.append({"key": "sleep", "label": "Schlaf", "weight": 30, "score": sl["value"], "text": f"Schlafwert {sl['value']}"})
        if not parts:
            return None
        ratio = self.acwr(d - timedelta(days=1))
        if ratio is not None:
            parts.append({"key": "load", "label": "Belastung", "weight": 15, "score": _clamp(100 - max(0.0, ratio - 0.9) * 150, 20),
                          "text": f"letzte 7 Tage {ratio:.1f}× so viel wie üblich".replace(".", ",")})
        value = _weighted(parts)
        resp = self.series["respiratory_rate"]
        if d in resp:
            z = _z([v for k, v in resp.items() if d - timedelta(days=60) <= k < d], resp[d])
            if z is not None and z > 2:
                value -= 10
                parts.append({"key": "respiratory_rate", "label": "Atemfrequenz", "weight": 0, "score": 0,
                              "text": f"{resp[d]:.1f}/min, deutlich erhöht (−10)".replace(".", ",")})
        return {"value": round(_clamp(value)), "parts": _round_parts(parts)}

    def target(self, readiness: int | None) -> tuple[int, int]:
        """Sinnvoller Bereich der Auslastung für heute."""
        if readiness is None:
            return 35, 65
        if readiness >= 70:
            return 55, 85
        if readiness >= 45:
            return 35, 65
        return 10, 35


def _rel(z: float) -> str:
    if z > 1:
        return "deutlich über deinem Schnitt"
    if z > 0.3:
        return "über deinem Schnitt"
    if z < -1:
        return "deutlich unter deinem Schnitt"
    if z < -0.3:
        return "unter deinem Schnitt"
    return "wie üblich"


def _round_parts(parts: list[dict]) -> list[dict]:
    return [{**p, "score": round(p["score"])} for p in parts]


def _with_day(v: dict | None, d: date) -> dict | None:
    return {**v, "day": d.isoformat()} if v else None


def today_scores(db: Session, user: User, days: int = 14) -> dict:
    """Werte für heute mit Aufschlüsselung und die letzten Tage für den Verlauf."""
    t = today()
    ctx = Context(db, user, t - timedelta(days=days), t)
    # morgens fehlen oft noch die Werte der Nacht: dann der Stand von gestern (mit Datum gekennzeichnet)
    rd = _with_day(ctx.readiness(t), t) or _with_day(ctx.readiness(t - timedelta(days=1)), t - timedelta(days=1))
    lo, hi = ctx.target(rd["value"] if rd else None)
    load = ctx.load(t)
    ratio = ctx.acwr(t)
    sl = _with_day(ctx.sleep(t), t) or _with_day(ctx.sleep(t - timedelta(days=1)), t - timedelta(days=1))
    history = []
    for i in range(days - 1, -1, -1):
        d = t - timedelta(days=i)
        r, s = ctx.readiness(d), ctx.sleep(d)
        history.append({"day": d.isoformat(), "readiness": r["value"] if r else None, "load": ctx.load(d)["value"],
                        "sleep": s["value"] if s else None})
    todays = sorted(ctx.acts.get(t, []), key=lambda a: a.start)
    last = todays[-1] if todays else None
    if last:
        load["last_activity"] = (last.start + timedelta(seconds=last.duration_s or last.moving_s or 0)).isoformat() + "Z"
    if sl:
        n = ctx.nights.get(date.fromisoformat(sl["day"]))
        sl["end"] = n.end.isoformat() + "Z" if n else None
    return {
        "day": t.isoformat(),
        "computed_at": utcnow().isoformat(timespec="seconds") + "Z",
        "readiness": rd,
        "load": {**load, "target": [lo, hi], "acwr": round(ratio, 2) if ratio else None,
                 "yesterday": ctx.load(t - timedelta(days=1))["value"]},
        "sleep": sl,
        "history": history,
    }


def refresh(db: Session, user: User, days: int = 90) -> None:
    """Schreibt die Tageswerte als Messgrößen (Quelle „bodybase“), damit sie in Trends und Auswertungen auftauchen."""
    t = today()
    ctx = Context(db, user, t - timedelta(days=days), t)
    # alte Werte im Zeitraum entfernen: Tage ohne Grundlage (z. B. nach dem Löschen einer Quelle) verschwinden so mit
    db.execute(delete(Sample).where(Sample.user_id == user.id, Sample.source == "bodybase", Sample.metric.in_(METRICS),
                                    Sample.day > t - timedelta(days=days)))
    w = Writer(db, user.id, "bodybase")
    for i in range(days):
        d = t - timedelta(days=i)
        r, s, ld = ctx.readiness(d), ctx.sleep(d), ctx.load(d)
        if r:
            w.sample("bb_readiness", day_ts(d), r["value"])
        if s:
            w.sample("bb_sleep", day_ts(d), s["value"])
        if ld["load"] > 0:
            w.sample("bb_load", day_ts(d), ld["value"])
    w.flush_samples()
    db.commit()
