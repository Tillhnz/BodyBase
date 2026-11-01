from datetime import datetime, timedelta


def _ex(client, auth, name):
    items = client.get("/api/strength/exercises", headers=auth).json()
    return next(e for e in items if e["name"] == name)


def _workout(start, kg, reps=(8, 8, 6), ex_id=None, name="Push"):
    return {"name": name, "start": start.isoformat() + "Z", "end": (start + timedelta(minutes=55)).isoformat() + "Z",
            "exercises": [{"exercise_id": ex_id, "rest_s": 120, "sets": [{"type": "warmup", "kg": 40, "reps": 10}] +
                           [{"type": "normal", "kg": kg, "reps": r} for r in reps] + [{"type": "normal"}]}]}


def test_catalog_and_custom_exercise(client, auth):
    bench = _ex(client, auth, "Bankdrücken (Langhantel)")
    assert bench["primary"] == "chest" and not bench["custom"]
    r = client.post("/api/strength/exercises", json={"name": "Landmine Press", "equipment": "barbell", "primary": "shoulders",
                                                      "secondary": ["triceps", "shoulders"], "kind": "weight_reps"}, headers=auth)
    assert r.status_code == 201
    custom = r.json()
    assert custom["custom"] and custom["secondary"] == ["triceps"]
    assert client.put(f"/api/strength/exercises/{bench['id']}", json={"name": "x"}, headers=auth).status_code == 403
    assert client.delete(f"/api/strength/exercises/{custom['id']}", headers=auth).status_code == 204


def test_workout_flow_prs_and_stats(client, auth):
    bench = _ex(client, auth, "Bankdrücken (Langhantel)")
    t0 = datetime(2026, 9, 1, 17, 0)
    r = client.post("/api/strength/workouts", json=_workout(t0, 80, ex_id=bench["id"]), headers=auth)
    assert r.status_code == 201, r.text
    w1 = r.json()
    assert w1["sets"] == 3 and w1["volume_kg"] == 80 * 22 and w1["prs"] == []
    assert len(w1["exercises"][0]["sets"]) == 4  # leerer Satz fällt weg, Aufwärmsatz bleibt
    r = client.post("/api/strength/workouts", json=_workout(t0 + timedelta(days=3), 85, ex_id=bench["id"]), headers=auth)
    w2 = r.json()
    kinds = {p["type"] for p in w2["prs"]}
    assert {"weight", "e1rm", "set_volume"} <= kinds

    prev = client.post("/api/strength/previous", json={"ids": [bench["id"]]}, headers=auth).json()
    assert prev[str(bench["id"])][1]["kg"] == 85

    stats = client.get(f"/api/strength/exercises/{bench['id']}", headers=auth).json()
    assert stats["records"]["heaviest"]["value"] == 85
    assert stats["total"]["sessions"] == 2
    assert any(r["reps"] == 6 and r["kg"] == 85 for r in stats["rep_records"])

    summ = client.get("/api/strength/summary?days=0", headers=auth).json()
    assert summ["all_time"]["workouts"] >= 2
    assert any(m["muscle"] == "chest" for m in summ["muscles"])

    acts = client.get("/api/activities", headers=auth).json()
    items = acts["items"] if isinstance(acts, dict) else acts
    mirrored = [a for a in items if a.get("sport") == "strength"]
    assert mirrored, "Training erscheint unter Aktivitäten"

    # Bearbeiten und Löschen
    edit = _workout(t0 + timedelta(days=3), 90, ex_id=bench["id"], name="Push schwer")
    r = client.put(f"/api/strength/workouts/{w2['id']}", json=edit, headers=auth)
    assert r.status_code == 200 and r.json()["name"] == "Push schwer"
    assert client.delete(f"/api/strength/workouts/{w2['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/strength/workouts/{w2['id']}", headers=auth).status_code == 404


def test_empty_workout_rejected(client, auth):
    bench = _ex(client, auth, "Bankdrücken (Langhantel)")
    body = {"name": "Leer", "exercises": [{"exercise_id": bench["id"], "sets": [{"type": "normal"}]}]}
    assert client.post("/api/strength/workouts", json=body, headers=auth).status_code == 422


