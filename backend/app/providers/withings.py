from datetime import datetime, timezone

from ..store import ActivityIn, SleepIn
from ..timeutil import parse_date
from .base import AuthError, Field, OAuthSpec, Provider, RateLimited, SyncError, epoch, num

API = "https://wbsapi.withings.net"

# Messarten von Withings -> eigene Metrik (Faktor für die Umrechnung)
MEASURE_TYPES = {
    1: ("weight", 1), 5: ("lean_mass", 1), 6: ("body_fat", 1), 8: (None, 1), 9: ("bp_diastolic", 1), 10: ("bp_systolic", 1),
    11: ("heart_rate", 1), 54: ("spo2", 1), 71: ("body_temp", 1), 73: ("body_temp", 1), 76: ("muscle_mass", 1),
    77: (None, 1), 88: ("bone_mass", 1), 123: ("vo2max", 1), 170: ("visceral_fat", 1),
}

WORKOUT_CATEGORIES = {
    1: "Walk", 2: "Run", 3: "Hiking", 4: "Skating", 5: "BMX", 6: "Bicycling", 7: "Swimming", 8: "Surfing", 9: "Kitesurfing",
    10: "Windsurfing", 11: "Bodyboard", 12: "Tennis", 13: "Table tennis", 14: "Squash", 15: "Badminton", 16: "Lift weights",
    17: "Calisthenics", 18: "Elliptical", 19: "Pilates", 20: "Basketball", 21: "Soccer", 22: "Football", 23: "Rugby",
    24: "Volleyball", 25: "Water polo", 26: "Horse riding", 27: "Golf", 28: "Yoga", 29: "Dancing", 30: "Boxing", 31: "Fencing",
    32: "Wrestling", 33: "Martial arts", 34: "Skiing", 35: "Snowboarding", 36: "Other", 128: "No activity", 187: "Rowing",
    188: "Zumba", 191: "Baseball", 192: "Handball", 193: "Hockey", 194: "Ice hockey", 195: "Climbing", 196: "Ice skating",
    272: "Multi-sport", 306: "Indoor walk", 307: "Indoor running", 308: "Indoor cycling",
}


