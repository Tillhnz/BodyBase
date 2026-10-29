from ..store import ActivityIn, SleepIn
from ..timeutil import parse_date, parse_iso
from .base import Field, OAuthSpec, Provider, num

API = "https://api.fitbit.com"


class Fitbit(Provider):
    key = "fitbit"
    name = "Fitbit"
    color = "#00b0b9"
    initials = "Fb"
    website = "https://www.fitbit.com"
    delivers = ["activity", "sleep", "heart", "body", "workouts"]
    summary = "Schritte, Ruhepuls, HRV, Schlafphasen, SpO₂, Atemfrequenz, VO₂max, Gewicht und Trainings."
    setup = ["Auf „Verbinden“ klicken, mit dem Fitbit- bzw. Google-Konto anmelden und alle Bereiche erlauben."]
    app_setup = [
        "Auf https://dev.fitbit.com/apps/new eine App anlegen.",
        "OAuth 2.0 Application Type: „Personal“ (nur dein Konto, erlaubt Detaildaten) oder „Server“.",
        "Redirect URL: die unten angezeigte Rücksprung-Adresse eintragen.",
        "OAuth 2.0 Client ID und Client Secret hier eintragen.",
    ]
    app_fields = [Field("client_id", "OAuth 2.0 Client ID"), Field("client_secret", "Client Secret", "password", secret=True)]
    oauth = OAuthSpec(
        "https://www.fitbit.com/oauth2/authorize", f"{API}/oauth2/token",
        ["activity", "heartrate", "sleep", "weight", "profile", "oxygen_saturation", "respiratory_rate", "cardio_fitness", "temperature"],
        pkce=True, token_auth="basic",
    )
    note = "Fitbit erlaubt 150 Anfragen pro Stunde. Der erste Abgleich großer Zeiträume verteilt sich daher auf mehrere Durchläufe."

    def after_token(self, ctx, token):
        try:
            prof = ctx.get(f"{API}/1/user/-/profile.json") or {}
            return (prof.get("user") or {}).get("displayName")
        except Exception:
            return None

    def _series(self, ctx, path: str, chunk: int):
        for a, b in ctx.days(chunk):
            yield ctx.get(f"{API}{path.format(start=a.isoformat(), end=b.isoformat())}") or {}

    def sync(self, ctx):
        w = ctx.writer
        # Tageswerte der Aktivität (max. 1 Jahr pro Abfrage)
        for res, metric in (("steps", "steps"), ("activityCalories", "active_energy"), ("caloriesOut", "total_energy"),
                            ("distance", "distance"), ("floors", "floors")):
            for data in self._series(ctx, f"/1/user/-/activities/{res}/date/{{start}}/{{end}}.json", 365):
                for item in data.get(f"activities-{res}", []):
                    w.daily(metric, parse_date(item.get("dateTime")), item.get("value"))
        active: dict = {}
        for res in ("minutesVeryActive", "minutesFairlyActive"):
            for data in self._series(ctx, f"/1/user/-/activities/{res}/date/{{start}}/{{end}}.json", 365):
                for item in data.get(f"activities-{res}", []):
                    d = parse_date(item.get("dateTime"))
                    active[d] = active.get(d, 0) + (num(item.get("value")) or 0)
        for d, v in active.items():
            w.daily("active_minutes", d, v)
        # Ruhepuls
        for data in self._series(ctx, "/1/user/-/activities/heart/date/{start}/{end}.json", 365):
            for item in data.get("activities-heart", []):
                w.daily("resting_hr", parse_date(item.get("dateTime")), (item.get("value") or {}).get("restingHeartRate"))
        # HRV, SpO2, Atemfrequenz, VO2max (30 Tage pro Abfrage)
        for data in self._series(ctx, "/1/user/-/hrv/date/{start}/{end}.json", 30):
            for item in data.get("hrv", []):
                w.daily("hrv", parse_date(item.get("dateTime")), (item.get("value") or {}).get("dailyRmssd"))
        for data in self._series(ctx, "/1/user/-/spo2/date/{start}/{end}.json", 30):
            for item in data if isinstance(data, list) else []:
                w.daily("spo2", parse_date(item.get("dateTime")), (item.get("value") or {}).get("avg"))
        for data in self._series(ctx, "/1/user/-/br/date/{start}/{end}.json", 30):
            for item in data.get("br", []):
                w.daily("respiratory_rate", parse_date(item.get("dateTime")), (item.get("value") or {}).get("breathingRate"))
        for data in self._series(ctx, "/1/user/-/cardioscore/date/{start}/{end}.json", 30):
            for item in data.get("cardioScore", []):
                w.daily("vo2max", parse_date(item.get("dateTime")), vo2_range((item.get("value") or {}).get("vo2Max")))
        # Gewicht und Körperfett (31 Tage pro Abfrage)
        for data in self._series(ctx, "/1/user/-/body/log/weight/date/{start}/{end}.json", 31):
            for item in data.get("weight", []):
                ts = parse_iso(f"{item.get('date')} {item.get('time') or '08:00:00'}")  # Ortszeit des Kontos
                w.sample("weight", ts, item.get("weight"))
                w.sample("bmi", ts, item.get("bmi"))
                if item.get("fat") is not None:
                    w.sample("body_fat", ts, item.get("fat"))
        # Schlaf (100 Tage pro Abfrage)
        for data in self._series(ctx, "/1.2/user/-/sleep/date/{start}/{end}.json", 100):
            for s in data.get("sleep", []):
                w.sleep(map_sleep(s))
        # Trainings
        after = ctx.since_date.isoformat()
        offset = 0
        while offset < 2000:
            data = ctx.get(f"{API}/1/user/-/activities/list.json",
                           params={"afterDate": after, "sort": "asc", "limit": 100, "offset": offset}) or {}
            items = data.get("activities", [])
            for a in items:
                w.activity(map_activity(a))
            if len(items) < 100:
                break
            offset += 100


