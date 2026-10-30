from datetime import datetime, timedelta


def _now():
    from app.timeutil import utcnow
    return utcnow().replace(microsecond=0)


def test_raw_hr_hourly_means_and_workout_series(db, user):
    from app import heartrate
    from app.models import Activity, HeartRateRaw, Sample
    from app.store import ActivityIn, Writer
    start = (_now() - timedelta(hours=5)).replace(minute=0, second=0)
    w = Writer(db, user.id, "health_connect")
    w.activity(ActivityIn(source_id="run1", start=start + timedelta(minutes=10), sport_raw="Run", duration_s=30 * 60, distance_m=6000))
    for i in range(0, 120 * 60, 30):  # zwei Stunden, alle 30 s
        w.sample("heart_rate", start + timedelta(seconds=i), 140 if 600 <= i <= 2400 else 70)
    w.flush()
    assert db.query(HeartRateRaw).filter(HeartRateRaw.user_id == user.id).count() == 240
    hours = db.query(Sample).filter(Sample.user_id == user.id, Sample.metric == "heart_rate").all()
    assert len(hours) == 2 and all(h.ts.minute == 30 for h in hours)
    run = db.query(Activity).filter(Activity.user_id == user.id, Activity.source_id == "run1").one()
    hr = run.details["hr"]
    assert hr["avg"] == 140 and len(hr["t"]) == len(hr["v"]) >= 50
    assert run.avg_hr == 140

    # Rohwerte älter als 3 Tage verschwinden, Verlauf und Stundenmittel bleiben
    for r in db.query(HeartRateRaw).filter(HeartRateRaw.user_id == user.id):
        r.ts -= timedelta(days=5)
    db.commit()
    heartrate.maintenance(db)
    assert db.query(HeartRateRaw).filter(HeartRateRaw.user_id == user.id).count() == 0
    assert db.get(Activity, run.id).details["hr"]["avg"] == 140


def test_compact_legacy_samples(db, user):
    from app import heartrate
    from app.models import Sample
    from app.timeutil import local_day
    old = datetime(2026, 1, 10, 9, 0)
    for i in range(12):
        ts = old + timedelta(minutes=5 * i)
        db.add(Sample(user_id=user.id, metric="heart_rate", source="apple_health", ts=ts, day=local_day(ts), value=60 + i))
    db.commit()
    heartrate.compact_old_samples(db, _now() - timedelta(days=3))
    rows = db.query(Sample).filter(Sample.user_id == user.id, Sample.metric == "heart_rate").all()
    assert len(rows) == 1 and rows[0].ts == old + timedelta(minutes=30) and abs(rows[0].value - 65.5) < 0.01


def test_live_bluetooth_hr_on_workout(client, auth):
    items = client.get("/api/strength/exercises", headers=auth).json()
    bench = next(e for e in items if e["name"] == "Bankdrücken (Langhantel)")
    t0 = datetime(2026, 7, 1, 17, 0)
    body = {"name": "Push", "start": t0.isoformat() + "Z", "end": (t0 + timedelta(minutes=40)).isoformat() + "Z",
            "exercises": [{"exercise_id": bench["id"], "sets": [{"kg": 60, "reps": 8}]}],
            "hr": {"start": t0.isoformat() + "Z", "t": list(range(0, 2400, 3)), "v": [100 + (i % 40) for i in range(800)],
                   "marks": [[300, "Bankdrücken"]], "source": "bluetooth", "device": "WHOOP 4A"}}
    w = client.post("/api/strength/workouts", json=body, headers=auth).json()
    hr = w["linked"]["hr"]
    assert hr["source"] == "bluetooth" and hr["marks"][0][1] == "Bankdrücken" and len(hr["t"]) <= 900
    assert w["linked"]["avg_hr"] is not None
    bad = {**body, "hr": {"t": [1, 2], "v": [1]}}
    assert client.post("/api/strength/workouts", json=bad, headers=auth).status_code == 201  # unbrauchbarer Puls wird ignoriert


def test_recent_endpoint(client, auth):
    r = client.get("/api/heart-rate/recent?hours=24", headers=auth)
    assert r.status_code == 200 and r.json()["t"] == []
