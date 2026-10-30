"""Sportarten der Anbieter auf wenige eigene Kategorien abbilden."""

SPORTS = {
    "run": "Laufen",
    "ride": "Radfahren",
    "walk": "Gehen",
    "hike": "Wandern",
    "climb": "Klettern & Bouldern",
    "swim": "Schwimmen",
    "strength": "Krafttraining",
    "row": "Rudern",
    "ski": "Wintersport",
    "yoga": "Yoga & Mobilität",
    "cardio": "Ausdauertraining",
    "team": "Ballsport",
    "other": "Sonstiges",
}

# Reihenfolge zählt: spezifische Begriffe zuerst ("virtualride" vor "ride", "nordic ski" vor "walk")
_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("row", ("row", "ruder", "kayak", "canoe", "paddl", "skierg")),
    ("ski", ("ski", "snowboard", "langlauf", "skating", "skate", "snowshoe")),
    ("swim", ("swim", "schwimm", "pool", "open_water", "openwater")),
    ("ride", ("ride", "cycl", "bike", "biking", "velo", "gravel", "spinning", "indoor_cycling", "bicycle", "mtb", "zwift", "radfahr", "rennrad", "radtour")),
    ("run", ("run", "lauf", "jog", "trail", "treadmill", "track")),
    ("climb", ("climb", "kletter", "boulder", "bouldering")),
    ("hike", ("hike", "hiking", "wander", "mountaineer", "berg")),
    ("walk", ("walk", "geh", "spazier", "nordic", "stroll")),
    ("strength", ("strength", "weight", "kraft", "gym", "functional", "crossfit", "lifting", "resistance", "calisthen")),
    ("yoga", ("yoga", "pilates", "stretch", "mobility", "breath", "meditat", "barre", "tai chi")),
    ("team", ("soccer", "fußball", "football", "basket", "tennis", "squash", "badminton", "volley", "hockey", "handball", "golf", "padel", "table_tennis")),
    ("cardio", ("hiit", "cardio", "elliptical", "crosstrainer", "stair", "aerobic", "workout", "training", "boxing", "dance", "martial", "jump")),
]


def normalize(raw: str | None) -> str:
    if not raw:
        return "other"
    s = str(raw).lower().replace("-", "_")
    for sport, hints in _HINTS:
        if any(h in s for h in hints):
            return sport
    return "other"


def migrate(db) -> None:
    """Bestehende Aktivitäten nach geänderten Regeln neu einordnen (z. B. Bouldern war früher „Wandern“)."""
    from sqlalchemy import select

    from .models import Activity
    changed = 0
    for a in db.scalars(select(Activity).where(Activity.sport.in_(["hike", "other", "cardio"]))):
        new = normalize(a.sport_raw or a.name)
        if new == "climb" and a.sport != "climb":
            a.sport = "climb"
            changed += 1
    if changed:
        db.commit()