def vo2_range(value) -> float | None:
    """Fitbit liefert VO2max oft als Spanne ("44-48")."""
    if value is None:
        return None
    s = str(value)
    if "-" in s:
        parts = [num(p) for p in s.split("-")]
        parts = [p for p in parts if p is not None]
        return sum(parts) / len(parts) if parts else None
    return num(s)


def map_sleep(s: dict) -> SleepIn:
    summary = ((s.get("levels") or {}).get("summary") or {})

    def minutes(stage):
        return (summary.get(stage) or {}).get("minutes")
    stages = s.get("type") == "stages"
    return SleepIn(
        source_id=str(s.get("logId")),
        start=parse_iso(s.get("startTime")),
        end=parse_iso(s.get("endTime")),
        asleep_min=num(s.get("minutesAsleep")),
        deep_min=minutes("deep") if stages else None,
        rem_min=minutes("rem") if stages else None,
        light_min=minutes("light") if stages else None,
        awake_min=minutes("wake") if stages else num(s.get("minutesAwake")),
        efficiency=num(s.get("efficiency")),
        nap=not s.get("isMainSleep", True),
    )


def map_activity(a: dict) -> ActivityIn:
    dist = num(a.get("distance"))
    unit = (a.get("distanceUnit") or "Kilometer").lower()
    if dist is not None:
        dist = dist * (1609.344 if unit.startswith("mile") else 1000.0)
    return ActivityIn(
        source_id=str(a.get("logId")),
        start=parse_iso(a.get("startTime")),
        sport_raw=a.get("activityName"),
        name=a.get("activityName"),
        duration_s=(num(a.get("duration")) or 0) / 1000 or None,
        moving_s=(num(a.get("activeDuration")) or 0) / 1000 or None,
        distance_m=dist,
        elevation_m=num(a.get("elevationGain")),
        calories=num(a.get("calories")),
        avg_hr=num(a.get("averageHeartRate")),
    )
