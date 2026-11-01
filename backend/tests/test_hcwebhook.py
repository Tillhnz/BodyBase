from datetime import date, timedelta


def _payload(day):
    d = day.isoformat()
    return {
        "timestamp": f"{d}T20:00:00Z", "app_version": "1.9.30", "timezone": "Europe/Berlin",
        "steps": [{"count": 4000, "start_time": f"{d}T08:00:00+01:00", "end_time": f"{d}T12:00:00+01:00"},
                  {"count": 3500, "start_time": f"{d}T12:00:00+01:00", "end_time": f"{d}T18:00:00+01:00"}],
        "heart_rate": [{"time": f"{d}T09:00:00+01:00", "avg": 72, "min": 68, "max": 80, "bpm": 72}],
        "resting_heart_rate": [{"bpm": 54, "time": f"{d}T07:00:00+01:00"}],
        "weight": [{"kilograms": 79.3, "time": f"{d}T07:05:00+01:00"}],
        "blood_glucose": [{"mmol_per_liter": 5.5, "time": f"{d}T07:10:00+01:00"}],
        "sleep": [{"session_end_time": f"{d}T06:30:00+01:00", "duration_seconds": 27000, "stages": [
            {"stage": "STAGE_TYPE_DEEP", "start_time": f"{d}T00:00:00+01:00", "end_time": f"{d}T01:30:00+01:00", "duration_seconds": 5400},
            {"stage": "6", "start_time": f"{d}T01:30:00+01:00", "end_time": f"{d}T03:00:00+01:00", "duration_seconds": 5400},
            {"stage": "light", "start_time": f"{d}T03:00:00+01:00", "end_time": f"{d}T06:00:00+01:00", "duration_seconds": 10800},
            {"stage": "awake", "start_time": f"{d}T06:00:00+01:00", "end_time": f"{d}T06:30:00+01:00", "duration_seconds": 1800}]}],
        "exercise": [{"type": "EXERCISE_TYPE_RUNNING", "start_time": f"{d}T17:00:00+01:00", "end_time": f"{d}T17:40:00+01:00",
                      "duration_seconds": 2400, "distance_meters": 7000}],
        "deleted": [{"type": "steps", "id": "abc"}],
    }


def test_hc_webhook(client, auth):
    from app.timeutil import today
    token = client.get("/api/me/ingest", headers=auth).json()["token"]
    day = today() - timedelta(days=1)
    r = client.post("/api/ingest/health-connect", json=_payload(day), headers={"X-API-Key": token})
    assert r.status_code == 200, r.text
    assert r.json()["records"] >= 8
    # erneut gesendet (z. B. nach Bearbeitung): ersetzt statt verdoppelt
    client.post("/api/ingest/health-connect", json=_payload(day), headers={"X-API-Key": token})
    steps = client.get("/api/metrics/steps?days=7", headers=auth).json()["series"]
    assert any(p["day"] == day.isoformat() and p["value"] == 7500 for p in steps)
    glu = client.get("/api/metrics/glucose?days=7", headers=auth).json()["series"][-1]["value"]
    assert abs(glu - 99.1) < 0.5
    nights = client.get("/api/sleep?days=7", headers=auth).json()["nights"]
    n = next(x for x in nights if x["deep_min"])
    assert round(n["deep_min"]) == 90 and round(n["rem_min"]) == 90 and round(n["asleep_min"]) == 360
    acts = client.get("/api/activities", headers=auth).json()["items"]
    assert acts[0]["sport"] == "run" and acts[0]["distance_m"] == 7000
    # auch an die allgemeine Adresse geschickt wird es erkannt
    r = client.post("/api/ingest/json", json=_payload(day - timedelta(days=1)), headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["records"] >= 8
    assert date.today()
