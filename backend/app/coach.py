"""Hinweise und Lob aus den Trainingsdaten: vernachlässigte Muskelgruppen, Ungleichgewichte, Serien, Fortschritte.

Bewusst einfache, nachvollziehbare Regeln. Jede Aussage nennt ihren Grund, damit man sie einordnen kann.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import habits as H
from .models import Activity, Exercise, Habit, Workout, WorkoutSet
from .timeutil import local_hour_now

GROUPS = {
    "Brust": ["chest"], "Rücken": ["lats", "upper_back", "lower_back", "traps"], "Schultern": ["shoulders"],
    "Arme": ["biceps", "triceps", "forearms"], "Beine": ["quads", "hamstrings", "glutes", "calves", "adductors", "abductors"],
    "Rumpf": ["abs"],
}
# Gruppen sind unterschiedlich groß: Beine und Rücken sollen mehr abbekommen als Arme
GROUP_WEIGHT = {"Brust": 1.0, "Rücken": 1.4, "Schultern": 0.8, "Arme": 0.8, "Beine": 1.6, "Rumpf": 0.7}
SUGGEST = {
    "Brust": ["push_up", "bench_press_db", "fly_db"], "Rücken": ["pull_up", "seated_row", "db_row", "back_extension"],
    "Schultern": ["lateral_raise", "shoulder_press_db", "face_pull"], "Arme": ["curl_db", "triceps_pushdown", "hammer_curl"],
    "Beine": ["squat", "rdl", "leg_curl_seated", "hip_thrust"], "Rumpf": ["plank", "leg_raise_hanging", "cable_crunch"],
    "hamstrings": ["rdl", "leg_curl_lying", "good_morning"], "pull": ["pull_up", "seated_row", "face_pull"],
    "push": ["push_up", "shoulder_press_db", "dips_triceps"],
}
DAYS = 14


def _suggestions(db: Session, user_id: int, key: str, muscles: list[str] | None = None) -> list[dict]:
    """Zuerst Übungen, die man schon kennt (meist benutzt), dann bewährte aus dem Katalog."""
    out: list[dict] = []
    if muscles:
        rows = db.execute(select(Exercise.id, Exercise.name, func.count(WorkoutSet.id).label("n"))
                          .join(WorkoutSet, WorkoutSet.exercise_id == Exercise.id)
                          .where(WorkoutSet.user_id == user_id, Exercise.primary.in_(muscles))
                          .group_by(Exercise.id, Exercise.name).order_by(func.count(WorkoutSet.id).desc()).limit(2)).all()
        out += [{"id": r.id, "name": r.name, "known": True} for r in rows]
    for k in SUGGEST.get(key, []):
        e = db.scalar(select(Exercise).where(Exercise.key == k))
        if e and all(x["id"] != e.id for x in out):
            out.append({"id": e.id, "name": e.name, "known": False})
    return out[:3]


def insights(db: Session, user_id: int, today: date) -> list[dict]:
    from .strength import body_load
    cur = body_load(db, user_id, DAYS, today)
    by = {m["muscle"]: m["value"] for m in cur["muscles"]}
    groups = {g: sum(by.get(m, 0) for m in ms) for g, ms in GROUPS.items()}
    norm = {g: v / GROUP_WEIGHT[g] for g, v in groups.items()}
    total = sum(groups.values())
    both = body_load(db, user_id, 2 * DAYS, today)
    prev_total = sum(m["value"] for m in both["muscles"] if m["muscle"] in sum(GROUPS.values(), [])) - total
    out: list[dict] = []

    last = db.scalar(select(func.max(Activity.start)).where(Activity.user_id == user_id, Activity.duplicate_of.is_(None)))
    if total < 6:
        if last is None:
            return [{"type": "tip", "title": "Los geht's", "text": "Sobald Trainings, Aktivitäten oder Gewohnheiten da sind, bekommst du hier Hinweise, welche Muskeln zu kurz kommen und was gut läuft."}]
        days_ago = (today - last.date()).days
        if days_ago >= 7:
            out.append({"type": "tip", "title": f"Seit {days_ago} Tagen kein Training",
                        "text": "Schon 20 Minuten mit ein paar Grundübungen bringen dich zurück in den Rhythmus. Fang leicht an."})
    else:
        top = max(norm.values()) or 1
        neglected = [g for g, v in norm.items() if v < 0.12 * top]
        for g in sorted(neglected, key=lambda g: norm[g]):
            what = "gar nicht" if groups[g] == 0 else "kaum"
            out.append({"type": "warn", "title": f"{g} {what} trainiert",
                        "text": f"In den letzten {DAYS} Tagen kam {g.lower() if g != 'Rumpf' else 'der Rumpf'} {what} vor, während anderes regelmäßig dran war. "
                                "Zwei, drei Sätze pro Training reichen schon, um das auszugleichen.",
                        "group": g, "exercises": _suggestions(db, user_id, g, GROUPS[g])})
        # Ungleichgewichte innerhalb der trainierten Bereiche
        push = by.get("chest", 0) + 0.5 * by.get("shoulders", 0) + 0.5 * by.get("triceps", 0)
        pull = by.get("lats", 0) + by.get("upper_back", 0) + 0.5 * by.get("biceps", 0)
        if push >= 8 and pull < push / 1.6 and "Rücken" not in neglected:
            out.append({"type": "tip", "title": "Mehr ziehen als drücken",
                        "text": f"Drücken (Brust, Schultern) liegt deutlich vor Ziehen (Rücken): etwa {round(push)} zu {round(pull)}. "
                                "Mehr Zugübungen gleichen das aus und sind gut für die Haltung.",
                        "exercises": _suggestions(db, user_id, "pull", ["lats", "upper_back"])})
        quads, hams = by.get("quads", 0), by.get("hamstrings", 0)
        if quads >= 8 and hams < quads * 0.35 and "Beine" not in neglected:
            out.append({"type": "tip", "title": "Beinrückseite kommt zu kurz",
                        "text": "Die Oberschenkel vorne arbeiten viel (auch beim Radfahren), die Rückseite wenig. "
                                "Kreuzheben-Varianten oder Beinbeuger beugen Verletzungen und Knieproblemen vor.",
                        "exercises": _suggestions(db, user_id, "hamstrings", ["hamstrings"])})
        if not neglected and min(norm.values()) >= 0.3 * top:
            out.append({"type": "good", "title": "Ausgewogen trainiert",
                        "text": f"Alle großen Muskelgruppen waren in den letzten {DAYS} Tagen dabei. Genau so."})
        if prev_total >= 10:
            change = (total - prev_total) / prev_total
            if change >= 0.15:
                out.append({"type": "good", "title": "Mehr als in den zwei Wochen davor",
                            "text": f"Rund {round(change * 100)} % mehr Trainingsumfang. Achte darauf, genug zu schlafen, damit die Steigerung ankommt."})
            elif change <= -0.4:
                out.append({"type": "tip", "title": "Ruhigere Phase",
                            "text": f"Etwa {round(-change * 100)} % weniger als in den zwei Wochen davor. Als Erholung völlig in Ordnung; wenn nicht geplant, hilft ein fester Termin im Kalender."})

    # Serien im Krafttraining
    weeks = _strength_week_streak(db, user_id, today)
    if weeks >= 3:
        out.append({"type": "good", "title": f"{weeks} Wochen in Folge Krafttraining", "text": "Regelmäßigkeit schlägt alles andere. Weiter so."})
    prs = db.scalars(select(Workout).where(Workout.user_id == user_id, Workout.day >= today - timedelta(days=6))).all()
    n_prs = sum(len(w.prs or []) for w in prs)
    if n_prs:
        out.append({"type": "good", "title": f"{n_prs} neue {'Bestleistung' if n_prs == 1 else 'Bestleistungen'} diese Woche",
                    "text": "Du wirst stärker. Ein Blick in die Übungen zeigt, wo genau."})

    # Gewohnheiten
    hour = local_hour_now()
    for h in db.scalars(select(Habit).where(Habit.user_id == user_id, Habit.archived.is_not(True))):
        d = H.habit_dict(db, h, today, days=1)
        if d["streak"] >= 7:
            nxt = d["next_week_target"]
            extra = f" Ab Montag sind es {_fmt(nxt)} {h.unit or ''}.".rstrip(" .") + "." if h.increment and nxt else ""
            out.append({"type": "good", "title": f"{h.name}: {d['streak']} Tage in Folge", "text": f"Starke Serie.{extra}"})
        t = d["today"]
        if t["due"] and not t["done"] and hour >= 17:
            rest = (t["target"] or 1) - (t["value"] or 0)
            text = f"Heute fehlen noch {_fmt(rest)} {h.unit or ''}".rstrip() + "." if h.kind == "count" else "Heute noch nicht abgehakt."
            if d["streak"] >= 3:
                text += f" Deine Serie von {d['streak']} Tagen hält, wenn du es heute noch schaffst."
            out.append({"type": "tip", "title": f"{h.name} offen", "text": text, "habit_id": h.id})
    # Muskelmasse je Region (Waage mit Segmentmessung)
    try:
        from . import segments as SG
        from .models import User
        seg = SG.overview(db, db.get(User, user_id), 90, today)
        for r in seg.get("regions", []) if seg.get("has_data") else []:
            if r["change_kg"] is None:
                continue
            if r["change_kg"] >= 0.2:
                out.append({"type": "good", "title": f"{r['region']}: +{_fmt(round(r['change_kg'], 1))} kg Muskeln in 90 Tagen",
                            "text": r["comment"]})
            elif r["change_kg"] <= -0.3:
                out.append({"type": "tip", "title": f"{r['region']}: {_fmt(round(r['change_kg'], 1))} kg Muskeln in 90 Tagen",
                            "text": r["comment"]})
    except Exception:  # Hinweise dürfen nie die Startseite blockieren
        pass
    order = {"warn": 0, "tip": 1, "good": 2}
    out.sort(key=lambda x: order[x["type"]])
    try:
        from .models import User
        recent = recent_changes(db, db.get(User, user_id), today)
    except Exception:  # noqa: BLE001 - Hinweise dürfen nie die Startseite blockieren
        recent = []
    # Gesamtbild zuerst, dann Warnungen, Tipps, Lob; Trainings-Hinweise mit Kategorie
    for x in out:
        x.setdefault("area", "Kraft" if x.get("exercises") or x.get("group") else "Gewohnheiten" if x.get("habit_id") else "Training")
    allx = recent[:1] + sorted(recent[1:] + out, key=lambda x: order[x["type"]]) if recent and recent[0].get("area") == "Gesamtbild" else sorted(recent + out, key=lambda x: order[x["type"]])
    return allx[:12]


def _fmt(v) -> str:
    return str(int(v)) if v is not None and float(v).is_integer() else f"{v:.1f}".replace(".", ",")


def _strength_week_streak(db: Session, user_id: int, today: date) -> int:
    days = {r[0] for r in db.execute(select(Workout.day).where(Workout.user_id == user_id, Workout.day >= today - timedelta(weeks=60)))}
    weeks = {d - timedelta(days=d.weekday()) for d in days}
    wk = today - timedelta(days=today.weekday())
    if wk not in weeks:
        wk -= timedelta(weeks=1)
    n = 0
    while wk in weeks:
        n += 1
        wk -= timedelta(weeks=1)
    return n


# ---------- Jüngste Veränderungen über alle Bereiche ----------

def _avg(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _split(db: Session, user, metric: str, today: date, recent: int = 7, base: int = 28):
    """Mittel der letzten `recent` Tage und der `base` Tage davor (ohne heute, der Tag läuft noch)."""
    from .store import daily_series
    end = today - timedelta(days=1)
    rows = {r["day"]: r["value"] for r in daily_series(db, user, metric, end - timedelta(days=recent + base - 1), end)}
    days = [(end - timedelta(days=i)).isoformat() for i in range(recent + base)]
    a = [rows.get(d) for d in days[:recent]]
    b = [rows.get(d) for d in days[recent:]]
    if sum(v is not None for v in a) < 3 or sum(v is not None for v in b) < 7:
        return None, None
    return _avg(a), _avg(b)


def _hm(minutes: float) -> str:
    m = round(abs(minutes))
    return f"{m // 60}:{m % 60:02d} h" if m >= 60 else f"{m} min"


def recent_changes(db: Session, user, today: date) -> list[dict]:
    """Was hat sich in der letzten Woche gegenüber den vier Wochen davor verändert, was bedeutet das, was tun?"""
    from .scores import Context
    out: list[dict] = []
    signals = {"sleep_short": False, "recovery_low": False, "load_high": False, "load_low": False}

    # --- Schlaf ---
    ctx = Context(db, user, today - timedelta(days=40), today)
    nights = [(today - timedelta(days=i)) for i in range(1, 8)]
    slept = [ctx.nights[d].asleep_min for d in nights if d in ctx.nights and ctx.nights[d].asleep_min]
    if len(slept) >= 4:
        needs = [ctx.need(d)["need"] for d in nights if d in ctx.nights and ctx.nights[d].asleep_min]
        debt = sum(max(0, n - s) for n, s in zip(needs, slept))
        a, b = _split(db, user, "sleep_duration", today)
        trend = f" ({'+' if a - b >= 0 else '−'}{_hm(a - b)} gegenüber den Wochen davor)" if a and b and abs(a - b) >= 10 else ""
        if debt >= 150:
            signals["sleep_short"] = True
            out.append({"type": "warn", "area": "Schlaf", "title": f"{_hm(debt)} Schlafschuld in 7 Nächten",
                        "text": f"Im Schnitt {_hm(_avg(slept))} pro Nacht bei einem Bedarf von {_hm(_avg(needs))}{trend}. "
                                "Fehlender Schlaf bremst Erholung, Muskelaufbau und Appetitregulation.",
                        "advice": "Die nächsten 3 Nächte je 30–45 min früher ins Bett; harte Einheiten erst danach.", "link": "/sleep"})
        elif debt <= 45:
            out.append({"type": "good", "area": "Schlaf", "title": "Schlafbedarf gedeckt",
                        "text": f"Durchschnittlich {_hm(_avg(slept))} pro Nacht{trend} – genug für deine Belastung.",
                        "advice": "Gute Basis für intensivere Einheiten.", "link": "/sleep"})
        bt = [ctx.nights[d].start for d in nights if d in ctx.nights and ctx.nights[d].start]
        if len(bt) >= 5:
            mins = [((t.hour * 60 + t.minute) + 720) % 1440 for t in bt]
            sd = (sum((m - _avg(mins)) ** 2 for m in mins) / (len(mins) - 1)) ** 0.5
            if sd > 60:
                out.append({"type": "tip", "area": "Schlaf", "title": "Unregelmäßige Schlafenszeiten",
                            "text": f"Deine Einschlafzeit schwankte diese Woche um rund ±{round(sd)} min. Ein unruhiger Rhythmus verschlechtert die Schlafqualität, auch bei gleicher Dauer.",
                            "advice": "Feste Zubettgehzeit, auch am Wochenende höchstens 1 h später.", "link": "/sleep"})

    # --- Erholung ---
    h7, h28 = _split(db, user, "hrv", today)
    r7, r28 = _split(db, user, "resting_hr", today)
    parts = []
    if h7 and h28:
        hc = (h7 - h28) / h28
        if hc <= -0.08:
            parts.append(f"HRV {round(-hc * 100)} % niedriger")
        elif hc >= 0.08:
            parts.append(f"HRV {round(hc * 100)} % höher")
    if r7 and r28 and abs(r7 - r28) >= 2:
        parts.append(f"Ruhepuls {'+' if r7 > r28 else '−'}{round(abs(r7 - r28))} bpm")
    if parts:
        worse = (h7 and h28 and h7 < h28 * 0.92) or (r7 and r28 and r7 >= r28 + 2)
        signals["recovery_low"] = bool(worse)
        out.append({"type": "warn" if worse else "good", "area": "Erholung",
                    "title": "Erholung lässt nach" if worse else "Bessere Erholung",
                    "text": ", ".join(parts) + " als in den vier Wochen davor. "
                            + ("Das Nervensystem steht unter mehr Stress – durch Training, wenig Schlaf, Alkohol, Infekt oder Alltag."
                               if worse else "Dein Körper verkraftet die aktuelle Belastung gut."),
                    "advice": "Ein bis zwei lockere Tage, viel trinken, früh schlafen; bei Krankheitsgefühl ganz pausieren." if worse
                    else "Guter Zeitpunkt, die Belastung behutsam zu steigern.", "link": "/health"})

    # --- Belastung ---
    acwr = ctx.acwr(today - timedelta(days=1))
    if acwr is not None:
        if acwr >= 1.4:
            signals["load_high"] = True
            out.append({"type": "warn", "area": "Belastung", "title": f"Belastung stark gestiegen ({acwr:.1f}×)".replace(".", ","),
                        "text": "Die letzte Woche war deutlich härter als dein Schnitt der vier Wochen davor. Sprünge über das 1,3-Fache erhöhen das Verletzungs- und Überlastungsrisiko.",
                        "advice": "Diese Woche nicht weiter steigern; eine Einheit durch lockere Ausdauer ersetzen.", "link": "/activities"})
        elif acwr <= 0.7:
            signals["load_low"] = True
            out.append({"type": "tip", "area": "Belastung", "title": "Deutlich weniger Training als üblich",
                        "text": f"Nur etwa {round(acwr * 100)} % deiner üblichen Wochenbelastung. Nach 2–3 Wochen beginnt die Fitness spürbar zu sinken.",
                        "advice": "Wenn es keine geplante Pause ist: zwei kurze Einheiten fest einplanen.", "link": "/activities"})
        elif 0.9 <= acwr <= 1.3:
            out.append({"type": "good", "area": "Belastung", "title": "Belastung im grünen Bereich",
                        "text": f"Die letzte Woche lag beim {acwr:.1f}-Fachen deines Schnitts – genug Reiz ohne Überlastung.".replace(".", ",", 1),
                        "link": "/activities"})

    # Sportarten-Verschiebung
    acts = db.execute(select(Activity.sport, Activity.day, Activity.moving_s, Activity.duration_s).where(
        Activity.user_id == user.id, Activity.duplicate_of.is_(None), Activity.day >= today - timedelta(days=35), Activity.day < today)).all()
    if acts:
        from .sports import SPORTS
        cur, prev = {}, {}
        for sport, d, mv, du in acts:
            m = (mv or du or 0) / 60
            tgt = cur if d >= today - timedelta(days=7) else prev
            tgt[sport] = tgt.get(sport, 0) + m
        for sport in set(cur) | set(prev):
            c, p = cur.get(sport, 0), prev.get(sport, 0) / 4
            if sport != "walk" and p >= 45 and c < p * 0.3:
                out.append({"type": "tip", "area": "Aktivität", "title": f"Kaum noch {SPORTS.get(sport, sport)}",
                            "text": f"Diese Woche {round(c)} min statt sonst etwa {round(p)} min pro Woche.",
                            "advice": "Bewusst pausiert? Sonst eine kurze Einheit einplanen, damit die Gewöhnung nicht verloren geht."})
            elif sport != "walk" and c >= 60 and c > max(p, 20) * 2:
                out.append({"type": "good", "area": "Aktivität", "title": f"Mehr {SPORTS.get(sport, sport)}",
                            "text": f"{round(c)} min diese Woche, sonst etwa {round(p)} min pro Woche.",
                            "advice": "Neue Reize lieber über 2–3 Wochen steigern, damit Sehnen und Gelenke mitkommen."})

    s7, s28 = _split(db, user, "steps", today)
    if s7 and s28 and abs(s7 - s28) / s28 >= 0.2:
        up = s7 > s28
        out.append({"type": "good" if up else "tip", "area": "Aktivität",
                    "title": f"{'Mehr' if up else 'Weniger'} Schritte: {round(s7):,} statt {round(s28):,} am Tag".replace(",", "."),
                    "text": "Alltagsbewegung zählt für Herz und Stoffwechsel fast so viel wie Training." if not up else "Mehr Alltagsbewegung verbessert Erholung und Stoffwechsel.",
                    "advice": None if up else "Kurze Spaziergänge nach dem Essen oder Telefonate im Gehen."})

    # --- Ernährung ---
    k7, k28 = _split(db, user, "calories_in", today)
    p7, _ = _split(db, user, "protein", today)
    w7, w28 = _split(db, user, "weight", today, 7, 21)
    if k7 and k28 and abs(k7 - k28) >= 200:
        out.append({"type": "tip", "area": "Ernährung", "title": f"{'Mehr' if k7 > k28 else 'Weniger'} gegessen: {round(k7)} statt {round(k28)} kcal",
                    "text": ("Weniger Energie bei gleicher oder höherer Belastung bremst Erholung und Leistung."
                             if k7 < k28 and (signals["load_high"] or signals["recovery_low"]) else
                             "Die Energiezufuhr hat sich spürbar verändert" + (f"; das Gewicht {'steigt' if w7 > w28 else 'sinkt'} um {abs(w7 - w28):.1f} kg.".replace(".", ",", 1) if w7 and w28 and abs(w7 - w28) >= 0.4 else ".")),
                    "advice": "An harten Tagen mehr Kohlenhydrate, an ruhigen Tagen weniger." , "link": "/metric/calories_in"})
    if p7:
        w = w7 or w28
        if w:
            gpk = p7 / w
            trains = bool(acts) or db.scalar(select(func.count()).select_from(Workout).where(Workout.user_id == user.id, Workout.day >= today - timedelta(days=14)))
            if trains and gpk < 1.4:
                out.append({"type": "tip", "area": "Ernährung", "title": f"Wenig Eiweiß: {gpk:.1f} g/kg".replace(".", ","),
                            "text": f"Im Schnitt {round(p7)} g pro Tag. Für Training und Muskelerhalt empfehlen Studien 1,6–2,2 g pro kg Körpergewicht.",
                            "advice": f"Ziel etwa {round(w * 1.6)} g: zu jeder Mahlzeit eine Eiweißquelle (Quark, Eier, Hülsenfrüchte, Fisch).", "link": "/metric/calories_in"})
            elif trains and gpk >= 1.6:
                out.append({"type": "good", "area": "Ernährung", "title": f"Eiweiß passt: {gpk:.1f} g/kg".replace(".", ","),
                            "text": "Genug für Muskelaufbau und Erholung.", "link": "/metric/calories_in"})
    wa7, wa28 = _split(db, user, "water", today)
    if wa7 and wa7 < 1500 and (signals["load_high"] or signals["recovery_low"]):
        out.append({"type": "tip", "area": "Ernährung", "title": "Wenig getrunken",
                    "text": f"Nur etwa {wa7 / 1000:.1f} l am Tag bei hoher Belastung.".replace(".", ","),
                    "advice": "2–3 l, an Trainingstagen etwas mehr."})

    # --- Gesamtbild ---
    if signals["load_high"] and (signals["recovery_low"] or signals["sleep_short"]):
        out.insert(0, {"type": "warn", "area": "Gesamtbild", "title": "Mehr Belastung als Erholung",
                       "text": "Die Belastung ist gestiegen, während " + (" und ".join(x for x, f in [("die Erholungswerte sinken", signals["recovery_low"]), ("Schlaf fehlt", signals["sleep_short"])] if f))
                               + ". Diese Kombination geht einer Überlastung oder einem Infekt oft voraus.",
                       "advice": "2–3 Tage nur locker, Schlaf nachholen, dann neu bewerten."})
    elif signals["sleep_short"] and signals["recovery_low"]:
        out.insert(0, {"type": "warn", "area": "Gesamtbild", "title": "Schlaf fehlt und die Erholung leidet",
                       "text": "Kurzer Schlaf und sinkende HRV hängen eng zusammen – das Training ist hier nicht die Ursache.",
                       "advice": "Schlaf zuerst: früher ins Bett, Bildschirme und Alkohol abends reduzieren."})
    return out
