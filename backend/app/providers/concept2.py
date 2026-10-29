from ..store import ActivityIn
from ..timeutil import parse_iso
from .base import Field, OAuthSpec, Provider, num

API = "https://log.concept2.com/api"
KIND = {"rower": "Rowing (Concept2)", "skierg": "SkiErg", "bike": "BikeErg", "dynamic": "Rowing (Dynamic)", "slides": "Rowing (Slides)",
        "paddle": "PaddleErg", "water": "Rowing (water)", "snow": "Nordic skiing", "rollerski": "Rollerski", "multierg": "MultiErg"}


class Concept2(Provider):
    key = "concept2"
    name = "Concept2 Logbook"
    color = "#2c64b4"
    initials = "C2"
    website = "https://log.concept2.com"
    delivers = ["workouts"]
    summary = "Einheiten auf RowErg, SkiErg und BikeErg aus dem Concept2 Logbook (ErgData, PM5)."
    setup = ["Auf „Verbinden“ klicken und beim Concept2 Logbook den Zugriff erlauben."]
    app_setup = [
        "Auf https://log.concept2.com/developers/keys einen API-Schlüssel (Anwendung) anlegen.",
        "Als Redirect URI die unten angezeigte Rücksprung-Adresse eintragen, Bereiche user:read und results:read.",
        "Client ID und Client Secret hier eintragen.",
    ]
    app_fields = [Field("client_id", "Client ID"), Field("client_secret", "Client Secret", "password", secret=True)]
    oauth = OAuthSpec("https://log.concept2.com/oauth/authorize", "https://log.concept2.com/oauth/access_token",
                      ["user:read", "results:read"], scope_sep=",")

    def after_token(self, ctx, token):
        try:
            u = (ctx.get(f"{API}/users/me", headers={"Accept": "application/vnd.c2logbook.v1+json"}) or {}).get("data") or {}
            return u.get("username")
        except Exception:
            return None

    def sync(self, ctx):
        page = 1
        while page <= 50:
            data = ctx.get(f"{API}/users/me/results", params={"from": ctx.since_date.isoformat(), "page": page},
                           headers={"Accept": "application/vnd.c2logbook.v1+json"}) or {}
            for r in data.get("data", []):
                ctx.writer.activity(map_result(r))
            pag = ((data.get("meta") or {}).get("pagination") or {})
            if not pag or page >= (pag.get("total_pages") or 1):
                break
            page += 1


def map_result(r: dict) -> ActivityIn:
    hr = r.get("heart_rate") or {}
    kind = KIND.get(r.get("type"), "Rowing")
    date = str(r.get("date") or "")
    tz = r.get("timezone")
    start = parse_iso(date)
    if tz and start is not None:
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            local = datetime.fromisoformat(date.replace(" ", "T")).replace(tzinfo=ZoneInfo(tz))
            start = parse_iso(local)
        except Exception:
            pass
    return ActivityIn(
        source_id=str(r.get("id")), start=start, sport_raw=kind, name=kind,
        duration_s=(num(r.get("time")) or 0) / 10 or None, distance_m=num(r.get("distance")),
        calories=num(r.get("calories_total")), avg_hr=num(hr.get("average")), max_hr=num(hr.get("max")),
    )