def test_active_workout_roundtrip(client, auth):
    assert client.get("/api/strength/active", headers=auth).json()["data"] is None
    client.put("/api/strength/active", json={"name": "Läuft", "exercises": []}, headers=auth)
    assert client.get("/api/strength/active", headers=auth).json()["data"]["name"] == "Läuft"
    assert client.delete("/api/strength/active", headers=auth).status_code == 204


def test_routines(client, auth):
    squat = _ex(client, auth, "Kniebeugen (Langhantel)")
    r = client.post("/api/strength/routines", json={"name": "Beine", "exercises": [
        {"exercise_id": squat["id"], "rest_s": 180, "sets": [{"kg": 100, "reps": 5}] * 3}]}, headers=auth)
    assert r.status_code == 201
    rid = r.json()["id"]
    assert client.get("/api/strength/routines", headers=auth).json()[0]["exercises"][0]["name"] == squat["name"]
    assert client.post("/api/strength/routines", json={"name": ""}, headers=auth).status_code == 422
    assert client.delete(f"/api/strength/routines/{rid}", headers=auth).status_code == 204


HEVY_CSV = '''"title","start_time","end_time","description","exercise_title","superset_id","exercise_notes","set_index","set_type","weight_kg","reps","distance_km","duration_seconds","rpe"
"Pull","28 Oct 2026, 18:05","28 Oct 2026, 19:10","","Lat Pulldown (Cable)",,"",0,"warmup",30,12,,,
"Pull","28 Oct 2026, 18:05","28 Oct 2026, 19:10","","Lat Pulldown (Cable)",,"",1,"normal",60,10,,,8
"Pull","28 Oct 2026, 18:05","28 Oct 2026, 19:10","","Mystery Machine Row",,"",0,"normal",50,12,,,
"Pull","28 Oct 2026, 18:05","28 Oct 2026, 19:10","","Plank",,"",0,"normal",,,,90,
'''

STRONG_CSV = '''Date;Workout Name;Duration;Exercise Name;Set Order;Weight;Reps;Distance;Seconds;Notes;Workout Notes;RPE
2026-10-20 07:00:00;Morgens;45m;Squat (Barbell);1;100;5;0;0;;;
2026-10-20 07:00:00;Morgens;45m;Squat (Barbell);2;100;5;0;0;;;
'''


