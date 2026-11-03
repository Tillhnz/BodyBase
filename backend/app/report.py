"""Wochen- und Monatsbericht im Stil der früheren WHOOP-Leistungsbewertung, aus den eigenen Tageswerten von BodyBase.

Woche: Urteil zu Belastung und Schlaf, Tagesbelastung gegen Bereitschaft (mit Zielbereich), Schlafregelmäßigkeit gegen
Schlafwert, Belastungsübersicht gegen den 3-Wochen-Schnitt, Sportarten, dazu HRV/Ruhepuls, Schlaf je Tag, Tagestabelle.
Monat: Erholsamer Schlaf (Bedarf, Stunden, Tief/REM), Belastung nach Wochentag und Sportart, Pulszonen,
Trainingsintensität (Dauer gegen Last), Jahresübersicht als Kalender für Auslastung, Bereitschaft und Schlaf,
Trainingsverhalten (Belastung gegen Ziel, 6 Monate) und Physiologische Reaktion (HRV, Ruhepuls je Monat).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from . import scores
from .models import User
from .sports import SPORTS
from .store import daily_series
from .timeutil import today

MONTHS = ["Jan.", "Feb.", "März", "April", "Mai", "Juni", "Juli", "Aug.", "Sept.", "Okt.", "Nov.", "Dez."]
MONTHS_LONG = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WD_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
ZONES = ["0–49 %", "50–59 %", "60–69 %", "70–79 %", "80–89 %", "90–100 %"]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _r(v, d=1):
    return round(v, d) if v is not None else None


class Days:
    """Alle Tageswerte für einen Zeitraum aus einem gemeinsamen Datenstand."""

    def __init__(self, db: Session, user: User, start: date, end: date):
        self.db, self.user = db, user
        self.ctx = scores.Context(db, user, start, end)
        self.hrv = {date.fromisoformat(p["day"]): p["value"] for p in daily_series(db, user, "hrv", start - timedelta(days=70), end)}
        self.rhr = {date.fromisoformat(p["day"]): p["value"] for p in daily_series(db, user, "resting_hr", start - timedelta(days=70), end)}
        self.steps = {date.fromisoformat(p["day"]): p["value"] for p in daily_series(db, user, "steps", start, end)}
        self.need_base = self.ctx.sleep_need
        self._cache: dict[date, dict] = {}

    def need(self, d: date) -> float:
        """Schlafbedarf: Ziel aus den Einstellungen plus etwas mehr nach Belastung am Vortag (wie bei WHOOP)."""
        extra = min(60.0, self.ctx.load(d - timedelta(days=1))["load"] * 0.25)
        return self.need_base + extra

    def day(self, d: date) -> dict:
        if d in self._cache:
            return self._cache[d]
        ctx = self.ctx
        r, ld, s = ctx.readiness(d), ctx.load(d), ctx.sleep(d)
        n = ctx.nights.get(d)
        lo, hi = ctx.target(r["value"] if r else None)
        zone = None
        if r:
            zone = "ueber" if ld["value"] > hi else "optimal" if ld["value"] >= lo else "erholsam"
        cons = next((p["score"] for p in (s or {}).get("parts", []) if p["key"] == "consistency"), None)
        out = {
            "day": d.isoformat(), "wd": WD[d.weekday()], "readiness": r["value"] if r else None, "load": ld["value"],
            "load_raw": round(ld["load"], 1), "target": [lo, hi], "zone": zone, "sleep": s["value"] if s else None,
            "consistency": cons, "asleep": round(n.asleep_min) if n and n.asleep_min else None, "need": round(self.need(d)),
            "deep": round(n.deep_min) if n and n.deep_min else None, "rem": round(n.rem_min) if n and n.rem_min else None,
            "hrv": _r(self.hrv.get(d), 0), "rhr": _r(self.rhr.get(d), 0), "steps": self.steps.get(d),
        }
        self._cache[d] = out
        return out

    def acts(self, a: date, b: date):
        return [x for d, lst in self.ctx.acts.items() if a <= d <= b for x in lst]


def _act_load(days: Days, a) -> float:
    return scores.load_score(days.ctx.activity_load(a))


def _sport_group(acts, top=4):
    by = defaultdict(list)
    for a in acts:
        by[a.sport or "other"].append(a)
    order = sorted(by, key=lambda k: -len(by[k]))
    main = order[:top]
    groups = {k: by[k] for k in main}
    rest = [a for k in order[top:] for a in by[k]]
    if rest:
        groups["_rest"] = rest
    return groups


def _label(sport):
    return "Alle anderen" if sport == "_rest" else SPORTS.get(sport, sport)


def _hm(minutes):
    if minutes is None:
        return "–"
    m = int(round(minutes))
    return f"{m // 60}:{m % 60:02d}"


# ---------- Woche ----------

def week(db: Session, user: User, start: date | None = None) -> dict:
    t = today()
    if start is None:  # letzte abgeschlossene Woche
        start = t - timedelta(days=t.weekday() + 7)
    start = start - timedelta(days=start.weekday())
    end = start + timedelta(days=6)
    days = Days(db, user, start - timedelta(days=21), min(end, t))
    week_days = [days.day(start + timedelta(days=i)) for i in range(7) if start + timedelta(days=i) <= t]
    prev_days = [days.day(start - timedelta(days=i)) for i in range(1, 22)]

    zones = [d["zone"] for d in week_days if d["zone"]]
    counts = {z: zones.count(z) for z in ("erholsam", "optimal", "ueber")}
    if not zones:
        load_verdict = None
    else:
        load_verdict = max(counts, key=lambda z: (counts[z], z == "optimal"))
    sl = [d["sleep"] for d in week_days if d["sleep"] is not None]
    cons = [d["consistency"] for d in week_days if d["consistency"] is not None]
    sleep_avg, cons_avg = _mean(sl), _mean(cons)
    if sleep_avg is None:
        sleep_verdict = None
    elif sleep_avg >= 80 and (cons_avg is None or cons_avg >= 70):
        sleep_verdict = "optimal"
    elif sleep_avg >= 65:
        sleep_verdict = "ausreichend"
    else:
        sleep_verdict = "verbessern"
    headline, text = _week_text(load_verdict, sleep_verdict, counts)

    acts = days.acts(start, end)
    prev_acts = days.acts(start - timedelta(days=21), start - timedelta(days=1))
    avg_load = _mean([d["load"] for d in week_days])
    prev_load = _mean([d["load"] for d in prev_days])
    dur = sum((a.duration_s or a.moving_s or 0) for a in acts) / 60
    prev_dur = sum((a.duration_s or a.moving_s or 0) for a in prev_acts) / 60 / 3
    sports = []
    for k, lst in _sport_group(acts, 6).items():
        sports.append({"sport": k, "label": _label(k), "count": len(lst), "avg_load": _r(_mean([_act_load(days, a) for a in lst]), 1),
                       "minutes": round(sum((a.duration_s or a.moving_s or 0) for a in lst) / 60)})
    sports.sort(key=lambda s: -(s["avg_load"] or 0))

    def avg_of(key, ds):
        return _mean([d[key] for d in ds])
    vitals = {k: {"week": _r(avg_of(k, week_days), 0), "base": _r(avg_of(k, prev_days), 0)} for k in ("hrv", "rhr", "readiness", "sleep", "steps")}
    sleep_hours = {"asleep": _r(avg_of("asleep", week_days), 0), "need": _r(avg_of("need", week_days), 0),
                   "base": _r(avg_of("asleep", prev_days), 0)}
    with_r = [d for d in week_days if d["readiness"] is not None]
    best = max(with_r, key=lambda d: d["readiness"]) if with_r else None
    worst = min(with_r, key=lambda d: d["readiness"]) if with_r else None
    return {
        "kind": "week", "start": start.isoformat(), "end": end.isoformat(), "running": end >= t,
        "prev": (start - timedelta(days=7)).isoformat(), "next": (start + timedelta(days=7)).isoformat() if end < t else None,
        "headline": headline, "text": text, "load_verdict": load_verdict, "sleep_verdict": sleep_verdict, "zone_counts": counts,
        "days": week_days,
        "load": {"avg": _r(avg_load), "base": _r(prev_load), "minutes": round(dur), "base_minutes": round(prev_dur),
                 "count": len(acts), "base_count": round(len(prev_acts) / 3, 1),
                 "text": _load_text(avg_load, prev_load)},
        "sports": sports, "vitals": vitals, "sleep_hours": sleep_hours,
        "best": best, "worst": worst,
    }


def _week_text(load, sleep, counts):
    load_part = {"erholsam": "Die Belastung war regenerativ", "optimal": "Die Belastung war optimal",
                 "ueber": "Die Belastung war zu hoch"}.get(load, "Zur Belastung fehlen Daten")
    sleep_part = {"optimal": "der Schlaf war optimal", "ausreichend": "der Schlaf war ausreichend",
                  "verbessern": "der Schlaf könnte verbessert werden"}.get(sleep, "zum Schlaf fehlen Daten")
    headline = f"{load_part}. {sleep_part[0].upper() + sleep_part[1:]}."
    texts = {
        "erholsam": "Du hast dir in dieser Woche weniger zugemutet, als deine Bereitschaft hergegeben hätte. "
                    "Das gibt dem Körper Zeit, sich anzupassen – ein guter Zeitpunkt, um wieder mehr zu trainieren.",
        "optimal": "Belastung und Erholung waren gut im Gleichgewicht: Du hast an den meisten Tagen so viel gemacht, wie zu deiner Bereitschaft passte.",
        "ueber": "An mehreren Tagen lag die Belastung über dem, was deine Bereitschaft empfohlen hat. "
                 "Plane bewusst leichtere Tage ein, damit die Erholung hinterherkommt.",
    }
    sleep_texts = {
        "optimal": " Dein Schlaf hat die Erholung gut unterstützt.",
        "ausreichend": " Mit etwas mehr oder regelmäßigerem Schlaf holst du noch mehr Erholung heraus.",
        "verbessern": " Mehr Schlaf und regelmäßigere Schlafenszeiten würden deine Erholung deutlich verbessern.",
    }
    text = texts.get(load, "") + sleep_texts.get(sleep, "")
    if counts and sum(counts.values()):
        text += (f" Tage: {counts['optimal']} optimal, {counts['erholsam']} erholsam, {counts['ueber']} über dem Ziel.")
    return headline, text.strip()


def _load_text(avg, base):
    if avg is None or not base:
        return None, None
    diff = (avg - base) / base
    word = ("deutlich höher" if diff > 0.25 else "etwas höher" if diff > 0.08 else "deutlich niedriger" if diff < -0.25
            else "etwas niedriger" if diff < -0.08 else "ähnlich wie sonst")
    head = f"Deine Belastung war diese Woche {word}."
    body = (f"Du hattest im Schnitt eine Auslastung von {avg:.0f} am Tag. Typisch für dich sind {base:.0f} "
            f"(Schnitt der 3 Wochen davor).")
    return head, body


# ---------- Monat ----------

def month(db: Session, user: User, year: int | None = None, mon: int | None = None) -> dict:
    t = today()
    if not year or not mon:
        year, mon = t.year, t.month
    start = date(year, mon, 1)
    end = (date(year + (mon == 12), mon % 12 + 1, 1) - timedelta(days=1))
    prev_start = date(year - (mon == 1), (mon - 2) % 12 + 1, 1)
    prev_end = start - timedelta(days=1)
    year_start = date(start.year - 1, start.month, 1) + timedelta(days=0)
    days = Days(db, user, min(year_start, start - timedelta(days=190)), min(end, t))
    last = min(end, t)
    cur = [days.day(start + timedelta(days=i)) for i in range((last - start).days + 1)]
    prev = [days.day(prev_start + timedelta(days=i)) for i in range((prev_end - prev_start).days + 1)]

    def avg(key, ds):
        return _mean([d[key] for d in ds])

    restor = {
        "need": [_r(avg("need", prev), 0), _r(avg("need", cur), 0)], "asleep": [_r(avg("asleep", prev), 0), _r(avg("asleep", cur), 0)],
        "deep": [_r(avg("deep", prev), 0), _r(avg("deep", cur), 0)], "rem": [_r(avg("rem", prev), 0), _r(avg("rem", cur), 0)],
        "sleep_score": [_r(avg("sleep", prev), 0), _r(avg("sleep", cur), 0)],
        "days": [{"day": d["day"], "wd": d["wd"], "need": d["need"], "asleep": d["asleep"], "deep": d["deep"], "rem": d["rem"]} for d in cur],
    }

    # Training
    acts = days.acts(start, last)
    prev_acts = days.acts(prev_start, prev_end)
    groups = _sport_group(acts, 4)
    keys = list(groups)
    sport_of = {id(a): k for k, lst in groups.items() for a in lst}
    # Auslastung je Wochentag, aufgeteilt nach Anteil an der Trainingslast (TRIMP) je Sportart; „rest“ = Alltag
    by_wd = [defaultdict(float) for _ in range(7)]
    rest_wd = [0.0] * 7
    total_wd = [0.0] * 7
    n_wd = [0] * 7
    for dd in cur:
        dday = date.fromisoformat(dd["day"])
        wd = dday.weekday()
        n_wd[wd] += 1
        ld = days.ctx.load(dday)
        trimp = {k: 0.0 for k in keys}
        for a in days.ctx.acts.get(dday, []):
            if id(a) in sport_of:
                trimp[sport_of[id(a)]] += days.ctx.activity_load(a)
        tot = sum(trimp.values()) + ld["steps"]
        score = dd["load"]
        total_wd[wd] += score
        if tot > 0:
            for k, v in trimp.items():
                by_wd[wd][k] += score * v / tot
            rest_wd[wd] += score * ld["steps"] / tot
    weekday = []
    for i in range(7):
        n = max(1, n_wd[i])
        weekday.append({"wd": WD_LONG[i], "parts": {k: round(by_wd[i][k] / n, 1) for k in keys},
                        "rest": round(rest_wd[i] / n, 1), "total": round(total_wd[i] / n, 1)})

    def act_stats(lst):
        return {"count": len(lst), "minutes": round(sum((a.duration_s or a.moving_s or 0) for a in lst) / 60),
                "avg_load": _r(_mean([_act_load(days, a) for a in lst])), "avg_minutes": _r(_mean([(a.duration_s or a.moving_s or 0) / 60 for a in lst]), 0)}
    training = {
        "sports": [{"key": k, "label": _label(k), **act_stats(groups[k])} for k in keys],
        "total": act_stats(acts), "prev": act_stats(prev_acts), "weekday": weekday,
        "intensity": [{"minutes": round((a.duration_s or a.moving_s or 0) / 60), "load": round(_act_load(days, a), 1),
                       "sport": sport_of[id(a)], "name": a.name, "day": a.day.isoformat()} for a in acts],
        "zones": _zones(days, acts, sport_of, keys),
    }

    # Jahresübersicht: Kalender der letzten 12 Monate (Spalten = Wochen, Zeilen = Wochentage)
    cal_start = date(start.year - 1, start.month, 1)
    cal_start -= timedelta(days=cal_start.weekday())  # mit einem Montag beginnen
    cal_end = last
    cal = []
    d = cal_start
    while d <= cal_end:
        x = days.day(d)
        cal.append({"day": x["day"], "load": x["load"], "readiness": x["readiness"], "sleep": x["sleep"]})
        d += timedelta(days=1)
    month_avgs = []
    m0 = date(start.year - 1, start.month, 1)
    for i in range(1, 13):
        ms = date(m0.year + (m0.month + i - 1) // 12, (m0.month + i - 1) % 12 + 1, 1)
        me = date(ms.year + (ms.month == 12), ms.month % 12 + 1, 1) - timedelta(days=1)
        ds = [c for c in cal if ms.isoformat() <= c["day"] <= me.isoformat()]
        month_avgs.append({"month": f"{MONTHS[ms.month - 1]} '{str(ms.year)[2:]}", "start": ms.isoformat(),
                           "load": _r(_mean([c["load"] for c in ds if c["load"]]), 0), "readiness": _r(_mean([c["readiness"] for c in ds]), 0),
                           "sleep": _r(_mean([c["sleep"] for c in ds]), 0)})
    wd_avgs = {k: [_r(_mean([c[k] for c in cal if date.fromisoformat(c["day"]).weekday() == i and c[k]]), 0) for i in range(7)]
               for k in ("load", "readiness", "sleep")}

    # Trainingsverhalten: 7-Tage-Mittel von (Auslastung − Mitte des Zielbereichs) über 6 Monate
    behav = []
    b0 = last - timedelta(days=182)
    vals = []
    d = b0 - timedelta(days=6)
    while d <= last:
        x = days.day(d)
        if x["readiness"] is not None:
            lo, hi = x["target"]
            vals.append((d, x["load"] - (lo + hi) / 2, (hi - lo) / 2))
        d += timedelta(days=1)
    for i in range((last - b0).days + 1):
        dd = b0 + timedelta(days=i)
        win = [v for v in vals if dd - timedelta(days=6) <= v[0] <= dd]
        if len(win) >= 3:
            dev = _mean([v[1] for v in win])
            half = _mean([v[2] for v in win])
            behav.append({"day": dd.isoformat(), "value": round(dev / half, 2) if half else 0})

    # Physiologische Reaktion: HRV und Ruhepuls je Monat (6 Monate)
    physio = {"hrv": _monthly(days.hrv, last, better="up"), "rhr": _monthly(days.rhr, last, better="down"),
              "hrv_days": [{"day": k.isoformat(), "value": v} for k, v in sorted(days.hrv.items()) if k >= last - timedelta(days=182)],
              "rhr_days": [{"day": k.isoformat(), "value": v} for k, v in sorted(days.rhr.items()) if k >= last - timedelta(days=182)]}

    # Zusätzliche Auswertungen
    extra = _month_extra(db, user, days, cur, prev, start, last, prev_start, prev_end)
    return {
        "kind": "month", "year": year, "month": mon, "title": f"{MONTHS_LONG[mon - 1]} {year}", "prev_title": MONTHS_LONG[prev_start.month - 1],
        "start": start.isoformat(), "end": end.isoformat(), "running": end >= t,
        "prev": f"{prev_start.year}-{prev_start.month:02d}",
        "next": None if end >= t else f"{end.year + (end.month == 12)}-{end.month % 12 + 1:02d}",
        "restorative": restor, "training": training,
        "calendar": {"start": cal_start.isoformat(), "days": cal, "months": month_avgs, "weekday": wd_avgs},
        "behaviour": behav, "physio": physio, "extra": extra,
    }


def _zones(days: Days, acts, sport_of, keys) -> dict:
    """Zeit je Pulszone (% der maximalen Herzfrequenz), aufgeteilt nach Sportart."""
    hr_max = days.ctx.hr_max
    out = [defaultdict(float) for _ in range(6)]
    estimated = 0
    for a in acts:
        k = sport_of[id(a)]
        det = a.details or {}
        series = det.get("hr") if isinstance(det.get("hr"), dict) else None
        if series and series.get("t") and series.get("v"):
            t, v = series["t"], series["v"]
            for i in range(len(t) - 1):
                dt = min(120.0, max(0.0, t[i + 1] - t[i]))
                out[_zone(v[i], hr_max)][k] += dt / 60
        elif isinstance(det.get("hr_zones"), list) and len(det["hr_zones"]) == 6:
            for i, s in enumerate(det["hr_zones"]):
                out[i][k] += (s or 0) / 60
        elif a.avg_hr:
            out[_zone(a.avg_hr, hr_max)][k] += (a.duration_s or a.moving_s or 0) / 60
            estimated += 1
    return {"labels": ZONES, "rows": [{k: round(z.get(k, 0), 1) for k in keys} for z in out],
            "totals": [round(sum(z.values())) for z in out], "estimated": estimated, "hr_max": round(hr_max)}


def _zone(bpm, hr_max):
    p = bpm / hr_max if hr_max else 0
    return 0 if p < 0.5 else 1 if p < 0.6 else 2 if p < 0.7 else 3 if p < 0.8 else 4 if p < 0.9 else 5


def _monthly(series: dict, last: date, better: str) -> list[dict]:
    out = []
    prev_avg = None
    for i in range(5, -1, -1):
        y, m = last.year, last.month - i
        while m <= 0:
            m += 12
            y -= 1
        ms = date(y, m, 1)
        me = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        vals = [v for k, v in series.items() if ms <= k <= me]
        avg = _mean(vals)
        change = (avg - prev_avg) / prev_avg * 100 if avg is not None and prev_avg else None
        status = "grau" if len(vals) < 10 else "schwarz"
        if status != "grau" and change is not None and abs(change) >= 3:
            good = (change > 0) == (better == "up")
            status = "gruen" if good else "rot"
        out.append({"month": f"{MONTHS[m - 1]} '{str(y)[2:]}", "start": ms.isoformat(), "end": me.isoformat(),
                    "avg": _r(avg, 0), "change": _r(change, 0), "days": len(vals), "status": status})
        if avg is not None:
            prev_avg = avg
    return out


def _month_extra(db, user, days: Days, cur, prev, start, last, prev_start, prev_end) -> dict:
    """Zusätzlich zu WHOOP: Kennzahlen gegen Vormonat, Körper, Schritte, Tage nach Zonen, beste/schwierigste Tage."""
    def avg(key, ds):
        return _mean([d[key] for d in ds])
    rows = []
    for key, label, unit, better, digits in (
            ("readiness", "Bereitschaft", "", "up", 0), ("sleep", "Schlafwert", "", "up", 0), ("load", "Auslastung", "", None, 0),
            ("hrv", "HRV", "ms", "up", 0), ("rhr", "Ruhepuls", "bpm", "down", 0), ("asleep", "Schlaf je Nacht", "min", "up", 0),
            ("steps", "Schritte am Tag", "", "up", 0)):
        a, b = avg(key, cur), avg(key, prev)
        if a is None and b is None:
            continue
        rows.append({"key": key, "label": label, "unit": unit, "better": better, "cur": _r(a, digits), "prev": _r(b, digits),
                     "change": _r((a - b) / b * 100, 0) if a is not None and b else None})
    zones = [d["zone"] for d in cur if d["zone"]]
    zone_counts = {z: zones.count(z) for z in ("erholsam", "optimal", "ueber")}
    rec = [d["readiness"] for d in cur if d["readiness"] is not None]
    rec_colors = {"green": sum(1 for v in rec if v >= 67), "yellow": sum(1 for v in rec if 34 <= v < 67), "red": sum(1 for v in rec if v < 34)}
    body = []
    for key, label in (("weight", "Gewicht"), ("body_fat", "Körperfett"), ("muscle_mass", "Muskelmasse"), ("vo2max", "VO₂max")):
        s = daily_series(db, user, key, prev_start, last)
        c = [p["value"] for p in s if p["day"] >= start.isoformat()]
        p_ = [p["value"] for p in s if p["day"] < start.isoformat()]
        if c:
            body.append({"key": key, "label": label, "cur": _r(_mean(c), 1), "prev": _r(_mean(p_), 1) if p_ else None,
                         "change": _r(_mean(c) - _mean(p_), 1) if p_ else None})
    with_r = [d for d in cur if d["readiness"] is not None]
    bullets = []
    for r in rows:
        if r["change"] is not None and abs(r["change"]) >= 5 and r["better"]:
            good = (r["change"] > 0) == (r["better"] == "up")
            bullets.append({"good": good, "text": f"{r['label']} {'+' if r['change'] > 0 else '−'}{abs(r['change']):.0f} % gegenüber dem Vormonat"})
    if zone_counts["ueber"] >= 5:
        bullets.append({"good": False, "text": f"An {zone_counts['ueber']} Tagen lag die Belastung über dem Ziel für deine Bereitschaft"})
    if zone_counts["optimal"] >= max(1, len(zones)) * 0.5:
        bullets.append({"good": True, "text": f"An {zone_counts['optimal']} von {len(zones)} Tagen passten Belastung und Erholung zusammen"})
    return {
        "compare": rows, "zone_counts": zone_counts, "recovery_colors": rec_colors, "body": body, "bullets": bullets[:6],
        "best": max(with_r, key=lambda d: d["readiness"]) if with_r else None,
        "worst": min(with_r, key=lambda d: d["readiness"]) if with_r else None,
    }

