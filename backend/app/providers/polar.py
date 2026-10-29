from ..store import ActivityIn, SleepIn
from ..timeutil import parse_date, parse_iso
from .base import Field, OAuthSpec, Provider, iso_duration_s, num

API = "https://www.polaraccesslink.com/v3"


class Polar(Provider):
    key = "polar"
    name = "Polar"
    color = "#d6001c"
    initials = "Po"
    website = "https://flow.polar.com"
    delivers = ["workouts", "sleep", "recovery", "activity"]
    summary = "Trainings, Schlaf, Nightly Recharge (HRV, Ruhepuls, Atemfrequenz) und tägliche Aktivität aus Polar Flow."
    setup = ["Auf „Verbinden“ klicken und bei Polar Flow den Zugriff erlauben."]
    app_setup = [
        "Auf https://admin.polaraccesslink.com mit dem Polar-Konto anmelden und einen Client anlegen.",
        "Als Redirect URL die unten angezeigte Rücksprung-Adresse eintragen.",
        "Client ID und Client Secret hier eintragen.",
    ]
    app_fields = [Field("client_id", "Client ID"), Field("client_secret", "Client Secret", "password", secret=True)]
    oauth = OAuthSpec("https://flow.polar.com/oauth2/authorization", "https://polarremote.com/v2/oauth2/token",
                      ["accesslink.read_all"], token_auth="basic")
    note = "Polar stellt Trainings nur für die letzten 30 Tage bereit. Ältere Einheiten holst du per Datei-Import."
    overlap_days = 7

    def after_token(self, ctx, token):
        uid = token.get("x_user_id")
        # Nutzer bei AccessLink registrieren (409 = schon registriert)
        ctx.auth.update(token)
        ctx.post(f"{API}/users", json={"member-id": f"bodybase-{ctx.user.id}"}, ok_status=(409,), expect_json=False)
        return f"Polar-Nutzer {uid}" if uid else None

    def sync(self, ctx):
        w = ctx.writer
        for e in ctx.get(f"{API}/exercises", headers={"Accept": "application/json"}) or []:
            w.activity(map_exercise(e))
        sleep = ctx.get(f"{API}/users/sleep", headers={"Accept": "application/json"}) or {}
        for n in sleep.get("nights", []):
            s = map_sleep(n)
            if s:
                w.sleep(s)
        recharge = ctx.get(f"{API}/users/nightly-recharge", headers={"Accept": "application/json"}) or {}
        for r in recharge.get("recharges", []):
            d = parse_date(r.get("date"))
            w.daily("resting_hr", d, r.get("heart_rate_avg"))
            w.daily("hrv", d, r.get("heart_rate_variability_avg"))
            w.daily("respiratory_rate", d, r.get("breathing_rate_avg"))
            status = num(r.get("nightly_recharge_status"))  # 1–6
            if status is not None:
                w.daily("readiness", d, round((status - 1) / 5 * 100))
        self._daily_activity(ctx)

    def _daily_activity(self, ctx):
        uid = ctx.auth.get("x_user_id")
        if not uid:
            return
        tx = ctx.post(f"{API}/users/{uid}/activity-transactions", headers={"Accept": "application/json"}, ok_status=(204,))
        if not isinstance(tx, dict) or not tx.get("resource-uri"):
            return
        uri = tx["resource-uri"]
        listing = ctx.get(uri, headers={"Accept": "application/json"}) or {}
        for url in listing.get("activity-log", []):
            a = ctx.get(url, headers={"Accept": "application/json"}) or {}
            d = parse_date(a.get("date"))
            ctx.writer.daily("steps", d, a.get("active-steps"))
            ctx.writer.daily("active_energy", d, a.get("active-calories"))
            ctx.writer.daily("total_energy", d, a.get("calories"))
        ctx.request("PUT", uri, expect_json=False, ok_status=(200, 204))


def map_exercise(e: dict) -> ActivityIn:
    hr = e.get("heart_rate") or {}
    start = parse_iso(e.get("start_time"))
    offset = num(e.get("start_time_utc_offset"))
    if start is not None and offset is not None and "+" not in str(e.get("start_time")) and "Z" not in str(e.get("start_time")):
        # Polar gibt die Ortszeit ohne Zone plus Versatz in Minuten
        from datetime import timedelta
        start = parse_iso(str(e.get("start_time")) + "+00:00") - timedelta(minutes=offset)
    load = e.get("training_load_pro") or {}
    return ActivityIn(
        source_id=str(e.get("id")), start=start, sport_raw=e.get("detailed_sport_info") or e.get("sport"),
        name=(e.get("sport") or "").replace("_", " ").title() or None, duration_s=iso_duration_s(e.get("duration")),
        distance_m=num(e.get("distance")), calories=num(e.get("calories")), avg_hr=num(hr.get("average")),
        max_hr=num(hr.get("maximum")), load=num(e.get("training_load")) or num(load.get("cardio-load")),
    )


def map_sleep(n: dict) -> SleepIn | None:
    start, end = parse_iso(n.get("sleep_start_time")), parse_iso(n.get("sleep_end_time"))
    if not start or not end:
        return None

    def mins(k):
        return num(n.get(k)) / 60 if n.get(k) is not None else None
    deep, rem, light = mins("deep_sleep"), mins("rem_sleep"), mins("light_sleep")
    return SleepIn(source_id=str(n.get("date")), start=start, end=end, deep_min=deep, rem_min=rem, light_min=light,
                   awake_min=mins("total_interruption_duration"), score=num(n.get("sleep_score")))
