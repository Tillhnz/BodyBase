"""Körperzusammensetzung je Segment und ihr Zusammenhang mit dem Training.

Withings liefert Muskel-, Fett- und fettfreie Masse je Segment mit einem Segment-Code. Welcher Code welcher Körperteil
ist, ist nicht öffentlich dokumentiert. BodyBase ordnet deshalb nach Größe zu (größter Wert = Rumpf, die nächsten zwei =
Beine, die kleinsten zwei = Arme); unter Gesundheit lässt sich das je Code ändern (gespeichert in prefs.segment_labels).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BodySegment, User
from .timeutil import local_day

KINDS = {"muscle": "Muskelmasse", "fat": "Fettmasse", "ffm": "Fettfreie Masse"}
PARTS = {"torso": "Rumpf", "left_arm": "Linker Arm", "right_arm": "Rechter Arm", "left_leg": "Linkes Bein",
         "right_leg": "Rechtes Bein", "arm": "Arm", "leg": "Bein", "ignore": "Nicht verwenden"}
REGION = {"torso": "Rumpf", "left_arm": "Arme", "right_arm": "Arme", "arm": "Arme", "left_leg": "Beine", "right_leg": "Beine",
          "leg": "Beine"}
REGION_MUSCLES = {
    "Arme": {"biceps": 1, "triceps": 1, "forearms": 1, "shoulders": 0.5},
    "Beine": {"quads": 1, "hamstrings": 1, "glutes": 1, "calves": 1, "adductors": 1, "abductors": 1},
    "Rumpf": {"chest": 1, "abs": 1, "lats": 1, "upper_back": 1, "lower_back": 1, "traps": 1, "shoulders": 0.5},
}


def store(db: Session, user_id: int, source: str, ts: datetime, kind: str, position: int, value: float) -> None:
    row = db.scalar(select(BodySegment).where(BodySegment.user_id == user_id, BodySegment.source == source,
                                              BodySegment.ts == ts, BodySegment.kind == kind, BodySegment.position == position))
    if row is None:
        db.add(BodySegment(user_id=user_id, source=source, ts=ts, day=local_day(ts), kind=kind, position=position, value=value))
    else:
        row.value = value


def auto_labels(rows: list[BodySegment]) -> dict[int, str]:
    """Zuordnung nach Größe der Muskelmasse (Mittel je Code)."""
    vals: dict[int, list] = defaultdict(list)
    for r in rows:
        if r.kind in ("muscle", "ffm"):
            vals[r.position].append(r.value)
    if not vals:
        vals = defaultdict(list, {r.position: [r.value] for r in rows})
    order = sorted(vals, key=lambda p: -sum(vals[p]) / len(vals[p]))
    out = {}
    for i, pos in enumerate(order):
        if i == 0:
            out[pos] = "torso"
        elif i <= 2 or len(order) < 5:
            out[pos] = "leg"
        else:
            out[pos] = "arm"
    return out


def labels_for(user: User, rows: list) -> tuple[dict[int, str], bool]:
    auto = auto_labels(rows)
    custom = {int(k): v for k, v in ((user.prefs or {}).get("segment_labels") or {}).items() if v in PARTS}
    return {**auto, **custom}, bool(custom)


def overview(db: Session, user: User, days: int, today_: date) -> dict:
    from .strength import body_load
    rows = db.scalars(select(BodySegment).where(BodySegment.user_id == user.id).order_by(BodySegment.ts)).all()
    if not rows:
        return {"has_data": False}
    labels, custom = labels_for(user, rows)
    start = today_ - timedelta(days=days - 1)
    # je Code und Art: Verlauf (ein Wert je Tag)
    series: dict[str, dict[int, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        series[r.kind][r.position][r.day.isoformat()] = r.value
    segments = []
    for pos in sorted({r.position for r in rows}):
        part = labels.get(pos, "ignore")
        item = {"position": pos, "part": part, "label": PARTS.get(part, f"Segment {pos}"), "region": REGION.get(part)}
        for kind in KINDS:
            pts = sorted(series[kind].get(pos, {}).items())
            if not pts:
                continue
            in_range = [p for p in pts if p[0] >= start.isoformat()]
            first = in_range[0] if in_range else None
            item[kind] = {"last": pts[-1][1], "last_day": pts[-1][0], "first": first[1] if first else None,
                          "change": round(pts[-1][1] - first[1], 2) if first and len(in_range) > 1 else None,
                          "series": [{"day": d, "value": v} for d, v in pts if d >= (start - timedelta(days=days)).isoformat()]}
        segments.append(item)
    # je Region: Summe der Segmente und Trainingsbelastung im Zeitraum
    load = {m["muscle"]: m["value"] for m in body_load(db, user.id, days, today_)["muscles"]}
    regions = []
    for region, weights in REGION_MUSCLES.items():
        segs = [s for s in segments if s["region"] == region and "muscle" in s]
        if not segs:
            continue
        last = sum(s["muscle"]["last"] for s in segs)
        changes = [s["muscle"]["change"] for s in segs]
        change = round(sum(changes), 2) if all(c is not None for c in changes) else None
        points = round(sum(load.get(m, 0) * w for m, w in weights.items()), 1)
        regions.append({"region": region, "muscle_kg": round(last, 2), "change_kg": change,
                        "change_pct": round(change / (last - change) * 100, 1) if change is not None and last - change else None,
                        "load": points, "comment": _comment(region, change, points, days)})
    return {"has_data": True, "days": days, "segments": segments, "regions": regions, "custom_labels": custom,
            "parts": PARTS, "kinds": KINDS, "measurements": len({r.day for r in rows})}


def _comment(region: str, change: float | None, load: float, days: int) -> str:
    per_week = load / max(1, days / 7)
    if change is None:
        return "Für einen Vergleich braucht es mindestens zwei Messungen im Zeitraum."
    up, down = change >= 0.1, change <= -0.1
    if up and per_week >= 4:
        return f"Mehr Muskelmasse, und {region} wurden regelmäßig trainiert (etwa {per_week:.0f} Punkte pro Woche). Das Training kommt an."
    if up:
        return "Mehr Muskelmasse, obwohl wenig gezielt trainiert wurde. Ernährung, Alltag oder Messschwankungen können mitspielen."
    if down and per_week < 3:
        return f"Weniger Muskelmasse bei wenig Training für {region}. Zwei, drei Einheiten pro Woche würden gegensteuern."
    if down:
        return "Weniger Muskelmasse trotz Training. Prüfe Eiweiß, Schlaf und Erholung; einzelne Messungen schwanken auch durch Wasser."
    if per_week >= 4:
        return "Stabil bei regelmäßigem Training. Für Zuwachs helfen schrittweise mehr Gewicht oder mehr Sätze."
    return "Stabil."
