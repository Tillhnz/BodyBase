"""Heatmap aller Strecken und Explorer-Kacheln (wie bei VeloViewer/StatsHunters).

Die Welt wird auf Zoomstufe 14 in Kacheln geteilt (in Mitteleuropa etwa 1,5 × 1,5 km). Jede Kachel, durch die eine
Strecke führt, gilt als entdeckt – mit dem Tag der ersten Aktivität dort. Dazu:
- größtes Quadrat: das größte k × k-Feld, in dem alle Kacheln entdeckt sind;
- größter Cluster: zusammenhängende Kacheln, deren vier Nachbarn alle entdeckt sind;
- nächstes Ziel: die Kacheln, die zum nächstgrößeren Quadrat fehlen.
"""
from __future__ import annotations

import math
import threading
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .importers.polyline import decode, encode
from .models import Activity, User

ZOOM = 14
N = 2 ** ZOOM
STEP_M = 150  # Abstand der Zwischenpunkte, damit keine Kachel übersprungen wird
_cache: dict = {}
_lock = threading.Lock()


def tile_of(lat: float, lon: float) -> tuple[int, int]:
    lat = max(-85.05, min(85.05, lat))
    x = int((lon + 180.0) / 360.0 * N)
    r = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * N)
    return min(max(x, 0), N - 1), min(max(y, 0), N - 1)


def tile_bounds(x: int, y: int) -> list[list[float]]:
    def lat(yy):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / N))))
    return [[lat(y + 1), x / N * 360 - 180], [lat(y), (x + 1) / N * 360 - 180]]


def _dist(a, b) -> float:
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    return 6371000 * math.hypot(dlat, dlon)


