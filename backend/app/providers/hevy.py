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
    summary = "Trainings aus Hevy laufen direkt ins Krafttraining von BodyBase. Die API gibt es nur mit Hevy Pro."
    setup = ["In der Hevy-App (Pro) unter Profil → Einstellungen → Developer einen API-Schlüssel erzeugen und hier eintragen."]
    note = ("Ohne Hevy Pro: In Hevy unter Profil → Einstellungen → Daten exportieren die workouts.csv laden und in BodyBase unter "
            "Kraft → Importieren hochladen. Danach kannst du direkt in BodyBase weitertrainieren.")
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
        """Hevy-Trainings landen im Krafttraining von BodyBase (mit Übungen, Rekorden und Auswertungen)."""
        from .. import strength as S
        matcher = S.Matcher(ctx.db, ctx.user.id)
        page = 1
        while page <= 200:
            data = ctx.get(f"{API}/workouts", params={"page": page, "pageSize": 10}, auth="none", headers=self._h(ctx)) or {}
            items = data.get("workouts", [])
            older = False
            for wo in items:
                payload = to_payload(wo, matcher)
                start = parse_iso(wo.get("start_time"))
                if start and start < ctx.since:
                    older = True
                    continue
                if not payload:
                    continue
                try:
                    S.save_workout(ctx.db, ctx.user, payload, source="hevy", source_id=str(wo.get("id")))
                    ctx.writer.counts["activities"] += 1
                except S.StrengthError:
                    ctx.db.rollback()
            if older or page >= (data.get("page_count") or 1):
                break
            page += 1


HEVY_TYPES = {"warmup": "warmup", "normal": "normal", "failure": "failure", "dropset": "drop"}


def to_payload(wo: dict, matcher) -> dict | None:
    exercises = []
    for ex in wo.get("exercises", []) or []:
        e = matcher.get(ex.get("title") or "")
        exercises.append({
            "exercise_id": e.id, "notes": ex.get("notes"), "superset": ex.get("superset_id"),
            "sets": [{"type": HEVY_TYPES.get(s.get("type") or "normal", "normal"), "kg": num(s.get("weight_kg")),
                      "reps": num(s.get("reps")), "duration_s": num(s.get("duration_seconds")),
                      "distance_m": num(s.get("distance_meters")), "rpe": num(s.get("rpe"))} for s in ex.get("sets", []) or []],
        })
    if not exercises:
        return None
    return {"name": wo.get("title") or "Training", "notes": wo.get("description"), "start": wo.get("start_time"),
            "end": wo.get("end_time"), "exercises": exercises}
