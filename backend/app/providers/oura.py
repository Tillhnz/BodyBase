from ..store import ActivityIn, SleepIn
from ..timeutil import parse_date, parse_iso
from .base import Field, OAuthSpec, Provider, num

API = "https://api.ouraring.com/v2/usercollection"


class Oura(Provider):
    key = "oura"
    name = "Oura"
    color = "#b9a26a"
    initials = "Ou"
    website = "https://ouraring.com"
    delivers = ["sleep", "recovery", "activity", "heart", "workouts"]
    summary = "Schlafphasen, Bereitschaft, HRV, Ruhepuls, Temperaturabweichung, SpO₂, Schritte und Trainings vom Oura Ring."
    setup = ["Auf „Verbinden“ klicken, mit dem Oura-Konto anmelden und alle Bereiche erlauben."]
    app_setup = [
        "Auf https://cloud.ouraring.com/oauth/applications eine Anwendung anlegen.",
        "Als Redirect URI die unten angezeigte Rücksprung-Adresse eintragen.",
        "Client ID und Client Secret hier eintragen.",
    ]
    app_fields = [Field("client_id", "Client ID"), Field("client_secret", "Client Secret", "password", secret=True)]
    oauth = OAuthSpec("https://cloud.ouraring.com/oauth/authorize", "https://api.ouraring.com/oauth/token",
                      ["email", "personal", "daily", "heartrate", "workout", "session", "spo2"])

    def after_token(self, ctx, token):
        try:
            info = ctx.get("https://api.ouraring.com/v2/usercollection/personal_info") or {}
            return info.get("email")
        except Exception:
            return None

    def _collect(self, ctx, endpoint: str):
        params = {"start_date": ctx.since_date.isoformat(), "end_date": ctx.until_date.isoformat()}
        for _ in range(100):
            data = ctx.get(f"{API}/{endpoint}", params=params) or {}
            yield from data.get("data", [])
            nxt = data.get("next_token")
            if not nxt:
                break
            params = {**params, "next_token": nxt}

    def sync(self, ctx):
        w = ctx.writer
        for item in self._collect(ctx, "daily_readiness"):
            d = parse_date(item.get("day"))
            w.daily("readiness", d, item.get("score"))
            w.daily("skin_temp_dev", d, item.get("temperature_deviation"))
        for item in self._collect(ctx, "daily_activity"):
            d = parse_date(item.get("day"))
            w.daily("steps", d, item.get("steps"))
            w.daily("active_energy", d, item.get("active_calories"))
            w.daily("total_energy", d, item.get("total_calories"))
            mins = (num(item.get("high_activity_time")) or 0) + (num(item.get("medium_activity_time")) or 0)
            w.daily("active_minutes", d, mins / 60)
        scores = {item.get("day"): item.get("score") for item in self._collect(ctx, "daily_sleep")}
        for item in self._collect(ctx, "daily_spo2"):
            w.daily("spo2", parse_date(item.get("day")), (item.get("spo2_percentage") or {}).get("average"))
        for s in self._collect(ctx, "sleep"):
            sleep = map_sleep(s, scores.get(s.get("day")))
            if sleep:
                w.sleep(sleep)
                if not sleep.nap:
                    w.sample("resting_hr", sleep.end, s.get("lowest_heart_rate"))
                    w.sample("respiratory_rate", sleep.end, s.get("average_breath"))
        for wo in self._collect(ctx, "workout"):
            w.activity(ActivityIn(
                source_id=str(wo.get("id")), start=parse_iso(wo.get("start_datetime")), sport_raw=wo.get("activity"),
                name=(wo.get("label") or wo.get("activity") or "").replace("_", " ").capitalize() or None,
                duration_s=_secs(wo.get("start_datetime"), wo.get("end_datetime")), distance_m=num(wo.get("distance")),
                calories=num(wo.get("calories")),
            ))


def _secs(a, b):
    sa, sb = parse_iso(a), parse_iso(b)
    return (sb - sa).total_seconds() if sa and sb else None


def map_sleep(s: dict, score=None) -> SleepIn | None:
    start, end = parse_iso(s.get("bedtime_start")), parse_iso(s.get("bedtime_end"))
    if not start or not end:
        return None

    def mins(k):
        return num(s.get(k)) / 60 if s.get(k) is not None else None
    return SleepIn(
        source_id=str(s.get("id")), start=start, end=end, asleep_min=mins("total_sleep_duration"),
        deep_min=mins("deep_sleep_duration"), rem_min=mins("rem_sleep_duration"), light_min=mins("light_sleep_duration"),
        awake_min=mins("awake_time"), efficiency=num(s.get("efficiency")), avg_hr=num(s.get("average_heart_rate")),
        hrv=num(s.get("average_hrv")), score=num(score) if s.get("type") == "long_sleep" else None,
        nap=s.get("type") not in ("long_sleep", None),
    )
