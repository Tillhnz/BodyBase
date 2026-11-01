from datetime import datetime, timedelta


def test_body_segments_auto_labels_and_regions(client, auth, db):
    from app.models import User
    from app import segments
    me = client.get("/api/me", headers=auth).json()
    u = db.get(User, me["id"])
    assert client.get("/api/body-segments", headers=auth).json() == {"has_data": False}
    t0 = datetime.utcnow().replace(microsecond=0) - timedelta(days=60)
    # Withings-Codes: 12 Rumpf, 10/11 Beine, 2/3 Arme; 99 unbekannt (wird nach Größe zugeordnet)
    base = {12: 27.0, 10: 10.0, 11: 10.1, 2: 3.4, 3: 3.5, 99: 3.0}
    for i, ts in enumerate([t0, t0 + timedelta(days=55)]):
        for pos, v in base.items():
            gain = 0.3 if pos in (10, 11) and i else 0
            segments.store(db, u.id, "withings", ts, "muscle", pos, v + gain)
            segments.store(db, u.id, "withings", ts, "fat", pos, 2.0 - 0.1 * i)
    db.commit()
    r = client.get("/api/body-segments?days=90", headers=auth).json()
    parts = {s["position"]: s["part"] for s in r["segments"]}
    assert parts[12] == "torso" and parts[10] == "left_leg" and parts[11] == "right_leg"
    assert parts[2] == "right_arm" and parts[3] == "left_arm" and parts[99] in ("torso", "leg", "arm")
    legs = next(x for x in r["regions"] if x["region"] == "Beine")
    assert legs["change_kg"] == 0.6 and legs["comment"]
    assert {s["label"] for s in r["segments"]} >= {"Linkes Bein", "Rechtes Bein", "Rumpf", "Linker Arm", "Rechter Arm"}
    r = client.put("/api/body-segments/labels", json={"labels": {"99": "ignore"}}, headers=auth).json()
    assert next(s for s in r["segments"] if s["position"] == 99)["part"] == "ignore" and r["custom_labels"]
    assert client.put("/api/body-segments/labels", json={"labels": {"12": "kopf"}}, headers=auth).status_code == 422


def test_duplicates_and_merge(client, auth):
    items = client.get("/api/strength/exercises", headers=auth).json()
    latzug = next(e for e in items if e["name"] == "Latzug (Kabel)")
    dup = client.post("/api/strength/exercises", json={"name": "Latziehen (Kabel)", "equipment": "cable", "primary": "lats"},
                      headers=auth).json()
    assert dup["media"] == latzug["media"]  # Bild über die gleichnamige eingebaute Übung
    t0 = datetime(2026, 6, 1, 18, 0)
    client.post("/api/strength/workouts", json={"name": "Pull", "start": t0.isoformat() + "Z", "exercises": [
        {"exercise_id": dup["id"], "sets": [{"kg": 50, "reps": 10}, {"kg": 55, "reps": 8}]}]}, headers=auth)
    d = client.get("/api/strength/duplicates", headers=auth).json()
    pair = next(x for x in d if x["drop"]["id"] == dup["id"])
    assert pair["keep"]["id"] == latzug["id"]
    r = client.post(f"/api/strength/exercises/{dup['id']}/merge", json={"into": latzug["id"]}, headers=auth).json()
    assert r["moved_sets"] == 2
    stats = client.get(f"/api/strength/exercises/{latzug['id']}", headers=auth).json()
    assert stats["total"]["sessions"] >= 1
    assert all(x["drop"]["id"] != dup["id"] for x in client.get("/api/strength/duplicates", headers=auth).json())
    # eingebaute Übungen lassen sich nicht wegführen
    assert client.post(f"/api/strength/exercises/{latzug['id']}/merge", json={"into": dup["id"]}, headers=auth).status_code == 422
