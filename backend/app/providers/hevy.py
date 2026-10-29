from ..store import ActivityIn
from ..timeutil import parse_iso
from .base import Field, Provider, SyncError, num

API = "https://api.hevyapp.com/v1"


class Hevy(Provider):
    key = "hevy"
    name = "Hevy"
    kind = "apikey"
    color = "#3d7bfa"
    initials = "Hv"
    website = "https://www.hevyapp.com"
    delivers = ["workouts"]
    summary = "Krafttraining: Einheiten mit Übungen, Sätzen, Wiederholungen und bewegtem Gewicht."
    setup = ["In der Hevy-App (Pro) unter Profil → Einstellungen → Developer einen API-Schlüssel erzeugen und hier eintragen."]
    fields = [Field("api_key", "API-Schlüssel", "password", secret=True)]

    def _h(self, ctx):
        return {"api-key": ctx.auth.get("api_key", ""), "Accept": "application/json"}

    def connect(self, ctx, values):
        ctx.auth = {"api_key": values.get("api_key", "").strip()}
        data = ctx.get(f"{API}/workouts/count", auth="none", headers=self._h(ctx))
        if data is None:
            raise SyncError("Hevy hat den Schlüssel nicht bestätigt.")
        return f"{data.get('workout_count', 0)} Einheiten"

    def sync(self, ctx):
        page = 1
        while page <= 200:
            data = ctx.get(f"{API}/workouts", params={"page": page, "pageSize": 10}, auth="none", headers=self._h(ctx)) or {}
            items = data.get("workouts", [])
            older = False
            for wo in items:
                act = map_workout(wo)
                if act.start and act.start < ctx.since:
                    older = True
                    continue
                ctx.writer.activity(act)
            if older or page >= (data.get("page_count") or 1):
                break
            page += 1


def map_workout(wo: dict) -> ActivityIn:
    start, end = parse_iso(wo.get("start_time")), parse_iso(wo.get("end_time"))
    volume, sets, exercises = 0.0, 0, []
    for ex in wo.get("exercises", []):
        exercises.append({"name": ex.get("title"), "sets": [
            {"kg": num(s.get("weight_kg")), "reps": num(s.get("reps")), "type": s.get("type")} for s in ex.get("sets", [])]})
        for s in ex.get("sets", []):
            if s.get("type") == "warmup":
                continue
            sets += 1
            if num(s.get("weight_kg")) and num(s.get("reps")):
                volume += num(s.get("weight_kg")) * num(s.get("reps"))
    return ActivityIn(
        source_id=str(wo.get("id")), start=start, sport_raw="strength", sport="strength", name=wo.get("title") or "Krafttraining",
        duration_s=(end - start).total_seconds() if start and end else None, volume_kg=volume or None,
        details={"exercises": exercises, "sets": sets},
    )
