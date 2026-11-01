"""Bilder und Anleitungen zu Übungen aus der freien Übungsdatenbank free-exercise-db (gemeinfrei, Unlicense).

Zu jeder Übung gibt es zwei Fotos (Start- und Endposition), im Wechsel gezeigt ergibt das eine kurze Animation.
Die Bilder lädt der Server beim ersten Abruf von GitHub und speichert sie unter DATA_DIR/exercise-media.
Quelle: https://github.com/yuhonas/free-exercise-db
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache

log = logging.getLogger("bodybase.media")

SOURCE_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/{id}/{n}.jpg"
INDEX_PATH = os.path.join(os.path.dirname(__file__), "data", "exercise_media.json")

# Geprüfte Zuordnung der eingebauten Übungen; alle anderen werden über den Namen gesucht
OVERRIDES = {
    "bench_press": "Barbell_Bench_Press_-_Medium_Grip", "incline_bench_db": "Incline_Dumbbell_Press",
    "chest_press": "Leverage_Chest_Press", "fly_db": "Dumbbell_Flyes", "pec_deck": "Butterfly", "push_up": "Pushups",
    "dips_chest": "Dips_-_Chest_Version", "pull_up": "Pullups", "lat_pulldown": "Wide-Grip_Lat_Pulldown",
    "lat_pulldown_machine": "Full_Range-Of-Motion_Lat_Pulldown", "db_row": "One-Arm_Dumbbell_Row",
    "machine_row": "Leverage_Iso_Row", "pendlay_row": "Bent_Over_Barbell_Row", "ohp": "Standing_Military_Press",
    "shoulder_press_machine": "Machine_Shoulder_Military_Press", "lateral_raise": "Side_Lateral_Raise",
    "lateral_raise_machine": "Side_Lateral_Raise", "rear_delt_fly": "Seated_Bent-Over_Rear_Delt_Raise",
    "reverse_pec_deck": "Reverse_Machine_Flyes", "curl_cable": "Standing_Biceps_Cable_Curl", "preacher_curl": "Preacher_Curl",
    "overhead_triceps": "Cable_Rope_Overhead_Triceps_Extension",
    "overhead_triceps_db": "Standing_Dumbbell_Triceps_Extension", "skullcrusher": "EZ-Bar_Skullcrusher",
    "dips_triceps": "Dips_-_Triceps_Version", "wrist_curl": "Palms-Up_Barbell_Wrist_Curl_Over_A_Bench",
    "bulgarian_split_squat": "Split_Squat_with_Dumbbells", "hip_abduction": "Thigh_Abductor", "hip_adduction": "Thigh_Adductor",
    "side_plank": "Side_Bridge", "crunch": "Crunches", "crunch_machine": "Ab_Crunch_Machine",
    "leg_raise_lying": "Flat_Bench_Lying_Leg_Raise", "knee_raise_bars": "Knee_Hip_Raise_On_Parallel_Bars",
    "jump_rope": "Rope_Jumping", "treadmill": "Running_Treadmill", "stair_climber": "Stairmaster", "clean": "Power_Clean",
    "kb_swing": "One-Arm_Kettlebell_Swings", "farmers_walk": "Farmers_Walk", "rowing_machine": "Rowing_Stationary",
    "bike_erg": "Bicycling_Stationary", "assisted_dip": "Dip_Machine", "incline_bench": "Barbell_Incline_Bench_Press_-_Medium_Grip",
    "thruster": "Kettlebell_Thruster", "ab_wheel": "Ab_Roller", "glute_bridge": "Barbell_Glute_Bridge",
    "pullover_db": "Bent-Arm_Dumbbell_Pullover", "assisted_pull_up": "Band_Assisted_Pull-Up",
    "burpee": None,  # in der Datenbank nicht enthalten
}
MUSCLE_MAP = {
    "abdominals": "abs", "abductors": "abductors", "adductors": "adductors", "biceps": "biceps", "calves": "calves",
    "chest": "chest", "forearms": "forearms", "glutes": "glutes", "hamstrings": "hamstrings", "lats": "lats",
    "lower back": "lower_back", "middle back": "upper_back", "neck": "neck", "quadriceps": "quads", "shoulders": "shoulders",
    "traps": "traps", "triceps": "triceps",
}
EQUIP = {"barbell": "barbell", "dumbbell": "dumbbell", "machine": "machine", "cable": "cable", "bodyweight": "body only",
         "kettlebell": "kettlebells", "band": "bands", "ez_bar": "e-z curl bar", "smith": "machine"}
STOP = {"the", "a", "with", "on", "of", "to", "and", "machine", "barbell", "dumbbell", "cable", "bodyweight", "body", "only"}


@lru_cache(maxsize=1)
def index() -> dict[str, dict]:
    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            return {e["id"]: e for e in json.load(f)}
    except OSError:
        log.warning("Übungsbilder: %s fehlt", INDEX_PATH)
        return {}


def _toks(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP}


def match(names: list[str], equipment: str | None = None, threshold: float = 0.75) -> str | None:
    """Bester Eintrag der Datenbank für eine Übung (Ähnlichkeit der Wörter im Namen, passende Ausrüstung zählt mit).
    Deutsche Namen werden vorher übersetzt."""
    names = list(names) + [translate(n) for n in names if translate(n) != (n or "").lower()]
    best, best_id = 0.0, None
    want_eq = EQUIP.get(equipment or "")
    for e in index().values():
        b = _toks(e["name"])
        if not b:
            continue
        score = 0.0
        for n in names:
            a = _toks(n)
            if a:
                score = max(score, len(a & b) / len(a | b))
        if want_eq and e.get("equipment") == want_eq:
            score += 0.15
        if score > best:
            best, best_id = score, e["id"]
    return best_id if best >= threshold else None


# Deutsche Begriffe -> englische, damit eigene Übungen mit deutschem Namen ein Bild finden
GERMAN = [
    ("schrägbankdrücken", "incline bench press"), ("negativbankdrücken", "decline bench press"), ("bankdrücken", "bench press"),
    ("schulterdrücken", "shoulder press"), ("nackendrücken", "shoulder press"), ("brustpresse", "chest press"),
    ("beinpresse", "leg press"), ("beinstrecker", "leg extension"), ("beinbeuger", "leg curl"), ("wadenheben", "calf raise"),
    ("kniebeugen", "squat"), ("kniebeuge", "squat"), ("kreuzheben", "deadlift"), ("rumänisch", "romanian"),
    ("ausfallschritte", "lunge"), ("ausfallschritt", "lunge"), ("latziehen", "lat pulldown"), ("latzug", "lat pulldown"),
    ("klimmzüge", "pull up"), ("klimmzug", "pull up"), ("liegestütze", "push up"), ("liegestütz", "push up"),
    ("seitheben", "lateral raise"), ("frontheben", "front raise"), ("fliegende", "fly"), ("überzüge", "pullover"),
    ("rudern", "row"), ("bizepscurls", "biceps curl"), ("bizeps", "biceps"), ("trizepsdrücken", "triceps pushdown"),
    ("trizeps", "triceps"), ("hüftheben", "hip thrust"), ("hüftstoß", "hip thrust"), ("rückenstrecker", "hyperextension"),
    ("bauch", "ab"), ("knieheben", "knee raise"), ("beinheben", "leg raise"), ("unterarmstütz", "plank"), ("seitstütz", "side plank"),
    ("kurzhanteln", "dumbbell"), ("kurzhantel", "dumbbell"), ("langhantel", "barbell"), ("kabelzug", "cable"), ("kabel", "cable"),
    ("maschine", "machine"), ("multipresse", "smith machine"), ("sz-stange", "ez bar"), ("schräg", "incline"), ("sitzend", "seated"),
    ("stehend", "standing"), ("einarmig", "one arm"), ("eng", "close grip"), ("breit", "wide grip"), ("barren", "parallel bars"),
    ("hängend", "hanging"), ("liegend", "lying"),
]


def translate(name: str) -> str:
    s = (name or "").lower()
    for de, en in GERMAN:
        s = s.replace(de, f" {en} ")
    return s


def media_for_catalog(key: str, names: list[str], equipment: str) -> str | None:
    if key in OVERRIDES:
        return OVERRIDES[key]
    return match(names, equipment, threshold=0.8)


def muscles_of(media_id: str) -> tuple[str, list[str]] | None:
    e = index().get(media_id)
    if not e or not e.get("primary"):
        return None
    prim = MUSCLE_MAP.get(e["primary"][0])
    sec = [MUSCLE_MAP[m] for m in e.get("secondary", []) + e["primary"][1:] if m in MUSCLE_MAP and MUSCLE_MAP[m] != prim]
    return (prim, sec[:6]) if prim else None


def info(media_id: str | None) -> dict | None:
    e = index().get(media_id or "")
    if not e:
        return None
    return {"id": e["id"], "name": e["name"], "images": e.get("images", 2), "level": e.get("level"),
            "instructions": e.get("instructions", []), "source": "free-exercise-db (gemeinfrei)"}


def search(q: str, limit: int = 30) -> list[dict]:
    words = _toks(q)
    out = []
    for e in index().values():
        t = _toks(e["name"]) | {e["id"].lower()}
        hit = len(words & t)
        if not words or hit or q.lower() in e["name"].lower():
            out.append((hit, e))
    out.sort(key=lambda x: (-x[0], x[1]["name"]))
    return [{"id": e["id"], "name": e["name"], "equipment": e.get("equipment")} for _, e in out[:limit]]


def image_path(data_dir: str, media_id: str, n: int) -> str | None:
    """Bild aus dem Zwischenspeicher, beim ersten Mal von GitHub geladen. None, wenn es keins gibt."""
    if media_id not in index() or n not in (0, 1):
        return None  # nur bekannte Kennungen, keine beliebigen Adressen
    folder = os.path.join(data_dir, "exercise-media", media_id)
    path = os.path.join(folder, f"{n}.jpg")
    if os.path.exists(path):
        return path
    import httpx
    try:
        r = httpx.get(SOURCE_URL.format(id=media_id, n=n), timeout=15, follow_redirects=True)
    except httpx.HTTPError as e:
        log.info("Übungsbild %s/%s nicht geladen: %s", media_id, n, e)
        return None
    if r.status_code != 200 or not r.content.startswith(b"\xff\xd8"):
        return None
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(r.content)
    os.replace(tmp, path)
    return path