class Withings(Provider):
    key = "withings"
    name = "Withings"
    color = "#2a8bd6"
    initials = "Wi"
    website = "https://www.withings.com"
    delivers = ["body", "heart", "sleep", "activity", "workouts"]
    summary = "Waagen, Blutdruckmessgeräte, Schlafsensor und Uhren: Gewicht, Körperzusammensetzung, Blutdruck, Schlaf, Schritte."
    setup = ["Auf „Verbinden“ klicken, mit dem Withings-Konto anmelden und den Zugriff erlauben."]
    app_setup = [
        "Auf https://developer.withings.com/dashboard/ ein Konto anlegen und eine „Public API Integration“ erstellen.",
        "Als Callback-URL die unten angezeigte Rücksprung-Adresse eintragen (Withings verlangt HTTPS).",
        "Client ID und Secret hier eintragen.",
    ]
    app_fields = [Field("client_id", "Client ID"), Field("client_secret", "Consumer Secret", "password", secret=True)]
    oauth = OAuthSpec("https://account.withings.com/oauth2_user/authorize2", f"{API}/v2/oauth2",
                      ["user.info", "user.metrics", "user.activity"], scope_sep=",")

    def token_extra(self, data: dict) -> dict:
        return {**data, "action": "requesttoken"}

    def parse_token(self, data: dict) -> dict:
        if data.get("status") not in (0, None):
            raise AuthError(f"Withings hat die Anmeldung abgelehnt (Status {data.get('status')}).")
        return super().parse_token(data.get("body") or data)

    def after_token(self, ctx, token):
        return f"Withings-Nutzer {token.get('userid')}" if token.get("userid") else None

    def _call(self, ctx, path: str, params: dict) -> dict:
        data = ctx.post(f"{API}{path}", data=params) or {}
        status = data.get("status")
        if status == 0:
            return data.get("body") or {}
        if status in (401, 100, 101, 102, 200, 293):
            ctx.refresh()
            data = ctx.post(f"{API}{path}", data=params) or {}
            if data.get("status") == 0:
                return data.get("body") or {}
            raise AuthError("Withings hat den Zugang abgelehnt. Bitte verbinde dich erneut.")
        if status == 601:
            raise RateLimited("Withings begrenzt gerade die Anfragen. Der nächste Abgleich holt den Rest nach.")
        raise SyncError(f"Withings meldet Status {status}: {data.get('error', '')}")

    def sync(self, ctx):
        w = ctx.writer
        start, end = epoch(ctx.since), epoch(ctx.until) + 86400
        # Messungen
        offset = None
        for _ in range(50):
            params = {"action": "getmeas", "category": 1, "startdate": start, "enddate": end,
                      "meastypes": ",".join(str(k) for k in MEASURE_TYPES)}
            if offset:
                params["offset"] = offset
            body = self._call(ctx, "/measure", params)
            for grp in body.get("measuregrps", []):
                ts = datetime.fromtimestamp(grp.get("date", 0), timezone.utc).replace(tzinfo=None)
                for m in grp.get("measures", []):
                    metric, factor = MEASURE_TYPES.get(m.get("type"), (None, 1))
                    if metric:
                        w.sample(metric, ts, scaled(m.get("value"), m.get("unit")) * factor)
            if not body.get("more"):
                break
            offset = body.get("offset")
        a, b = ctx.since_date.isoformat(), ctx.until_date.isoformat()
        # Aktivität pro Tag
        offset = None
        for _ in range(20):
            params = {"action": "getactivity", "startdateymd": a, "enddateymd": b,
                      "data_fields": "steps,distance,elevation,soft,moderate,intense,active,calories,totalcalories,hr_average"}
            if offset:
                params["offset"] = offset
            body = self._call(ctx, "/v2/measure", params)
            for day in body.get("activities", []):
                d = parse_date(day.get("date"))
                w.daily("steps", d, day.get("steps"))
                w.daily("distance", d, (num(day.get("distance")) or 0) / 1000 if day.get("distance") is not None else None)
                w.daily("active_energy", d, day.get("calories"))
                w.daily("total_energy", d, day.get("totalcalories"))
                mins = (num(day.get("moderate")) or 0) + (num(day.get("intense")) or 0)
                if day.get("moderate") is not None or day.get("intense") is not None:
                    w.daily("active_minutes", d, mins / 60)
            if not body.get("more"):
                break
            offset = body.get("offset")
        # Schlaf
        offset = None
        for _ in range(20):
            params = {"action": "getsummary", "startdateymd": a, "enddateymd": b,
                      "data_fields": "deepsleepduration,lightsleepduration,remsleepduration,wakeupduration,sleep_score,"
                                     "hr_average,rr_average,total_sleep_time,sleep_efficiency,durationtosleep"}
            if offset:
                params["offset"] = offset
            body = self._call(ctx, "/v2/sleep", params)
            for s in body.get("series", []):
                w.sleep(map_sleep(s))
                rr = (s.get("data") or {}).get("rr_average")
                if rr:
                    w.sample("respiratory_rate", datetime.fromtimestamp(s.get("enddate", 0), timezone.utc).replace(tzinfo=None), rr)
            if not body.get("more"):
                break
            offset = body.get("offset")
        # Trainings
        offset = None
        for _ in range(20):
            params = {"action": "getworkouts", "startdateymd": a, "enddateymd": b}
            if offset:
                params["offset"] = offset
            body = self._call(ctx, "/v2/measure", params)
            for s in body.get("series", []):
                act = map_workout(s)
                if act:
                    w.activity(act)
            if not body.get("more"):
                break
            offset = body.get("offset")


def scaled(value, unit) -> float:
    """Withings speichert Werte als Ganzzahl mit Zehnerpotenz (80450, -3 -> 80.45)."""
    value, unit = float(value or 0), int(unit or 0)
    return value * 10 ** unit if unit >= 0 else value / 10 ** (-unit)


def _ts(v):
    return datetime.fromtimestamp(v, timezone.utc).replace(tzinfo=None) if v else None


def map_sleep(s: dict) -> SleepIn:
    d = s.get("data") or {}

    def mins(k):
        return num(d.get(k)) / 60 if d.get(k) is not None else None
    eff = num(d.get("sleep_efficiency"))
    return SleepIn(
        source_id=str(s.get("id") or s.get("startdate")),
        start=_ts(s.get("startdate")), end=_ts(s.get("enddate")),
        asleep_min=mins("total_sleep_time"), deep_min=mins("deepsleepduration"), rem_min=mins("remsleepduration"),
        light_min=mins("lightsleepduration"), awake_min=mins("wakeupduration"), score=num(d.get("sleep_score")),
        efficiency=round(eff * 100, 1) if eff is not None and eff <= 1 else eff, avg_hr=num(d.get("hr_average")),
    )


def map_workout(s: dict) -> ActivityIn | None:
    cat = s.get("category")
    if cat == 128:
        return None
    d = s.get("data") or {}
    start, end = _ts(s.get("startdate")), _ts(s.get("enddate"))
    if not start:
        return None
    return ActivityIn(
        source_id=str(s.get("id") or s.get("startdate")), start=start,
        sport_raw=WORKOUT_CATEGORIES.get(cat, str(cat)), name=WORKOUT_CATEGORIES.get(cat),
        duration_s=(end - start).total_seconds() if end else None, distance_m=num(d.get("distance")),
        elevation_m=num(d.get("elevation")), calories=num(d.get("calories")), avg_hr=num(d.get("hr_average")),
        max_hr=num(d.get("hr_max")),
    )
