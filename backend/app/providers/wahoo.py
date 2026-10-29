from ..store import ActivityIn
from ..timeutil import parse_iso
from .base import Field, OAuthSpec, Provider, num

API = "https://api.wahooligan.com/v1"

# Auszug der Wahoo-Trainingsarten (workout_type_id)
TYPES = {0: "Biking", 1: "Running", 2: "FE", 3: "Running track", 4: "Running trail", 5: "Running treadmill", 6: "Walking",
         7: "Walking speed", 8: "Walking nordic", 9: "Hiking", 10: "Mountaineering", 11: "Biking cyclecross",
         12: "Biking indoor", 13: "Biking mountain", 14: "Biking recumbent", 15: "Biking road", 16: "Biking track",
         17: "Biking motocycling", 18: "FE general", 19: "FE treadmill", 20: "FE elliptical", 21: "FE bike", 22: "FE rower",
         23: "FE climber", 25: "Swimming lap", 26: "Swimming open water", 27: "Snowboarding", 28: "Skiing",
         29: "Skiing downhill", 30: "Skiing cross country", 31: "Skating", 32: "Skating ice", 33: "Skating inline",
         34: "Long boarding", 35: "Sailing", 36: "Windsurfing", 37: "Canoeing", 38: "Kayaking", 39: "Rowing",
         40: "Kiteboarding", 41: "Stand up paddle", 42: "Workout", 43: "Cardio class", 44: "Stair climber",
         45: "Wheelchair", 46: "Golfing", 47: "Other", 49: "Biking indoor cycling class", 56: "Walking treadmill",
         61: "Biking indoor trainer", 62: "Multisport", 63: "Transition", 64: "E-Biking", 65: "Tickr offline",
         66: "Yoga", 67: "Running race", 68: "Biking indoor virtual", 69: "Mental strength", 70: "Handcycling",
         71: "Running indoor virtual"}


class Wahoo(Provider):
    key = "wahoo"
    name = "Wahoo"
    color = "#0b7cff"
    initials = "Wa"
    website = "https://www.wahoofitness.com"
    delivers = ["workouts"]
    summary = "Trainings von ELEMNT-Radcomputern, KICKR und der Wahoo-App mit Leistung, Puls und Kalorien."
    setup = ["Auf „Verbinden“ klicken und bei Wahoo den Zugriff erlauben."]
    app_setup = [
        "Auf https://developers.wahooligan.com eine Anwendung anlegen (Bereiche: user_read, workouts_read, offline_data).",
        "Als Redirect URI die unten angezeigte Rücksprung-Adresse eintragen.",
        "Client ID und Secret hier eintragen.",
    ]
    app_fields = [Field("client_id", "Client ID"), Field("client_secret", "Secret", "password", secret=True)]
    oauth = OAuthSpec("https://api.wahooligan.com/oauth/authorize", "https://api.wahooligan.com/oauth/token",
                      ["user_read", "workouts_read", "offline_data"], send_redirect_on_refresh=False)

    def after_token(self, ctx, token):
        try:
            u = ctx.get(f"{API}/user") or {}
            return " ".join(x for x in (u.get("first"), u.get("last")) if x) or u.get("email")
        except Exception:
            return None

    def sync(self, ctx):
        page = 1
        while page <= 40:
            data = ctx.get(f"{API}/workouts", params={"page": page, "per_page": 50}) or {}
            items = data.get("workouts", [])
            stop = False
            for wo in items:
                act = map_workout(wo)
                if act.start and act.start < ctx.since:
                    stop = True  # neueste zuerst: ältere sind schon da
                    continue
                ctx.writer.activity(act)
            if stop or len(items) < 50:
                break
            page += 1


def map_workout(wo: dict) -> ActivityIn:
    s = wo.get("workout_summary") or {}
    t = TYPES.get(wo.get("workout_type_id"), "Workout")
    return ActivityIn(
        source_id=str(wo.get("id")), start=parse_iso(wo.get("starts")), sport_raw=t, name=wo.get("name") or t,
        duration_s=num(s.get("duration_total_accum")) or ((num(wo.get("minutes")) or 0) * 60 or None),
        moving_s=num(s.get("duration_active_accum")), distance_m=num(s.get("distance_accum")),
        elevation_m=num(s.get("ascent_accum")), calories=num(s.get("calories_accum")), avg_hr=num(s.get("heart_rate_avg")),
        avg_power=num(s.get("power_avg")), load=num(s.get("training_stress_score")) if s.get("training_stress_score") else None,
    )
