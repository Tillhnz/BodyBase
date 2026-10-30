from .. import tracks
from ..store import ActivityIn
from ..timeutil import parse_iso
from .base import Field, OAuthSpec, Provider, epoch, num

API = "https://cloudapi.suunto.com/v2"

ACTIVITIES = {0: "Walking", 1: "Running", 2: "Cycling", 3: "Nordic skiing", 4: "Other", 10: "Mountain biking", 11: "Hiking",
              12: "Roller skating", 13: "Downhill skiing", 14: "Paddling", 15: "Rowing", 16: "Golf", 17: "Indoor",
              20: "Swimming", 21: "Trail running", 22: "Gym", 23: "Nordic walking", 24: "Horseback riding", 27: "Climbing",
              29: "Snowboarding", 31: "Ski touring", 34: "Fitness class", 40: "Treadmill", 51: "Indoor rowing",
              52: "Crossfit", 53: "Kettlebell", 59: "Yoga", 60: "Pilates", 61: "Openwater swimming", 69: "Trail running",
              70: "Circuit training", 74: "Indoor cycling", 78: "Gravel cycling", 82: "Mountaineering", 83: "Multisport",
              84: "Triathlon", 92: "Strength training", 98: "Stretching"}


class Suunto(Provider):
    key = "suunto"
    name = "Suunto"
    color = "#e8a33d"
    initials = "Su"
    website = "https://www.suunto.com"
    delivers = ["workouts"]
    summary = "Trainings aus der Suunto-App mit Strecke, Höhenmetern, Puls und Kalorien."
    setup = ["Auf „Verbinden“ klicken und bei Suunto den Zugriff erlauben."]
    app_setup = [
        "Im Suunto API Zone Portal (https://apizone.suunto.com) registrieren und ein Abo für die Workout-API abschließen.",
        "Eine Anwendung anlegen, als Redirect URI die unten angezeigte Rücksprung-Adresse eintragen.",
        "Client ID, Client Secret und den Subscription Key hier eintragen.",
    ]
    app_fields = [Field("client_id", "Client ID"), Field("client_secret", "Client Secret", "password", secret=True),
                  Field("subscription_key", "Subscription Key (Ocp-Apim)", "password", secret=True)]
    oauth = OAuthSpec("https://cloudapi-oauth.suunto.com/oauth/authorize", "https://cloudapi-oauth.suunto.com/oauth/token",
                      [], token_auth="basic")
    note = "Die Suunto-API ist für Partner gedacht; der Zugang muss bei Suunto beantragt werden. Einfacher: Suunto mit Strava verbinden."

    def after_token(self, ctx, token):
        return token.get("user")

    has_tracks = True

    def track(self, ctx, row):
        headers = {"Ocp-Apim-Subscription-Key": ctx.app.get("subscription_key", "")}
        data = tracks.download(ctx, f"{API}/workout/exportFit/{row.source_id}", headers=headers)
        return tracks.from_file("suunto.fit", data) if data else None

    def sync(self, ctx):
        headers = {"Ocp-Apim-Subscription-Key": ctx.app.get("subscription_key", "")}
        data = ctx.get(f"{API}/workouts", params={"since": epoch(ctx.since) * 1000, "limit": 500}, headers=headers) or {}
        for wo in data.get("payload", []):
            ctx.writer.activity(map_workout(wo))


def map_workout(wo: dict) -> ActivityIn:
    hr = wo.get("hrdata") or {}
    t = ACTIVITIES.get(wo.get("activityId"), "Workout")
    return ActivityIn(
        source_id=str(wo.get("workoutKey") or wo.get("workoutId")), start=parse_iso(wo.get("startTime")), sport_raw=t,
        name=wo.get("workoutName") or t, duration_s=num(wo.get("totalTime")), distance_m=num(wo.get("totalDistance")),
        elevation_m=num(wo.get("totalAscent")), calories=num(wo.get("energyConsumption")),
        avg_hr=num(hr.get("workoutAvgHR") or hr.get("avg")), max_hr=num(hr.get("workoutMaxHR") or hr.get("max")),
    )
