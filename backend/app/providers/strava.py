from ..store import ActivityIn
from ..timeutil import parse_iso
from .base import Field, OAuthSpec, Provider, epoch, num

API = "https://www.strava.com/api/v3"


class Strava(Provider):
    key = "strava"
    name = "Strava"
    color = "#fc5200"
    initials = "St"
    website = "https://www.strava.com"
    delivers = ["workouts"]
    summary = "Alle Aktivitäten mit Strecke, Puls, Leistung und Karte. Fast jede Uhr und App kann zu Strava hochladen."
    setup = ["Auf „Verbinden“ klicken und bei Strava den Zugriff auf „Aktivitäten (auch private)“ erlauben."]
    app_setup = [
        "Bei Strava anmelden und https://www.strava.com/settings/api öffnen.",
        "Eine App anlegen. Als „Authorization Callback Domain“ nur den Hostnamen deiner BodyBase-Adresse eintragen (ohne http:// und Port).",
        "Client ID und Client Secret hier eintragen.",
    ]
    app_fields = [Field("client_id", "Client ID"), Field("client_secret", "Client Secret", "password", secret=True)]
    oauth = OAuthSpec("https://www.strava.com/oauth/authorize", "https://www.strava.com/oauth/token",
                      ["read", "activity:read_all"], scope_sep=",", extra_authorize={"approval_prompt": "auto"})
    note = "Strava erlaubt neuen Apps anfangs nur einen verbundenen Sportler (dich). Für mehr Nutzer musst du bei Strava eine Erhöhung beantragen."

    def after_token(self, ctx, token):
        athlete = token.get("athlete") or {}
        token.pop("athlete", None)
        name = " ".join(x for x in (athlete.get("firstname"), athlete.get("lastname")) if x)
        return name or None

    def sync(self, ctx):
        after = epoch(ctx.since)
        page = 1
        while page <= 50:
            items = ctx.get(f"{API}/athlete/activities", params={"after": after, "per_page": 100, "page": page}) or []
            for a in items:
                ctx.writer.activity(map_activity(a))
            if len(items) < 100:
                break
            page += 1


def map_activity(a: dict) -> ActivityIn:
    return ActivityIn(
        source_id=str(a.get("id")),
        start=parse_iso(a.get("start_date")),
        sport_raw=a.get("sport_type") or a.get("type"),
        name=a.get("name"),
        duration_s=num(a.get("elapsed_time")),
        moving_s=num(a.get("moving_time")),
        distance_m=num(a.get("distance")),
        elevation_m=num(a.get("total_elevation_gain")),
        calories=num(a.get("calories")) or num(a.get("kilojoules")),  # Radfahren: kJ Arbeit entsprechen etwa kcal Verbrauch
        avg_hr=num(a.get("average_heartrate")),
        max_hr=num(a.get("max_heartrate")),
        avg_power=num(a.get("average_watts")),
        load=num(a.get("suffer_score")),
        polyline=(a.get("map") or {}).get("summary_polyline") or None,
    )