def test_import_hevy_and_strong(client, auth):
    r = client.post("/api/strength/import", files={"file": ("workouts.csv", HEVY_CSV.encode(), "text/csv")}, headers=auth)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["source"] == "hevy" and res["created"] == 1 and res["new_exercises"] == 1
    # erneuter Import legt nichts doppelt an
    again = client.post("/api/strength/import", files={"file": ("workouts.csv", HEVY_CSV.encode(), "text/csv")}, headers=auth).json()
    assert again["created"] == 0 and again["updated"] == 1
    ws = client.get("/api/strength/workouts", headers=auth).json()
    pull = next(w for w in ws if w["name"] == "Pull")
    full = client.get(f"/api/strength/workouts/{pull['id']}", headers=auth).json()
    names = [b["name"] for b in full["exercises"]]
    assert names[0] == "Latzug (Kabel)" and "Mystery Machine Row" in names
    assert full["duration_s"] == 65 * 60
    r = client.post("/api/strength/import", files={"file": ("strong.csv", STRONG_CSV.encode(), "text/csv")}, headers=auth)
    assert r.json()["source"] == "strong" and r.json()["created"] == 1
    bad = client.post("/api/strength/import", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")}, headers=auth)
    assert bad.status_code == 422


def test_tracks_from_streams():
    from app import tracks
    start = datetime(2026, 10, 1, 8, 0)
    n = 120
    res = tracks.from_streams(start, list(range(0, n * 5, 5)), [52.5 + i * 0.0002 for i in range(n)],
                              [13.4 + i * 0.0002 for i in range(n)], [40 + (i % 10) for i in range(n)],
                              [130 + i % 20 for i in range(n)])
    assert res is not None
    poly, details = res
    assert poly and details["profile"]["ll"] and details["profile"]["h"]
    assert tracks.from_streams(start, [], None, None) is None


def test_track_is_not_overwritten_by_summary(db, user):
    from app.models import Activity
    from app.store import ActivityIn, Writer
    w = Writer(db, user.id, "strava")
    row = w.activity(ActivityIn(source_id="t1", start=datetime(2026, 10, 2, 8), distance_m=5000, polyline="abc"))
    row.details = {"track": "ok", "profile": {"d": [0, 1]}}
    row.polyline = "genau"
    db.commit()
    w.activity(ActivityIn(source_id="t1", start=datetime(2026, 10, 2, 8), distance_m=5000, polyline="grob", details={"x": 1}))
    again = db.get(Activity, row.id)
    assert again.polyline == "genau" and again.details["profile"] and again.details["x"] == 1


def test_parse_dates_in_any_language():
    from app.strength import _parse_dt
    a = _parse_dt("28 Oct 2026, 18:05")
    for t in ("28. Okt. 2026, 18:05", "28 Okt 2026, 18:05", "Oct 28, 2026, 6:05 PM", "28.10.2026 18:05", "2026-10-28 18:05:00",
              "28 Oktober 2026 18:05"):
        assert _parse_dt(t) == a, t


def test_import_german_hevy_and_errors(client, auth):
    german = HEVY_CSV.replace("28 Oct 2026", "28. Okt. 2026")
    r = client.post("/api/strength/import", files={"file": ("workouts.csv", german.encode(), "text/csv")}, headers=auth)
    assert r.status_code == 200 and r.json()["created"] == 1, r.text
    broken = HEVY_CSV.replace("28 Oct 2026, 18:05", "irgendwann")
    r = client.post("/api/strength/import", files={"file": ("w.csv", broken.encode(), "text/csv")}, headers=auth)
    assert r.status_code == 422 and "irgendwann" in r.json()["detail"]
    import io as _io
    import zipfile as _zf
    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w") as z:
        z.writestr("workouts.csv", HEVY_CSV.replace("Pull", "Zip Pull"))
    r = client.post("/api/strength/import", files={"file": ("export.zip", buf.getvalue(), "application/zip")}, headers=auth)
    assert r.status_code == 200 and r.json()["created"] == 1, r.text


def test_chunked_gzip_import(client, auth):
    import gzip
    import time
    data = gzip.compress(HEVY_CSV.replace("Pull", "Chunk Pull").encode())
    half = len(data) // 2
    parts = [data[:half], data[half:]]
    res = None
    for i, part in enumerate(parts):
        r = client.post("/api/strength/import/chunk", content=part, headers={
            **auth, "X-Upload-Id": "testupload01", "X-Chunk-Index": str(i), "X-Chunk-Total": "2"})
        assert r.status_code == 200, r.text
        res = r.json()
    job = res["job_id"]
    for _ in range(100):
        st = client.get(f"/api/strength/import/{job}", headers=auth).json()
        if st["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert st["status"] == "done", st
    assert st["result"]["created"] == 1
    bad = client.post("/api/strength/import/chunk", content=b"x", headers={
        **auth, "X-Upload-Id": "../../etc", "X-Chunk-Index": "0", "X-Chunk-Total": "1"})
    assert bad.status_code == 422


def test_guess_muscles_for_unknown_exercises(client, auth):
    from app.strength_catalog import guess_muscles
    assert guess_muscles("Lat Pulldown - Wide Grip (Cable)")[0] == "lats"
    assert guess_muscles("Leg Curl (Machine)")[0] == "hamstrings"
    assert guess_muscles("Bicep Curl (Cable)")[0] == "biceps"
    assert guess_muscles("Glute Kickback on Machine")[0] == "glutes"
    assert guess_muscles("Völlig unbekannt") is None
    csv = HEVY_CSV.replace("Mystery Machine Row", "Single Arm Cable Curl").replace("Pull", "Guess Pull")
    client.post("/api/strength/import", files={"file": ("w.csv", csv.encode(), "text/csv")}, headers=auth)
    ex = next(e for e in client.get("/api/strength/exercises", headers=auth).json() if e["name"] == "Single Arm Cable Curl")
    assert ex["primary"] == "biceps" and ex["custom"]


def test_body_load_combines_strength_and_sports(client, auth, db):
    from datetime import date
    from app.models import User
    from app.store import ActivityIn, Writer
    bench = _ex(client, auth, "Bankdrücken (Langhantel)")
    now = datetime.utcnow().replace(microsecond=0) - timedelta(hours=3)
    client.post("/api/strength/workouts", json=_workout(now, 60, ex_id=bench["id"]), headers=auth)
    me = client.get("/api/me", headers=auth).json()
    u = db.get(User, me["id"])
    w = Writer(db, u.id, "strava")
    w.activity(ActivityIn(source_id="ride1", start=now - timedelta(hours=1), sport_raw="Ride", duration_s=3600, distance_m=30000))
    w.activity(ActivityIn(source_id="boulder1", start=now - timedelta(days=1), sport_raw="Bouldering", duration_s=5400))
    w.flush()
    r = client.get("/api/strength/body-load?days=7", headers=auth).json()
    m = {x["muscle"]: x for x in r["muscles"]}
    assert m["chest"]["strength"] == 3 and m["triceps"]["strength"] == 1.5
    assert m["quads"]["sports"] >= 6  # 60 Minuten Rad
    assert m["forearms"]["sports"] >= 9  # 90 Minuten Bouldern
    assert {s["sport"] for s in r["sources"]} >= {"ride", "climb"}
    assert [c["key"] for c in r["categories"]][0] == "strength" and {"ride", "climb"} <= {c["key"] for c in r["categories"]}
    assert m["quads"]["by"]["ride"] >= 6 and "climb" not in m["quads"]["by"] and m["forearms"]["by"]["climb"] >= 9
    assert date.today()


ROUTINE_CSV = '''title,folder_title,exercise_title,set_type,weight_kg,reps,rest_seconds
"Push A","PPL","Bench Press (Barbell)",normal,80,8,120
"Push A","PPL","Bench Press (Barbell)",normal,80,8,120
"Push A","PPL","Lateral Raise (Dumbbell)",normal,10,15,60
"Beine","PPL","Squat (Barbell)",normal,100,5,180
'''


def test_import_routines_csv(client, auth):
    r = client.post("/api/strength/import", files={"file": ("routines.csv", ROUTINE_CSV.encode(), "text/csv")}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "routines" and r.json()["created"] == 2
    routines = {x["name"]: x for x in client.get("/api/strength/routines", headers=auth).json()}
    push = routines["Push A"]
    assert push["folder"] == "PPL" and len(push["exercises"]) == 2 and len(push["exercises"][0]["sets"]) == 2
    assert push["exercises"][0]["rest_s"] == 120
    again = client.post("/api/strength/import", files={"file": ("routines.csv", ROUTINE_CSV.encode(), "text/csv")}, headers=auth).json()
    assert again["created"] == 0 and again["updated"] == 2


def test_link_whoop_to_strength_workout(client, auth, db):
    from app.models import User
    from app.store import ActivityIn, Writer
    bench = _ex(client, auth, "Bankdrücken (Langhantel)")
    t0 = datetime(2026, 8, 3, 16, 0)
    w = client.post("/api/strength/workouts", json=_workout(t0, 70, ex_id=bench["id"]), headers=auth).json()
    assert w["linked"]["avg_hr"] is None
    me = client.get("/api/me", headers=auth).json()
    u = db.get(User, me["id"])
    wr = Writer(db, u.id, "whoop")
    # WHOOP erkennt das Training 12 Minuten später und etwas kürzer
    wr.activity(ActivityIn(source_id="wh1", start=t0 + timedelta(minutes=12), sport_raw="weightlifting", duration_s=40 * 60,
                           avg_hr=118, max_hr=161, calories=310, load=9.4,
                           details={"hr_zones": [60, 600, 900, 600, 240, 0]}))
    # ein Spaziergang am Abend gehört nicht dazu
    wr.activity(ActivityIn(source_id="wh2", start=t0 + timedelta(hours=3), sport_raw="walking", duration_s=1800, avg_hr=95))
    wr.flush()
    full = client.get(f"/api/strength/workouts/{w['id']}", headers=auth).json()
    linked = full["linked"]
    assert linked["avg_hr"] == 118 and linked["load"] == 9.4 and linked["hr_zones"][2] == 900
    assert linked["filled_from"]["avg_hr"] == "WHOOP"
    assert {s["source"] for s in linked["sources"]} == {"strength", "whoop"}
    whoop_id = next(s["id"] for s in linked["sources"] if s["source"] == "whoop")
    walk = next(c for c in linked["candidates"] if c["sport"] == "walk")

    # Lösen: Werte verschwinden wieder
    r = client.post(f"/api/activities/{whoop_id}/unlink", headers=auth).json()
    assert r["avg_hr"] is None and len(r["sources"]) == 1
    # automatischer Abgleich verknüpft es nicht erneut
    wr.activity(ActivityIn(source_id="wh1", start=t0 + timedelta(minutes=12), sport_raw="weightlifting", duration_s=40 * 60,
                           avg_hr=118))
    wr.flush()
    assert client.get(f"/api/strength/workouts/{w['id']}", headers=auth).json()["linked"]["avg_hr"] is None
    # von Hand verknüpfen
    r = client.post(f"/api/activities/{walk['id']}/link", json={"target_id": r["activity_id"]}, headers=auth).json()
    assert r["avg_hr"] == 95 and any(s["manual"] for s in r["sources"])


def test_overlap_rules():
    from app.models import Activity
    from app.store import _similar
    base = datetime(2026, 8, 3, 16, 0)
    a = Activity(start=base, duration_s=3600, sport="strength", source="strength")
    assert _similar(a, Activity(start=base + timedelta(minutes=10), duration_s=2700, sport="cardio", source="whoop"))
    assert not _similar(a, Activity(start=base + timedelta(minutes=10), duration_s=2700, sport="ride", source="whoop"))
    assert not _similar(a, Activity(start=base + timedelta(minutes=50), duration_s=3600, sport="strength", source="whoop"))


def test_german_names_get_muscles():
    from app.strength_catalog import guess_muscles
    assert guess_muscles("Knieheben am Barren")[0] == "abs"
    assert guess_muscles("Nackendrücken")[0] == "shoulders"


def test_exercise_media(client, auth):
    from app import strength_media
    from app.strength_catalog import CATALOG
    idx = strength_media.index()
    assert len(idx) > 800
    assert all(v in idx for v in strength_media.OVERRIDES.values() if v)
    with_media = [c for c in CATALOG if strength_media.media_for_catalog(c["key"], [*c["aliases"], c["name"]], c["equipment"])]
    assert len(with_media) >= len(CATALOG) - 3
    items = client.get("/api/strength/exercises", headers=auth).json()
    bench = next(e for e in items if e["name"] == "Bankdrücken (Langhantel)")
    assert bench["media"] == "Barbell_Bench_Press_-_Medium_Grip"
    detail = client.get(f"/api/strength/exercises/{bench['id']}", headers=auth).json()
    assert detail["media"]["instructions"]
    assert client.get("/api/strength/media/..%2Fetc/0.jpg", headers=auth).status_code == 404
    assert client.get("/api/strength/media/Nicht_Vorhanden/0.jpg", headers=auth).status_code == 404
    res = client.get("/api/strength/media/search?q=lunge", headers=auth).json()
    assert any("Lunge" in r["name"] for r in res)
    custom = client.post("/api/strength/exercises", json={"name": "Wide-Grip Lat Pulldown", "equipment": "cable", "primary": "lats"}, headers=auth).json()
    assert custom["media"] == "Wide-Grip_Lat_Pulldown"
    r = client.put(f"/api/strength/exercises/{custom['id']}", json={**custom, "media": "gibt-es-nicht"}, headers=auth)
    assert r.status_code == 422
