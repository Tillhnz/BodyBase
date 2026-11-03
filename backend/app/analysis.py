"""Gesamtanalyse: Statistik über alle Quellen und Messgrößen, in Ebenen.

1. Gesamtbild      je Bereich (Erholung, Schlaf, Herz, Fitness, Aktivität, Körper, Ernährung) Stand, Richtung und Gründe
2. Kennzahlen      je Messgröße Mittel, Median, Streuung, Spannweite, Trend je Woche, Vergleich zum Zeitraum davor
3. Zusammenhänge   Rangkorrelationen aller Messgrößen am selben Tag und zum Folgetag, mit Signifikanz
4. Wenn–dann       Gruppenvergleiche (harte Trainingstage vs. Ruhetage, lange vs. kurze Nächte, spätes Training …)
5. Muster          Wochentagsprofile
6. Training        Sportarten, Intensität, WHO-Minuten, Belastungsverlauf, Monotonie, Muskelgruppen
7. Quellen         welche Quelle was liefert und wie gut sich Quellen decken

Alles in reinem Python, damit keine schweren Abhängigkeiten nötig sind. Signifikanz über die Fisher-Transformation
(Korrelationen) bzw. eine Normalnäherung des Welch-Tests (Gruppenvergleiche); bei vielen gleichzeitigen Tests ist das
eine Orientierung, kein Beweis.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import metrics as M
from . import providers, scores
from .models import Activity, Sample, User, Workout
from .sports import SPORTS
from .store import daily_series, priority_for
from .timeutil import today, tz

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
# Messgrößen für Zusammenhänge, Muster und Ebenen-Diagramm (nur die vorhandenen werden genutzt)
CORE = ["bb_readiness", "bb_sleep", "bb_load", "hrv", "resting_hr", "sleep_duration", "sleep_deep", "sleep_rem",
        "sleep_efficiency", "steps", "active_minutes", "active_energy", "weight", "body_fat", "muscle_mass", "stress",
        "respiratory_rate", "skin_temp_dev", "spo2", "bp_systolic", "glucose", "calories_in", "protein", "water",
        "caffeine", "mindful_minutes", "vo2max"]
# Paare, die per Definition zusammenhängen (Bestandteile): in der Matrix sichtbar, aber keine „Erkenntnis“
_FAMILIES = [
    {"bb_sleep", "sleep_duration", "sleep_deep", "sleep_rem", "sleep_efficiency"},
    {"bb_readiness", "hrv", "resting_hr", "bb_sleep"},
    {"bb_load", "steps", "active_minutes", "active_energy"},
    {"weight", "body_fat", "muscle_mass"},
]


# ---------- Grundrechnungen ----------

def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _sd(xs):
    if len(xs) < 2:
        return None
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = _mean(xs), _mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def _spearman(xs, ys):
    return _pearson(_ranks(xs), _ranks(ys))


def _p_corr(r, n):
    if r is None or n < 4 or abs(r) >= 1:
        return 0.0 if r is not None and abs(r) >= 1 else None
    z = math.atanh(r) * math.sqrt(n - 3)
    return math.erfc(abs(z) / math.sqrt(2))


def _slope(points):
    """Lineare Regression: Steigung je Tag und Bestimmtheitsmaß."""
    if len(points) < 5:
        return None, None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None, None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (my + b * (x - mx))) ** 2 for x, y in zip(xs, ys))
    return b, (1 - ss_res / ss_tot) if ss_tot else 0.0


def _welch(a, b):
    """Mittelwertunterschied, Effektstärke (Cohen d) und p (Normalnäherung)."""
    ma, mb = _mean(a), _mean(b)
    sa, sb = _sd(a) or 0.0, _sd(b) or 0.0
    pooled = math.sqrt(((len(a) - 1) * sa ** 2 + (len(b) - 1) * sb ** 2) / max(1, len(a) + len(b) - 2))
    d = (ma - mb) / pooled if pooled else 0.0
    se = math.sqrt(sa ** 2 / len(a) + sb ** 2 / len(b))
    p = math.erfc(abs(ma - mb) / se / math.sqrt(2)) if se else None
    return ma - mb, d, p


def num(v, digits=0):
    """Zahl im deutschen Format."""
    if v is None:
        return "–"
    s = f"{v:,.{digits}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def fmt_metric(key, v, signed=False):
    m = M.get(key)
    if v is None:
        return "–"
    if m and m.unit == "min" and m.category == "sleep" and abs(v) >= 60:
        sign = "−" if v < 0 else ("+" if signed else "")
        a = abs(v)
        return f"{sign}{int(a // 60)}:{int(round(a % 60)):02d} h"
    digits = m.decimals if m else 1
    if m and m.key == "steps":
        digits = 0
    s = num(abs(v) if signed else v, digits)
    if signed:
        s = ("+" if v > 0 else "−" if v < 0 else "±") + s
    unit = m.unit if m else ""
    return f"{s} {unit}".strip()


def _label(key):
    m = M.get(key)
    return m.label if m else key


# ---------- Daten laden ----------

class Data:
    def __init__(self, db: Session, user: User, days: int):
        self.db, self.user, self.days = db, user, days
        self.end = today()
        self.start = self.end - timedelta(days=days - 1)
        self.prev_start = self.start - timedelta(days=days)
        try:  # eigene Tageswerte auf Stand bringen, damit sie mit ausgewertet werden
            scores.refresh(db, user, days=min(days * 2 + 7, 800))
        except Exception:
            db.rollback()
        present = db.scalars(select(Sample.metric).where(Sample.user_id == user.id, Sample.day >= self.prev_start)
                             .group_by(Sample.metric)).all()
        self.keys = [k for k in M.METRICS if k in set(present) and k not in ("heart_rate",)]
        self.series: dict[str, dict[date, float]] = {}
        self.source_of: dict[str, dict[date, str]] = {}
        for k in self.keys:
            rows = daily_series(db, user, k, self.prev_start, self.end)
            self.series[k] = {date.fromisoformat(p["day"]): p["value"] for p in rows}
            self.source_of[k] = {date.fromisoformat(p["day"]): p["source"] for p in rows}
        self.ctx = scores.Context(db, user, self.prev_start, self.end)
        self.acts = [a for d, lst in self.ctx.acts.items() if self.prev_start <= d <= self.end for a in lst]

    def cur(self, key):
        s = self.series.get(key, {})
        return {d: v for d, v in s.items() if self.start <= d <= self.end}

    def prev(self, key):
        s = self.series.get(key, {})
        return {d: v for d, v in s.items() if self.prev_start <= d < self.start}

    def days_list(self):
        return [self.start + timedelta(days=i) for i in range(self.days)]


# ---------- Ebene 2: Kennzahlen ----------

def metric_stats(data: Data, key: str) -> dict | None:
    cur = data.cur(key)
    if not cur:
        return None
    m = M.get(key)
    vals = list(cur.values())
    prev = list(data.prev(key).values())
    pts = [((d - data.start).days, v) for d, v in sorted(cur.items())]
    b, r2 = _slope(pts)
    sd = _sd(vals)
    mean = _mean(vals)
    fitted = b * (data.days - 1) if b is not None else None
    # Richtung: der Trend muss gegenüber der Streuung ins Gewicht fallen
    trend = "stabil"
    if fitted is not None and sd and abs(fitted) >= max(0.4 * sd, 0.02 * abs(mean or 0)) and (r2 or 0) >= 0.04:
        up = fitted > 0
        trend = "steigt" if up else "sinkt"
    verdict = None
    if trend != "stabil" and m and m.better:
        verdict = "besser" if (trend == "steigt") == (m.better == "up") else "schlechter"
    weekday = [[] for _ in range(7)]
    for d, v in cur.items():
        weekday[d.weekday()].append(v)
    lo_d = min(cur, key=cur.get)
    hi_d = max(cur, key=cur.get)
    last_d = max(cur)
    prev_mean = _mean(prev)
    return {
        "key": key, "label": m.label if m else key, "unit": m.unit if m else "", "category": m.category if m else None,
        "decimals": m.decimals if m else 1, "better": m.better if m else None,
        "n": len(vals), "coverage": round(len(vals) / data.days, 3),
        "mean": mean, "median": _median(vals), "sd": sd, "p10": _pct(vals, 0.1), "p90": _pct(vals, 0.9),
        "min": {"day": lo_d.isoformat(), "value": cur[lo_d]}, "max": {"day": hi_d.isoformat(), "value": cur[hi_d]},
        "last": {"day": last_d.isoformat(), "value": cur[last_d]},
        "slope_week": b * 7 if b is not None else None, "r2": r2, "fitted_change": fitted, "trend": trend, "verdict": verdict,
        "prev_mean": prev_mean, "delta": (mean - prev_mean) if prev_mean is not None else None,
        "delta_pct": ((mean - prev_mean) / abs(prev_mean) * 100) if prev_mean else None,
        "cv": (sd / abs(mean) * 100) if sd and mean else None,
        "weekday": [_mean(w) for w in weekday], "weekday_n": [len(w) for w in weekday],
        "sources": sorted({s for d, s in data.source_of.get(key, {}).items() if d >= data.start}),
    }


def _rolling(series: dict[date, float], days: list[date], window=7):
    out = []
    for d in days:
        vals = [series[x] for x in (d - timedelta(days=i) for i in range(window)) if x in series]
        out.append(round(_mean(vals), 3) if len(vals) >= max(2, window // 3) else None)
    return out


# ---------- Ebene 3: Zusammenhänge ----------

def _trivial(a, b):
    return a == b or any(a in f and b in f for f in _FAMILIES)


def _pairs(xs: dict[date, float], ys: dict[date, float], lag: int):
    out = [(xs[d], ys[d + timedelta(days=lag)]) for d in xs if d + timedelta(days=lag) in ys]
    return [p[0] for p in out], [p[1] for p in out]


def correlations(data: Data, keys: list[str]) -> dict:
    matrix = {0: [], 1: []}
    findings = []
    for lag in (0, 1):
        for a in keys:
            row = []
            for b in keys:
                if lag == 0 and a == b:
                    row.append({"r": 1.0, "n": len(data.cur(a)), "p": 0.0})
                    continue
                xs, ys = _pairs(data.cur(a), data.cur(b), lag)
                r = _spearman(xs, ys) if len(xs) >= 10 else None
                p = _p_corr(r, len(xs)) if r is not None else None
                row.append({"r": round(r, 3) if r is not None else None, "n": len(xs), "p": p})
                if r is None or p is None or abs(r) < 0.2 or p >= 0.05 or _trivial(a, b) or len(xs) < 14:
                    continue
                if lag == 0 and keys.index(b) < keys.index(a):
                    continue  # am selben Tag ist a~b dasselbe wie b~a
                findings.append(_finding(data, a, b, lag, r, len(xs), p, xs, ys))
            matrix[lag].append(row)
    findings.sort(key=lambda f: -abs(f["r"]))
    return {"keys": keys, "labels": [_label(k) for k in keys], "same_day": matrix[0], "next_day": matrix[1],
            "findings": findings[:16]}


def _finding(data, a, b, lag, r, n, p, xs, ys):
    strength = "deutlich" if abs(r) >= 0.5 else "spürbar" if abs(r) >= 0.3 else "leicht"
    sx = _sd(xs) or 0
    # Wirkung in Einheiten: Regression auf den Rohwerten, für „eine typische Schwankung“ von a
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0
    when = "am Folgetag" if lag else "am selben Tag"
    direction = "höher" if r > 0 else "niedriger"
    text = (f"Ist {_label(a)} höher, ist {_label(b)} {when} {strength} {direction}: "
            f"je {fmt_metric(a, sx)} mehr {_label(a)} im Schnitt {fmt_metric(b, slope * sx, signed=True)}.")
    return {"a": a, "b": b, "lag": lag, "r": round(r, 3), "n": n, "p": p, "strength": strength, "text": text,
            "effect": slope * sx}


# ---------- Ebene 4: Wenn–dann ----------

def comparisons(data: Data) -> list[dict]:
    days = data.days_list()
    load = {d: data.ctx.load(d)["value"] for d in days}
    out = []

    def comp(title, a_label, a_days, b_label, b_days, outcomes, note=None):
        rows = []
        for key, offset, when in outcomes:
            ser = data.series.get(key)
            if not ser:
                continue
            a = [ser[d + timedelta(days=offset)] for d in a_days if d + timedelta(days=offset) in ser]
            b = [ser[d + timedelta(days=offset)] for d in b_days if d + timedelta(days=offset) in ser]
            if len(a) < 4 or len(b) < 4:
                continue
            diff, d_eff, p = _welch(a, b)
            m = M.get(key)
            good = None
            if m and m.better and abs(d_eff) >= 0.3:
                good = (diff > 0) == (m.better == "up")
            rows.append({"key": key, "label": _label(key), "when": when, "a": _mean(a), "b": _mean(b), "n_a": len(a), "n_b": len(b),
                         "diff": diff, "diff_text": fmt_metric(key, diff, signed=True), "a_text": fmt_metric(key, _mean(a)),
                         "b_text": fmt_metric(key, _mean(b)), "d": round(d_eff, 2), "p": p, "good": good,
                         "clear": abs(d_eff) >= 0.3 and (p is not None and p < 0.1)})
        if rows:
            out.append({"title": title, "a": a_label, "b": b_label, "n_a": len(a_days), "n_b": len(b_days), "rows": rows, "note": note,
                        "strongest": max(abs(r["d"]) for r in rows)})

    hard = [d for d in days if load[d] >= 60]
    rest = [d for d in days if load[d] < 20]
    comp("Harte Trainingstage und die Erholung danach", "Auslastung ab 60", hard, "Ruhetage (unter 20)", rest, [
        ("bb_sleep", 1, "folgende Nacht"), ("sleep_deep", 1, "folgende Nacht"), ("hrv", 1, "nächster Morgen"),
        ("resting_hr", 1, "nächster Morgen"), ("bb_readiness", 1, "nächster Tag")])

    sl = data.series.get("sleep_duration", {})
    long_n = [d for d in days if sl.get(d, 0) >= 420]
    short_n = [d for d in days if d in sl and sl[d] < 360]
    comp("Lange und kurze Nächte", "ab 7 Stunden", long_n, "unter 6 Stunden", short_n, [
        ("hrv", 0, "am Morgen danach"), ("resting_hr", 0, "am Morgen danach"), ("bb_readiness", 0, "am Tag danach"),
        ("steps", 0, "am Tag danach"), ("bb_load", 0, "am Tag danach"), ("stress", 0, "am Tag danach")])

    late, early = [], []
    for a in data.acts:
        if not (data.start <= a.day <= data.end):
            continue
        end = a.start + timedelta(seconds=a.duration_s or a.moving_s or 0)
        hour = end.replace(tzinfo=timezone.utc).astimezone(tz()).hour
        (late if hour >= 20 else early).append(a.day)
    late_set = set(late)
    early_only = sorted(set(early) - late_set)
    comp("Spätes Training und Schlaf", "Training endet nach 20 Uhr", sorted(late_set), "nur früher am Tag", early_only, [
        ("bb_sleep", 1, "folgende Nacht"), ("sleep_duration", 1, "folgende Nacht"), ("sleep_deep", 1, "folgende Nacht"),
        ("hrv", 1, "nächster Morgen"), ("resting_hr", 1, "nächster Morgen")])

    kinds = defaultdict(set)
    for a in data.acts:
        if data.start <= a.day <= data.end:
            kinds[a.day].add("strength" if a.sport in ("strength", "climb") else "endurance"
                             if a.sport in ("run", "ride", "swim", "row", "ski", "cardio", "hike") else "other")
    strength_d = [d for d, k in kinds.items() if k == {"strength"}]
    endurance_d = [d for d, k in kinds.items() if k == {"endurance"}]
    comp("Kraft- und Ausdauertage", "nur Kraft/Klettern", strength_d, "nur Ausdauer", endurance_d, [
        ("hrv", 1, "nächster Morgen"), ("resting_hr", 1, "nächster Morgen"), ("bb_sleep", 1, "folgende Nacht"),
        ("bb_readiness", 1, "nächster Tag")])

    st = data.series.get("steps", {})
    many = [d for d in days if st.get(d, 0) >= 10000]
    few = [d for d in days if d in st and st[d] < 5000]
    comp("Viel und wenig Bewegung im Alltag", "ab 10.000 Schritte", many, "unter 5.000", few, [
        ("bb_sleep", 1, "folgende Nacht"), ("sleep_deep", 1, "folgende Nacht"), ("bb_readiness", 1, "nächster Tag"),
        ("stress", 0, "am selben Tag")])

    weekend = [d for d in days if d.weekday() >= 5]
    weekday = [d for d in days if d.weekday() < 5]
    comp("Wochenende und Woche", "Sa und So", weekend, "Mo bis Fr", weekday, [
        ("sleep_duration", 0, "Nacht davor"), ("bb_sleep", 0, "Nacht davor"), ("steps", 0, "am Tag"),
        ("bb_load", 0, "am Tag"), ("hrv", 0, "am Morgen")])

    caf = data.series.get("caffeine", {})
    if caf:
        comp("Koffein und Schlaf", "ab 200 mg", [d for d in days if caf.get(d, 0) >= 200], "unter 50 mg",
             [d for d in days if d in caf and caf[d] < 50], [("bb_sleep", 1, "folgende Nacht"), ("sleep_deep", 1, "folgende Nacht")])
    mind = data.series.get("mindful_minutes", {})
    if mind:
        comp("Achtsamkeit", "ab 10 Minuten", [d for d in days if mind.get(d, 0) >= 10], "keine",
             [d for d in days if d not in mind or mind[d] == 0], [("hrv", 1, "nächster Morgen"), ("bb_sleep", 1, "folgende Nacht"),
                                                                ("stress", 0, "am selben Tag")])
    out.sort(key=lambda c: -c["strongest"])
    return out


# ---------- Ebene 6: Training ----------

def training(data: Data) -> dict:
    ctx = data.ctx
    acts = [a for a in data.acts if data.start <= a.day <= data.end]
    by_sport = defaultdict(lambda: {"count": 0, "minutes": 0.0, "distance_km": 0.0, "load": 0.0, "hr": []})
    zones = {"locker": 0.0, "moderat": 0.0, "intensiv": 0.0}
    hours = [0] * 24
    weeks = defaultdict(lambda: {"minutes": 0.0, "load": 0.0, "count": 0, "who": 0.0, "strength_days": set(), "days": set()})
    for a in acts:
        minutes = (a.duration_s or a.moving_s or 0) / 60
        load = ctx.activity_load(a)
        s = by_sport[a.sport or "other"]
        s["count"] += 1
        s["minutes"] += minutes
        s["distance_km"] += (a.distance_m or 0) / 1000
        s["load"] += load
        if a.avg_hr:
            s["hr"].append(a.avg_hr)
        if a.avg_hr and ctx.hr_max > ctx.hr_rest:
            hrr = (a.avg_hr - ctx.hr_rest) / (ctx.hr_max - ctx.hr_rest)
        else:
            hrr = scores.SPORT_INTENSITY.get(a.sport or "other", 0.5)
        zone = "locker" if hrr < 0.4 else "moderat" if hrr < 0.6 else "intensiv"
        zones[zone] += minutes
        hours[a.start.replace(tzinfo=timezone.utc).astimezone(tz()).hour] += 1
        wk = a.day - timedelta(days=a.day.weekday())
        w = weeks[wk]
        w["minutes"] += minutes
        w["load"] += load
        w["count"] += 1
        w["days"].add(a.day)
        # WHO: 150–300 min moderat oder 75–150 min intensiv je Woche; intensiv zählt doppelt
        w["who"] += minutes * (2 if zone == "intensiv" else 1 if zone == "moderat" else 0)
        if a.sport in ("strength", "climb"):
            w["strength_days"].add(a.day)
    week_list = []
    wk = data.start - timedelta(days=data.start.weekday())
    while wk <= data.end:
        w = weeks.get(wk)
        daily = [ctx.load(wk + timedelta(days=i))["load"] for i in range(7) if wk + timedelta(days=i) <= data.end]
        m, sd = _mean(daily), _sd(daily)
        monotony = (m / sd) if sd else None
        end_day = min(wk + timedelta(days=6), data.end)
        acwr = ctx.acwr(end_day)
        week_list.append({
            "week": wk.isoformat(), "minutes": round(w["minutes"]) if w else 0, "load": round(w["load"]) if w else 0,
            "count": w["count"] if w else 0, "who_minutes": round(w["who"]) if w else 0,
            "strength_days": len(w["strength_days"]) if w else 0, "active_days": len(w["days"]) if w else 0,
            "monotony": round(monotony, 2) if monotony else None, "acwr": round(acwr, 2) if acwr else None,
            "partial": wk < data.start or end_day < wk + timedelta(days=6),
        })
        wk += timedelta(days=7)
    full = [w for w in week_list if not w["partial"]] or week_list
    sports = sorted(({"sport": k, "label": SPORTS.get(k, k), "count": v["count"], "minutes": round(v["minutes"]),
                      "distance_km": round(v["distance_km"], 1), "load": round(v["load"]),
                      "avg_hr": round(_mean(v["hr"])) if v["hr"] else None} for k, v in by_sport.items()), key=lambda x: -x["load"])
    total_load = sum(s["load"] for s in sports) or 1
    for s in sports:
        s["load_share"] = round(s["load"] / total_load * 100, 1)
    # Muskelgruppen aus Krafttraining, Sport und Gewohnheiten
    groups = []
    try:
        from .coach import GROUP_WEIGHT, GROUPS
        from .strength import body_load
        bl = body_load(data.db, data.user.id, data.days, data.end)
        by = {m["muscle"]: m["value"] for m in bl["muscles"]}
        raw = {g: sum(by.get(m, 0) for m in ms) for g, ms in GROUPS.items()}
        norm = {g: v / GROUP_WEIGHT[g] for g, v in raw.items()}
        top = max(norm.values()) or 1
        groups = [{"group": g, "points": round(raw[g], 1), "relative": round(norm[g] / top * 100)} for g in GROUPS]
    except Exception:
        groups = []
    wos = data.db.scalars(select(Workout).where(Workout.user_id == data.user.id, Workout.day >= data.start)).all()
    return {
        "count": len(acts), "minutes": round(sum((a.duration_s or a.moving_s or 0) for a in acts) / 60),
        "sports": sports, "zones": {k: round(v) for k, v in zones.items()}, "hours": hours, "weeks": week_list,
        "avg_who": round(_mean([w["who_minutes"] for w in full]) or 0), "avg_strength_days": round(_mean([w["strength_days"] for w in full]) or 0, 1),
        "avg_active_days": round(_mean([w["active_days"] for w in full]) or 0, 1),
        "weeks_who_met": sum(1 for w in full if w["who_minutes"] >= 150), "weeks_full": len(full),
        "muscle_groups": groups,
        "strength": {"workouts": len(wos), "volume_kg": round(sum(w.volume_kg or 0 for w in wos)),
                     "prs": sum(len(w.prs or []) for w in wos)},
        "hr_rest": round(ctx.hr_rest), "hr_max": round(ctx.hr_max),
    }


# ---------- Ebene 7: Quellen ----------

def sources(data: Data) -> list[dict]:
    out = []
    for key in data.keys:
        rows = data.db.execute(select(Sample.source, func.count(func.distinct(Sample.day)), func.max(Sample.day))
                               .where(Sample.user_id == data.user.id, Sample.metric == key, Sample.day >= data.start)
                               .group_by(Sample.source)).all()
        if not rows:
            continue
        srcs = [{"source": s, "name": providers.name_of(s), "days": n, "last": d.isoformat() if d else None} for s, n, d in rows]
        order = priority_for(data.user, key)
        used = data.source_of.get(key, {})
        share = defaultdict(int)
        for d, s in used.items():
            if d >= data.start:
                share[s] += 1
        for s in srcs:
            s["used_days"] = share.get(s["source"], 0)
        srcs.sort(key=lambda s: (order.index(s["source"]) if s["source"] in order else 99, -s["days"]))
        item = {"key": key, "label": _label(key), "sources": srcs, "agreement": None}
        if len(srcs) >= 2:
            a, b = srcs[0]["source"], srcs[1]["source"]
            sa = {date.fromisoformat(p["day"]): p["value"] for p in daily_series(data.db, data.user, key, data.start, data.end, source=a)}
            sb = {date.fromisoformat(p["day"]): p["value"] for p in daily_series(data.db, data.user, key, data.start, data.end, source=b)}
            common = sorted(set(sa) & set(sb))
            if len(common) >= 5:
                xa = [sa[d] for d in common]
                xb = [sb[d] for d in common]
                mb = _mean(xb)
                diff = _mean([x - y for x, y in zip(xa, xb)])
                r = _pearson(xa, xb)
                pct = diff / abs(mb) * 100 if mb else None
                text = (f"{providers.name_of(a)} liegt im Schnitt {fmt_metric(key, diff, signed=True)}"
                        f"{f' ({num(pct, 0)} %)' if pct is not None else ''} neben {providers.name_of(b)}")
                item["agreement"] = {"a": a, "b": b, "days": len(common), "diff": diff, "pct": pct,
                                     "r": round(r, 3) if r is not None else None, "text": text}
        out.append(item)
    return out


# ---------- Ebene 1: Gesamtbild ----------

def _status(score):
    if score is None:
        return "unklar"
    return "gut" if score >= 70 else "okay" if score >= 50 else "achtung"


def overview(data: Data, st: dict[str, dict], tr: dict) -> list[dict]:
    goals = {**_default_goals(), **((data.user.prefs or {}).get("goals") or {})}
    doms = []

    def g(key, field="mean"):
        return (st.get(key) or {}).get(field)

    def trend_fact(key):
        s = st.get(key)
        if not s or s["fitted_change"] is None:
            return None
        if s["trend"] == "stabil":
            return f"{s['label']} stabil um {fmt_metric(key, s['mean'])}"
        return f"{s['label']} {s['trend']} ({fmt_metric(key, s['fitted_change'], signed=True)} im Zeitraum)"

    # Erholung
    if "bb_readiness" in st:
        cur = data.cur("bb_readiness")
        green = sum(1 for v in cur.values() if v >= 55) / len(cur) * 100
        red = sum(1 for v in cur.values() if v < 40)
        doms.append({"key": "recovery", "title": "Erholung", "cat": "recovery", "score": round(g("bb_readiness")),
                     "status": _status(g("bb_readiness")), "metric": "bb_readiness", "verdict": st["bb_readiness"]["verdict"],
                     "headline": f"Bereitschaft im Schnitt {num(g('bb_readiness'))}",
                     "facts": [f"{num(green)} % der Tage gut erholt (ab 55)", f"{red} Tage deutlich angeschlagen (unter 40)",
                               trend_fact("hrv"), trend_fact("resting_hr")]})
    # Schlaf
    if "bb_sleep" in st or "sleep_duration" in st:
        need = float(goals.get("sleep_duration") or 480)
        sl = data.cur("sleep_duration")
        enough = sum(1 for v in sl.values() if v >= 420) / len(sl) * 100 if sl else None
        beds = []
        for d, n in data.ctx.nights.items():
            if data.start <= d <= data.end:
                beds.append(data.ctx._bed_minutes(n))
        bed_sd = _sd(beds)
        facts = [f"im Schnitt {fmt_metric('sleep_duration', g('sleep_duration'))} geschlafen (Ziel {fmt_metric('sleep_duration', need)})" if sl else None,
                 f"{num(enough)} % der Nächte mindestens 7 Stunden" if enough is not None else None,
                 f"Einschlafzeit schwankt um ± {num(bed_sd)} Minuten" if bed_sd else None]
        if g("sleep_deep") and g("sleep_duration"):
            facts.append(f"Tiefschlaf {num(g('sleep_deep') / g('sleep_duration') * 100)} %, REM {num((g('sleep_rem') or 0) / g('sleep_duration') * 100)} % der Schlafzeit")
        score = g("bb_sleep")
        doms.append({"key": "sleep", "title": "Schlaf", "cat": "sleep", "score": round(score) if score is not None else None,
                     "status": _status(score), "metric": "bb_sleep" if "bb_sleep" in st else "sleep_duration",
                     "verdict": (st.get("bb_sleep") or st.get("sleep_duration") or {}).get("verdict"),
                     "headline": f"Schlafwert im Schnitt {num(score)}" if score is not None else "Schlafdauer", "facts": facts})
    # Herz-Kreislauf
    if any(k in st for k in ("resting_hr", "hrv", "bp_systolic")):
        facts = [trend_fact("resting_hr"), trend_fact("hrv")]
        status = "okay"
        verdicts = [st[k]["verdict"] for k in ("resting_hr", "hrv") if k in st and st[k]["verdict"]]
        if verdicts and all(v == "besser" for v in verdicts):
            status = "gut"
        elif "schlechter" in verdicts:
            status = "achtung" if verdicts.count("schlechter") == len(verdicts) else "okay"
        elif not verdicts:
            status = "gut" if (g("resting_hr") or 99) < 60 else "okay"
        if "bp_systolic" in st:
            sys_, dia = g("bp_systolic"), g("bp_diastolic")
            cat = ("optimal" if sys_ < 120 and (dia or 0) < 80 else "normal" if sys_ < 130 and (dia or 0) < 85
                   else "hoch-normal" if sys_ < 140 and (dia or 0) < 90 else "erhöht")
            facts.append(f"Blutdruck im Schnitt {num(sys_)}/{num(dia)} mmHg ({cat})")
            if cat == "erhöht":
                status = "achtung"
        if "spo2" in st:
            facts.append(f"Sauerstoffsättigung im Schnitt {num(g('spo2'))} %")
        doms.append({"key": "heart", "title": "Herz & Kreislauf", "cat": "heart", "score": None, "status": status,
                     "metric": "resting_hr" if "resting_hr" in st else "hrv", "verdict": None,
                     "headline": f"Ruhepuls {fmt_metric('resting_hr', g('resting_hr'))} · HRV {fmt_metric('hrv', g('hrv'))}"
                     if "resting_hr" in st and "hrv" in st else (trend_fact("resting_hr") or trend_fact("hrv") or ""), "facts": facts})
    # Fitness
    if "vo2max" in st or tr["count"]:
        facts = [trend_fact("vo2max")]
        weeks = [w for w in tr["weeks"] if not w["partial"]]
        if len(weeks) >= 4:
            first = _mean([w["load"] for w in weeks[: len(weeks) // 2]])
            second = _mean([w["load"] for w in weeks[len(weeks) // 2:]])
            if first:
                facts.append(f"Trainingslast je Woche zweite Hälfte {num((second - first) / first * 100, 0)} % gegenüber der ersten")
        vo = g("vo2max", "last")
        vo_v = vo["value"] if vo else None
        level = _vo2_level(vo_v, data.user)
        if level:
            facts.append(f"VO₂max {num(vo_v, 1)}: {level} für Alter und Geschlecht")
        verdict = (st.get("vo2max") or {}).get("verdict")
        doms.append({"key": "fitness", "title": "Fitness", "cat": "activity", "score": None,
                     "status": "gut" if verdict == "besser" or level in ("sehr gut", "ausgezeichnet") else "achtung" if verdict == "schlechter" else "okay",
                     "metric": "vo2max" if "vo2max" in st else "bb_load", "verdict": verdict,
                     "headline": f"VO₂max {num(vo_v, 1)}" if vo_v else f"{tr['count']} Trainings im Zeitraum", "facts": facts})
    # Aktivität
    facts = [f"{num(tr['avg_who'])} WHO-Minuten je Woche (Empfehlung mindestens 150, intensiv zählt doppelt)",
             f"in {tr['weeks_who_met']} von {tr['weeks_full']} Wochen erreicht",
             f"{num(tr['avg_strength_days'], 1)} Krafttage je Woche (Empfehlung mindestens 2)"]
    if "steps" in st:
        goal = goals.get("steps") or 10000
        cur = data.cur("steps")
        hit = sum(1 for v in cur.values() if v >= goal) / len(cur) * 100
        facts.insert(0, f"{fmt_metric('steps', g('steps'))} Schritte am Tag, Ziel an {num(hit)} % der Tage erreicht")
    act_score = min(100, tr["avg_who"] / 150 * 60 + min(2, tr["avg_strength_days"]) / 2 * 25 + (15 if (g("steps") or 0) >= 7000 else 0))
    doms.append({"key": "activity", "title": "Aktivität", "cat": "activity", "score": round(act_score), "status": _status(act_score),
                 "metric": "bb_load", "verdict": None, "headline": f"{num(tr['avg_active_days'], 1)} Trainingstage je Woche", "facts": facts})
    # Körper
    if "weight" in st:
        w = st["weight"]
        facts = [trend_fact("weight"), trend_fact("body_fat"), trend_fact("muscle_mass")]
        comp = _composition(data)
        if comp:
            facts.append(comp)
        doms.append({"key": "body", "title": "Körper", "cat": "body", "score": None,
                     "status": "gut" if (st.get("body_fat") or {}).get("verdict") == "besser" or (st.get("muscle_mass") or {}).get("verdict") == "besser"
                     else "achtung" if (st.get("body_fat") or {}).get("verdict") == "schlechter" else "okay",
                     "metric": "weight", "verdict": None, "headline": f"Gewicht {fmt_metric('weight', w['last']['value'])}", "facts": facts})
    # Ernährung
    if "calories_in" in st or "protein" in st:
        cov = (st.get("calories_in") or st.get("protein"))["coverage"]
        facts = [f"an {num(cov * 100)} % der Tage erfasst"]
        if "protein" in st and "weight" in st:
            facts.append(f"Eiweiß {num(g('protein'))} g am Tag = {num(g('protein') / g('weight', 'mean'), 1)} g je kg Körpergewicht "
                         f"(für Kraftaufbau oft 1,6–2,2 g/kg empfohlen)")
        if "calories_in" in st and "total_energy" in st:
            facts.append(f"Bilanz im Schnitt {fmt_metric('calories_in', g('calories_in') - g('total_energy'), signed=True)} am Tag")
        doms.append({"key": "nutrition", "title": "Ernährung", "cat": "nutrition", "score": None, "status": "unklar" if cov < 0.5 else "okay",
                     "metric": "calories_in" if "calories_in" in st else "protein", "verdict": None,
                     "headline": f"{fmt_metric('calories_in', g('calories_in'))} am Tag" if "calories_in" in st else "Eiweiß", "facts": facts})
    for d in doms:
        d["facts"] = [f for f in d["facts"] if f]
    return doms


def _default_goals():
    from .routers.account import DEFAULT_GOALS
    return dict(DEFAULT_GOALS)


def _composition(data: Data) -> str | None:
    w, bf = data.cur("weight"), data.cur("body_fat")
    common = sorted(set(w) & set(bf))
    if len(common) < 4:
        return None
    k = max(1, min(7, len(common) // 3))
    first, last = common[:k], common[-k:]
    fat0 = _mean([w[d] * bf[d] / 100 for d in first])
    fat1 = _mean([w[d] * bf[d] / 100 for d in last])
    lean0 = _mean([w[d] * (1 - bf[d] / 100) for d in first])
    lean1 = _mean([w[d] * (1 - bf[d] / 100) for d in last])
    return (f"Gewicht {fmt_metric('weight', (fat1 + lean1) - (fat0 + lean0), signed=True)}: davon Fett "
            f"{fmt_metric('weight', fat1 - fat0, signed=True)}, fettfreie Masse {fmt_metric('weight', lean1 - lean0, signed=True)}")


# grobe Einordnung nach Alter und Geschlecht (Cooper-Institut/ACSM, gerundet): Grenzen für „gut“, „sehr gut“, „ausgezeichnet“
_VO2 = {"m": [(30, 43, 48, 53), (40, 41, 46, 52), (50, 38, 43, 48), (60, 35, 40, 45), (200, 31, 36, 41)],
        "f": [(30, 36, 41, 46), (40, 34, 39, 44), (50, 31, 36, 41), (60, 28, 33, 37), (200, 25, 30, 34)]}


def _vo2_level(v, user: User):
    if not v or not user.birth_year:
        return None
    age = today().year - user.birth_year
    table = _VO2["f" if (user.sex or "").lower().startswith(("f", "w")) else "m"]
    for top, good, very, exc in table:
        if age < top:
            return "ausgezeichnet" if v >= exc else "sehr gut" if v >= very else "gut" if v >= good else "ausbaufähig"
    return None


# ---------- Zusammenfassung ----------

def summary(doms: list[dict], corr: dict, comps: list[dict], st: dict) -> dict:
    strengths, attention = [], []
    for d in doms:
        if d["status"] == "gut":
            strengths.append(f"{d['title']}: {d['headline']}")
        elif d["status"] == "achtung":
            attention.append(f"{d['title']}: {d['headline']}")
    for k, s in st.items():
        if s["verdict"] == "besser" and k in CORE:
            strengths.append(f"{s['label']} entwickelt sich gut ({fmt_metric(k, s['fitted_change'], signed=True)})")
        elif s["verdict"] == "schlechter" and k in CORE:
            attention.append(f"{s['label']} entwickelt sich ungünstig ({fmt_metric(k, s['fitted_change'], signed=True)})")
    for c in comps:
        for r in c["rows"]:
            if r["clear"] and r["good"] is False and c["title"].startswith(("Spätes", "Harte", "Koffein")):
                attention.append(f"{c['title']}: {r['label']} {r['when']} {r['diff_text']} ({c['a']} gegenüber {c['b']})")
                break
    return {"strengths": strengths[:6], "attention": attention[:6],
            "top_links": [f["text"] for f in corr["findings"][:3]]}


# ---------- Bericht ----------

def report(db: Session, user: User, days: int = 90) -> dict:
    data = Data(db, user, days)
    st = {k: s for k in data.keys if (s := metric_stats(data, k))}
    core = [k for k in CORE if k in st and st[k]["n"] >= 14]
    corr = correlations(data, core[:16])
    comps = comparisons(data)
    tr = training(data)
    doms = overview(data, st, tr)
    days_list = data.days_list()
    layers = {k: {"daily": [data.cur(k).get(d) for d in days_list], "rolling": _rolling(data.series[k], days_list),
                  "mean": st[k]["mean"], "sd": st[k]["sd"]} for k in core}
    layers_load = [data.ctx.load(d)["value"] for d in days_list]
    sleep_bed = []
    for d in days_list:
        n = data.ctx.nights.get(d)
        sleep_bed.append(round(data.ctx._bed_minutes(n)) if n else None)
    return {
        "days": days, "start": data.start.isoformat(), "end": data.end.isoformat(),
        "summary": summary(doms, corr, comps, st),
        "domains": doms,
        "stats": [st[k] for k in data.keys if k in st],
        "correlations": corr,
        "comparisons": comps,
        "patterns": {k: {"label": st[k]["label"], "weekday": st[k]["weekday"], "n": st[k]["weekday_n"], "mean": st[k]["mean"],
                         "sd": st[k]["sd"], "better": st[k]["better"]} for k in core},
        "training": tr,
        "layers": {"days": [d.isoformat() for d in days_list], "series": layers, "load": layers_load, "bedtime": sleep_bed},
        "sources": sources(data),
        "coverage": {"metrics": len(st), "sources": sorted({s for k in st for s in st[k]["sources"]}),
                     "activities": tr["count"], "nights": sum(1 for d in data.ctx.nights if data.start <= d <= data.end)},
    }
