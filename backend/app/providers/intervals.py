from ..store import ActivityIn
from ..timeutil import parse_date, parse_iso
from .base import Field, Provider, SyncError, num

API = "https://intervals.icu/api/v1"


class Intervals(Provider):
    key = "intervals"
    name = "intervals.icu"
    kind = "apikey"
    color = "#e2405b"
    initials = "iI"
    website = "https://intervals.icu"
    delivers = ["workouts", "recovery", "body", "heart", "sleep"]
    summary = "Aktivitäten (auch von Garmin, Zwift, Polar, Suunto, COROS) und Wellness: Gewicht, Ruhepuls, HRV, Schlaf, Bereitschaft."
    setup = [
        "Bei intervals.icu unter Settings → Developer Settings einen API-Schlüssel erzeugen.",
        "Schlüssel hier eintragen. Die Athleten-ID kannst du leer lassen (dann dein eigenes Konto).",
    ]
    fields = [Field("api_key", "API-Schlüssel", "password", secret=True),
              Field("athlete_id", "Athleten-ID", required=False, placeholder="0 = eigenes Konto", default="0")]
    note = "Aktivitäten, die intervals.icu nur von Strava kennt, gibt die Schnittstelle ohne Details heraus. Verbinde dafür Strava direkt."

    def _basic(self, ctx):
        return ("API_KEY", ctx.auth.get("api_key", ""))

    def _athlete(self, ctx):
        return (ctx.config.get("athlete_id") or "0").strip() or "0"

    def connect(self, ctx, values):
        ctx.auth = {"api_key": values.get("api_key", "").strip()}
        ctx.config["athlete_id"] = (values.get("athlete_id") or "0").strip() or "0"
        a = ctx.get(f"{API}/athlete/{self._athlete(ctx)}", auth="basic", basic=self._basic(ctx)) or {}
        if not a:
            raise SyncError("intervals.icu hat kein Konto zu diesem Schlüssel geliefert.")
        return a.get("name") or a.get("id")

    def sync(self, ctx):
        w = ctx.writer
        params = {"oldest": ctx.since_date.isoformat(), "newest": ctx.until_date.isoformat()}
        aid = self._athlete(ctx)
        for a in ctx.get(f"{API}/athlete/{aid}/activities", params=params, auth="basic", basic=self._basic(ctx)) or []:
            if a.get("_note") and not a.get("start_date_local"):
                continue  # nur von Strava bekannt, ohne Daten
            w.activity(map_activity(a))
        for item in ctx.get(f"{API}/athlete/{aid}/wellness", params=params, auth="basic", basic=self._basic(ctx)) or []:
            map_wellness(w, item)


def map_activity(a: dict) -> ActivityIn:
    start = parse_iso(a.get("start_date")) or parse_iso(a.get("start_date_local"))
    return ActivityIn(
        source_id=str(a.get("id")), start=start, sport_raw=a.get("type"), name=a.get("name"),
        duration_s=num(a.get("elapsed_time")), moving_s=num(a.get("moving_time")), distance_m=num(a.get("distance")),
        elevation_m=num(a.get("total_elevation_gain")), calories=num(a.get("calories")),
        avg_hr=num(a.get("average_heartrate")), max_hr=num(a.get("max_heartrate")),
        avg_power=num(a.get("icu_average_watts")), load=num(a.get("icu_training_load")),
    )


def map_wellness(w, item: dict) -> None:
    d = parse_date(item.get("id"))
    w.daily("weight", d, item.get("weight"))
    w.daily("resting_hr", d, item.get("restingHR"))
    w.daily("hrv", d, item.get("hrv"))
    w.daily("readiness", d, item.get("readiness"))
    w.daily("body_fat", d, item.get("bodyFat"))
    w.daily("vo2max", d, item.get("vo2max"))
    w.daily("spo2", d, item.get("spO2"))
    w.daily("respiratory_rate", d, item.get("respiration"))
    w.daily("bp_systolic", d, item.get("systolic"))
    w.daily("bp_diastolic", d, item.get("diastolic"))
    w.daily("steps", d, item.get("steps"))
    w.daily("calories_in", d, item.get("kcalConsumed"))
    w.daily("glucose", d, (num(item.get("bloodGlucose")) or 0) * 18.0182 if item.get("bloodGlucose") else None)
    if item.get("sleepSecs"):
        w.daily("sleep_duration", d, num(item.get("sleepSecs")) / 60)
    w.daily("sleep_score", d, item.get("sleepScore"))