def route_tiles(pts: list[tuple[float, float]]) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for i, p in enumerate(pts):
        out.add(tile_of(*p))
        if i:
            q = pts[i - 1]
            d = _dist(q, p)
            if d > STEP_M:
                n = int(d // STEP_M)
                for k in range(1, n + 1):
                    f = k / (n + 1)
                    out.add(tile_of(q[0] + (p[0] - q[0]) * f, q[1] + (p[1] - q[1]) * f))
    return out


def _simplify(pts: list[tuple[float, float]], max_points: int = 400) -> list[tuple[float, float]]:
    if len(pts) <= max_points:
        return pts
    step = len(pts) / max_points
    out = [pts[int(i * step)] for i in range(max_points)]
    out.append(pts[-1])
    return out


def _load(db: Session, user: User) -> list[dict]:
    """Alle Aktivitäten mit Strecke, dekodiert und mit Kacheln – zwischengespeichert, bis sich etwas ändert."""
    sig = db.execute(select(func.count(), func.max(Activity.id), func.sum(func.length(Activity.polyline))).where(
        Activity.user_id == user.id, Activity.polyline.isnot(None), Activity.duplicate_of.is_(None))).one()
    key = (user.id, tuple(sig))
    with _lock:
        hit = _cache.get(user.id)
        if hit and hit[0] == key:
            return hit[1]
    rows = db.execute(select(Activity.id, Activity.sport, Activity.day, Activity.name, Activity.distance_m, Activity.polyline).where(
        Activity.user_id == user.id, Activity.polyline.isnot(None), Activity.duplicate_of.is_(None)).order_by(Activity.start)).all()
    acts = []
    for aid, sport, day, name, dist, poly in rows:
        try:
            pts = decode(poly)
        except Exception:  # noqa: BLE001 - kaputte Strecke überspringen
            continue
        pts = [p for p in pts if abs(p[0]) > 0.01 or abs(p[1]) > 0.01]
        if len(pts) < 2:
            continue
        acts.append({"id": aid, "sport": sport, "day": day, "name": name, "km": round((dist or 0) / 1000, 1),
                     "poly": encode(_simplify(pts)), "tiles": route_tiles(pts), "start": pts[0]})
    with _lock:
        _cache[user.id] = (key, acts)
    return acts


def _max_square(tiles: set) -> tuple[int, tuple[int, int] | None]:
    """Größtes vollständig entdecktes Quadrat (dynamische Programmierung über die sortierten Kacheln)."""
    best, at = 0, None
    size: dict[tuple[int, int], int] = {}
    for x, y in sorted(tiles, key=lambda t: (t[1], t[0])):
        s = 1 + min(size.get((x - 1, y), 0), size.get((x, y - 1), 0), size.get((x - 1, y - 1), 0))
        size[(x, y)] = s
        if s > best:
            best, at = s, (x - s + 1, y - s + 1)
    return best, at


def _max_cluster(tiles: set) -> set:
    inner = {(x, y) for x, y in tiles if {(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)} <= tiles}
    seen, best = set(), set()
    for t in inner:
        if t in seen:
            continue
        comp, stack = set(), [t]
        seen.add(t)
        while stack:
            x, y = stack.pop()
            comp.add((x, y))
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in inner and n not in seen:
                    seen.add(n)
                    stack.append(n)
        if len(comp) > len(best):
            best = comp
    return best


def _next_square(tiles: set, k: int, at: tuple[int, int] | None) -> list[tuple[int, int]]:
    """Fehlende Kacheln für ein Quadrat der Größe k+1 – die Lage mit den wenigsten Lücken nahe dem aktuellen Quadrat."""
    if not at:
        return []
    size = k + 1
    best = None
    for ox in range(at[0] - size, at[0] + k + 1):
        for oy in range(at[1] - size, at[1] + k + 1):
            miss = [(x, y) for x in range(ox, ox + size) for y in range(oy, oy + size) if (x, y) not in tiles]
            if best is None or len(miss) < len(best):
                best = miss
    return best or []


def overview(db: Session, user: User, sports: list[str] | None, year_from: int | None, year_to: int | None, highlight: int | None = None) -> dict:
    acts = _load(db, user)
    all_sports = sorted({a["sport"] for a in acts})
    years = sorted({a["day"].year for a in acts})
    sel = [a for a in acts if (not sports or a["sport"] in sports)]
    upto = [a for a in sel if not year_to or a["day"].year <= year_to]
    shown = [a for a in upto if not year_from or a["day"].year >= year_from]

    first: dict[tuple[int, int], date] = {}
    for a in upto:
        for t in a["tiles"]:
            if t not in first:
                first[t] = a["day"]
    tiles = set(first)
    sq, at = _max_square(tiles)
    cluster = _max_cluster(tiles)
    target = _next_square(tiles, sq, at)

    per_month: dict[str, int] = defaultdict(int)
    for d in first.values():
        per_month[f"{d.year}-{d.month:02d}"] += 1
    timeline, total = [], 0
    for m in sorted(per_month):
        total += per_month[m]
        timeline.append({"month": m, "new": per_month[m], "total": total})
    per_year: dict[int, int] = defaultdict(int)
    for d in first.values():
        per_year[d.year] += 1

    # Startpunkt am häufigsten = Zuhause; unentdeckte Kacheln im Umkreis von 10 km als Anreiz
    home = None
    if upto:
        cnt: dict[tuple[int, int], int] = defaultdict(int)
        for a in upto:
            cnt[tile_of(*a["start"])] += 1
        home = max(cnt, key=cnt.get)
    near_total = near_done = 0
    if home:
        r = 6
        for x in range(home[0] - r, home[0] + r + 1):
            for y in range(home[1] - r, home[1] + r + 1):
                if (x - home[0]) ** 2 + (y - home[1]) ** 2 <= r * r:
                    near_total += 1
                    near_done += (x, y) in tiles

    hl = highlight or year_from
    t_from = date(hl, 1, 1) if hl else None
    km = sum(a["km"] for a in shown)
    return {
        "sports": all_sports, "years": years,
        "routes": [{"id": a["id"], "sport": a["sport"], "day": a["day"].isoformat(), "name": a["name"], "km": a["km"], "poly": a["poly"]} for a in shown],
        "tiles": [{"x": x, "y": y, "day": d.isoformat(), "new": bool(t_from and t_from.year == d.year), "b": tile_bounds(x, y)} for (x, y), d in first.items()],
        "square": {"size": sq, "b": [tile_bounds(at[0], at[1] + sq - 1)[0], tile_bounds(at[0] + sq - 1, at[1])[1]] if at else None},
        "cluster": len(cluster), "cluster_tiles": [tile_bounds(x, y) for x, y in cluster] if len(cluster) <= 4000 else [],
        "target": {"size": sq + 1, "missing": [tile_bounds(x, y) for x, y in target][:200], "count": len(target)},
        "timeline": timeline, "per_year": [{"year": y, "new": per_year[y]} for y in sorted(per_year)],
        "near": {"done": near_done, "total": near_total, "home": tile_bounds(*home) if home else None},
        "stats": {"tiles": len(tiles), "activities": len(shown), "km": round(km), "new_in_range": sum(1 for d in first.values() if t_from and d.year == t_from.year)},
    }
