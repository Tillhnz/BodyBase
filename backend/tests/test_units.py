from datetime import datetime, timedelta

from sqlalchemy import select

from app import metrics as M
from app.importers.apple import build_sleep_sessions, convert
from app.importers.tabular import _match, _num
from app.models import Activity
from app.providers.base import iso_duration_s
from app.providers.fitbit import vo2_range
from app.providers.garmin import map_activity, map_sleep
from app.sports import normalize
from app.store import ActivityIn, Writer
from app.timeutil import parse_iso


def test_sports():
    assert normalize("VirtualRide") == "ride"
    assert normalize("TrailRun") == "run"
    assert normalize("strength_training") == "strength"
    assert normalize("HKWorkoutActivityTypeTraditionalStrengthTraining") == "strength"
    assert normalize("Nordic skiing") == "ski"
    assert normalize("Hiking") == "hike"
    assert normalize("Yoga") == "yoga"
    assert normalize(None) == "other"
    assert normalize("Rowing (Concept2)") == "row"


def test_plausible():
    assert M.plausible("weight", 80)
    assert not M.plausible("weight", 5)
    assert not M.plausible("resting_hr", float("nan"))
    assert not M.plausible("unknown", 1)


def test_parse_iso_variants():
    assert parse_iso("2026-10-01T10:00:00Z") == datetime(2026, 10, 1, 10, 0)
    assert parse_iso("2026-10-01 12:00:00 +0200") == datetime(2026, 10, 1, 10, 0)
    assert parse_iso("2026-10-01T12:00:00.000+02:00") == datetime(2026, 10, 1, 10, 0)
    assert parse_iso(1759312800000) == datetime(2025, 10, 1, 10, 0)
    assert parse_iso("2026-10-01T12:00:00") == datetime(2026, 10, 1, 10, 0)  # Ortszeit Berlin (Sommerzeit)
    assert parse_iso("kaputt") is None


def test_helpers():
    assert iso_duration_s("PT1H2M3S") == 3723
    assert vo2_range("44-48") == 46
    assert round(convert("weight", 176.37, "lb"), 1) == 80.0
    assert convert("spo2", 0.97, "%") == 97
    assert round(convert("glucose", 5.5, "mmol/L")) == 99
    assert _num("1.234,5") == 1234.5 and _num("80,4") == 80.4 and _num("-") is None
    assert _match("Weight (lb)") == ("weight", "lb")
    assert _match("Fat (g)")[0] == "fat"
    assert _match("Body Fat (%)")[0] == "body_fat"


def test_duplicates_follow_priority(db, user):
    start = datetime(2026, 9, 1, 16, 0)
    Writer(db, user.id, "strava").activity(ActivityIn(source_id="s1", start=start, sport_raw="Run", duration_s=3000, distance_m=10000,
                                                      name="Abendlauf"))
    Writer(db, user.id, "garmin").activity(ActivityIn(source_id="g1", start=start + timedelta(seconds=30), sport_raw="running",
                                                      duration_s=3010, distance_m=10020, avg_hr=150))
    rows = {a.source: a for a in db.scalars(select(Activity).where(Activity.user_id == user.id))}
    assert rows["garmin"].duplicate_of is None
    assert rows["strava"].duplicate_of == rows["garmin"].id
    # eine andere Einheit am selben Tag bleibt eigenständig
    Writer(db, user.id, "strava").activity(ActivityIn(source_id="s2", start=start + timedelta(hours=3), sport_raw="Ride", duration_s=3600))
    s2 = db.scalar(select(Activity).where(Activity.source_id == "s2", Activity.user_id == user.id))
    assert s2.duplicate_of is None


def test_samples_upsert(db, user):
    w = Writer(db, user.id, "manual")
    ts = datetime(2026, 9, 2, 6, 0)
    w.sample("weight", ts, 80)
    w.flush()
    w.sample("weight", ts, 80.5)
    w.sample("weight", ts, 999)  # unplausibel: verworfen
    counts = w.flush()
    assert counts["skipped"] == 1
    from app.models import Sample
    rows = db.scalars(select(Sample).where(Sample.user_id == user.id, Sample.metric == "weight")).all()
    assert len(rows) == 1 and rows[0].value == 80.5


def test_garmin_mapping():
    a = map_activity({"activityId": 1, "activityName": "Lauf", "startTimeGMT": "2026-10-01 05:00:00",
                      "activityType": {"typeKey": "running"}, "duration": 3000, "distance": 10000, "averageHR": 150})
    assert a.start == datetime(2026, 10, 1, 5, 0) and a.distance_m == 10000
    s = map_sleep({"dailySleepDTO": {"id": 3, "sleepStartTimestampGMT": 1759276800000, "sleepEndTimestampGMT": 1759302000000,
                                     "sleepTimeSeconds": 25200, "deepSleepSeconds": 5400, "sleepScores": {"overall": {"value": 82}}}})
    assert s.asleep_min == 420 and s.deep_min == 90 and s.score == 82


def test_apple_sleep_sessions():
    base = datetime(2026, 10, 1, 22, 0)
    parts = [
        (base, base + timedelta(hours=2), "light", "Watch"),
        (base + timedelta(hours=2), base + timedelta(hours=3), "deep", "Watch"),
        (base + timedelta(hours=3), base + timedelta(hours=3, minutes=10), "awake", "Watch"),
        (base + timedelta(hours=3, minutes=10), base + timedelta(hours=7), "rem", "Watch"),
        (base, base + timedelta(hours=6), "asleep", "iPhone"),
    ]
    sessions = build_sleep_sessions(parts)
    assert len(sessions) == 1
    s = sessions[0]
    assert round(s.asleep_min) == 410 and round(s.deep_min) == 60 and round(s.awake_min) == 10
