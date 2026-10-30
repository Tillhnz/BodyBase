from ..store import ActivityIn, SleepIn
from ..timeutil import parse_iso
from .base import Field, OAuthSpec, Provider, num

API = "https://api.prod.whoop.com/developer/v2"


class Whoop(Provider):
    key = "whoop"
    name = "WHOOP"
    color = "#e8e8e8"
    initials = "Wh"
    website = "https://www.whoop.com"
    delivers = ["recovery", "sleep", "heart", "workouts", "body"]
    summary = "Recovery, HRV, Ruhepuls, Hauttemperatur, SpO₂, Schlafphasen, Strain und Trainings."
    setup = ["Auf „Verbinden“ klicken, mit dem WHOOP-Konto anmelden und alle Bereiche erlauben."]
    app_setup = [
        "Auf https://developer-dashboard.whoop.com ein Team und eine App anlegen.",
        "Alle „read“-Bereiche sowie „offline“ auswählen und als Redirect URL die unten angezeigte Rücksprung-Adresse eintragen.",
        "Client ID und Client Secret hier eintragen.",
    ]
    app_fields = [Field("client_id", "Client ID"), Field("client_secret", "Client Secret", "password", secret=True)]
    oauth = OAuthSpec("https://api.prod.whoop.com/oauth/oauth2/auth", "https://api.prod.whoop.com/oauth/oauth2/token",
                      ["offline", "read:recovery", "read:cycles", "read:sleep", "read:workout", "read:body_measurement", "read:profile"])

    def after_token(self, ctx, token):
        try:
            p = ctx.get(f"{API}/user/profile/basic") or {}
            return " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x) or p.get("email")
        except Exception:
            return None

    def _collect(self, ctx, path: str):
        params = {"start": ctx.since.isoformat() + "Z", "end": ctx.until.isoformat() + "Z", "limit": 25}
        for _ in range(200):
            data = ctx.get(f"{API}{path}", params=params) or {}
            yield from data.get("records", [])
            nxt = data.get("next_token")
            if not nxt:
                break
            params = {**params, "nextToken": nxt}

    def sync(self, ctx):
        w = ctx.writer
        for r in self._collect(ctx, "/recovery"):
            s = r.get("score") or {}
            if r.get("score_state") != "SCORED":
                continue
            ts = parse_iso(r.get("updated_at") or r.get("created_at"))
            w.sample("recovery", ts, s.get("recovery_score"))
            w.sample("resting_hr", ts, s.get("resting_heart_rate"))
            w.sample("hrv", ts, s.get("hrv_rmssd_milli"))
            w.sample("spo2", ts, s.get("spo2_percentage"))
        for r in self._collect(ctx, "/activity/sleep"):
            if r.get("score_state") != "SCORED":
                continue
            sleep = map_sleep(r)
            if sleep:
                w.sleep(sleep)
                w.sample("respiratory_rate", sleep.end, (r.get("score") or {}).get("respiratory_rate"))
        for r in self._collect(ctx, "/cycle"):
            s = r.get("score") or {}
            if r.get("score_state") == "SCORED" and r.get("end"):
                ts = parse_iso(r.get("end"))
                w.sample("strain", ts, s.get("strain"))
                kj = num(s.get("kilojoule"))
                if kj:
                    w.sample("total_energy", ts, kj / 4.184)
        for r in self._collect(ctx, "/activity/workout"):
            if r.get("score_state") != "SCORED":
                continue
            w.activity(map_workout(r))


def map_sleep(r: dict) -> SleepIn | None:
    start, end = parse_iso(r.get("start")), parse_iso(r.get("end"))
    if not start or not end:
        return None
    sc = r.get("score") or {}
    st = sc.get("stage_summary") or {}

    def mins(k):
        return num(st.get(k)) / 60000 if st.get(k) is not None else None
    deep, rem, light = mins("total_slow_wave_sleep_time_milli"), mins("total_rem_sleep_time_milli"), mins("total_light_sleep_time_milli")
    return SleepIn(source_id=str(r.get("id")), start=start, end=end, deep_min=deep, rem_min=rem, light_min=light,
                   awake_min=mins("total_awake_time_milli"), score=num(sc.get("sleep_performance_percentage")),
                   efficiency=num(sc.get("sleep_efficiency_percentage")), nap=bool(r.get("nap")))


def map_workout(r: dict) -> ActivityIn:
    s = r.get("score") or {}
    start, end = parse_iso(r.get("start")), parse_iso(r.get("end"))
    kj = num(s.get("kilojoule"))
    return ActivityIn(
        source_id=str(r.get("id")), start=start, sport_raw=r.get("sport_name"),
        name=(r.get("sport_name") or "").replace("-", " ").title() or None,
        duration_s=(end - start).total_seconds() if start and end else None, distance_m=num(s.get("distance_meter")),
        elevation_m=num(s.get("altitude_gain_meter")), calories=kj / 4.184 if kj else None,
        avg_hr=num(s.get("average_heart_rate")), max_hr=num(s.get("max_heart_rate")), load=num(s.get("strain")),
        details=hr_zones(s.get("zone_durations") or s.get("zone_duration")),
    )


def hr_zones(z: dict | None) -> dict | None:
    """Zeit in den Herzfrequenzzonen 0–5 (Sekunden)."""
    if not isinstance(z, dict):
        return None
    keys = ["zone_zero_milli", "zone_one_milli", "zone_two_milli", "zone_three_milli", "zone_four_milli", "zone_five_milli"]
    secs = [round((num(z.get(k)) or 0) / 1000) for k in keys]
    return {"hr_zones": secs} if any(secs) else None
