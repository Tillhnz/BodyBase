import io
import json
import zipfile
from datetime import timedelta

from conftest import register


def _app_today():
    """Kalendertag in der Zeitzone der App (nicht des Testrechners)."""
    from app.timeutil import today
    return today()



def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_register_login_me(client):
    headers, email = register(client)
    me = client.get("/api/me", headers=headers).json()
    assert me["email"] == email
    r = client.post("/api/auth/login", json={"email": email, "password": "falsch-falsch"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": email, "password": "geheim-123"})
    assert r.status_code == 200
    assert "bb_session" in r.cookies


def test_cookie_requires_app_header(client):
    _, email = register(client)
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": email, "password": "geheim-123"})
    assert r.status_code == 200
    # Cookie ohne App-Kennung: schreibende Anfragen werden abgelehnt (CSRF-Schutz)
    r = client.post("/api/entries", json={"metric": "weight", "value": 80})
    assert r.status_code == 403
    r = client.post("/api/entries", json={"metric": "weight", "value": 80}, headers={"X-BB-Request": "1"})
    assert r.status_code == 201
    client.cookies.clear()


def test_first_user_is_admin(client, auth):
    # Der erste Nutzer in der Test-Datenbank ist Administrator; spätere nicht
    headers, _ = register(client)
    assert client.get("/api/me", headers=headers).json()["role"] == "user"
    assert client.get("/api/admin/users", headers=headers).status_code == 403


def test_manual_entries_and_series(client, auth):
    for i, v in enumerate([81.2, 80.8, 80.5]):
        day = (_app_today() - timedelta(days=2 - i)).isoformat()
        r = client.post("/api/entries", json={"metric": "weight", "value": v, "time": f"{day}T07:30:00"}, headers=auth)
        assert r.status_code == 201, r.text
    r = client.post("/api/entries", json={"metric": "weight", "value": 900}, headers=auth)
    assert r.status_code == 422
    d = client.get("/api/metrics/weight?days=7", headers=auth).json()
    assert [p["value"] for p in d["series"]] == [81.2, 80.8, 80.5]
    assert d["stats"]["last"] == 80.5
    assert d["series"][0]["source"] == "manual"
    entries = client.get("/api/entries?metric=weight", headers=auth).json()
    assert len(entries) == 3
    assert client.delete(f"/api/entries/{entries[0]['id']}", headers=auth).status_code == 204


def test_demo_data_dashboard_and_views(client):
    headers, _ = register(client)
    r = client.post("/api/me/demo", headers=headers)
    assert r.status_code == 201, r.text
    dash = client.get("/api/dashboard", headers=headers).json()
    assert dash["has_data"] and dash["demo"]
    assert dash["rings"][0]["key"] == "steps"
    assert dash["readiness"] is not None
    summary = client.get("/api/summary?keys=weight,resting_hr,hrv", headers=headers).json()
    assert all(s["last"] for s in summary)
    # Schritte von Garmin und Apple Health: Garmin hat laut Rangfolge Vorrang
    steps = client.get("/api/metrics/steps?days=30", headers=headers).json()
    assert {p["source"] for p in steps["series"]} == {"garmin"}
    week = client.get("/api/metrics/steps?days=90&group=week", headers=headers).json()
    assert len(week["series"]) >= 12
    acts = client.get("/api/activities?limit=200", headers=headers).json()
    assert acts["total"] > 20
    assert all(a["source"] == "garmin" for a in acts["items"]), "Strava-Doppel sollen unter Garmin zusammengefasst sein"
    assert any("Strava" in a["also_in"] for a in acts["items"])
    detail = client.get(f"/api/activities/{acts['items'][0]['id']}", headers=headers).json()
    assert detail["versions"][0]["primary"]
    stats = client.get("/api/activities/stats?days=180", headers=headers).json()
    assert stats["sports"] and stats["load"]
    sleep = client.get("/api/sleep?days=30", headers=headers).json()
    assert len(sleep["nights"]) >= 28 and sleep["avg"]["asleep_min"] > 300
    comp = client.get("/api/compare?a=hrv&b=resting_hr&days=90", headers=headers).json()
    assert comp["r"] is not None and len(comp["pairs"]) > 30
    assert client.post("/api/me/demo", headers=headers).status_code == 409
    assert client.delete("/api/me/demo", headers=headers).status_code == 204
    assert not client.get("/api/dashboard", headers=headers).json()["has_data"]


def test_priority_override(client):
    headers, _ = register(client)
    client.post("/api/me/demo", headers=headers)
    r = client.put("/api/me/prefs", json={"priority": {"steps": ["apple_health"]}}, headers=headers)
    assert r.status_code == 200
    steps = client.get("/api/metrics/steps?days=14", headers=headers).json()
    assert {p["source"] for p in steps["series"]} == {"apple_health"}


def test_ingest_health_auto_export(client):
    headers, _ = register(client)
    info = client.get("/api/me/ingest", headers=headers).json()
    token = info["token"]
    assert token.startswith("bb_")
    today = _app_today().isoformat()
    payload = {"data": {"metrics": [
        {"name": "step_count", "units": "count", "data": [{"date": f"{today} 00:00:00 +0100", "qty": 7345}]},
        {"name": "weight_body_mass", "units": "lb", "data": [{"date": f"{today} 07:00:00 +0100", "qty": 176.4}]},
        {"name": "heart_rate", "units": "count/min", "data": [{"date": f"{today} 08:00:00 +0100", "Min": 50, "Avg": 62, "Max": 90}]},
        {"name": "blood_pressure", "units": "mmHg", "data": [{"date": f"{today} 07:05:00 +0100", "systolic": 121, "diastolic": 79}]},
        {"name": "sleep_analysis", "units": "hr", "data": [{"date": today, "totalSleep": 7.2, "deep": 1.1, "rem": 1.6, "core": 4.5,
                                                            "awake": 0.3, "sleepStart": f"{today} 00:10:00 +0100",
                                                            "sleepEnd": f"{today} 07:40:00 +0100"}]},
    ], "workouts": [{"id": "W1", "name": "Outdoor Run", "start": f"{today} 06:00:00 +0100", "end": f"{today} 06:45:00 +0100",
                     "duration": 2700, "distance": {"qty": 8.2, "units": "km"}, "activeEnergyBurned": {"qty": 2400, "units": "kJ"}}]}}
    r = client.post("/api/ingest/health-auto-export", json=payload)
    assert r.status_code == 401
    r = client.post("/api/ingest/health-auto-export", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert client.get("/api/metrics/steps?days=2", headers=headers).json()["series"][-1]["value"] == 7345
    w = client.get("/api/metrics/weight?days=2", headers=headers).json()["series"][-1]["value"]
    assert abs(w - 80.01) < 0.05
    acts = client.get("/api/activities", headers=headers).json()["items"]
    assert acts[0]["sport"] == "run" and round(acts[0]["distance_m"]) == 8200 and round(acts[0]["calories"]) == 574
    nights = client.get("/api/sleep?days=2", headers=headers).json()["nights"]
    assert round(nights[-1]["asleep_min"]) == 432
    # neuer Schlüssel: der alte gilt nicht mehr
    new = client.post("/api/me/ingest/rotate", headers=headers).json()["token"]
    assert client.post("/api/ingest/json", json={}, headers={"Authorization": f"Bearer {token}"}).status_code == 401
    r = client.post("/api/ingest/json", headers={"Authorization": f"Bearer {new}"}, json={
        "source": "health_connect", "samples": [{"metric": "resting_hr", "value": 52, "date": today}]})
    assert r.status_code == 200 and r.json()["counts"]["samples"] == 1


def test_csv_import(client):
    headers, _ = register(client)
    csv_data = "Datum;Gewicht (kg);Körperfett (%);Schritte\n28.10.2026;80,4;19,5;10234\n29.10.2026;80,1;19,4;8000\n"
    r = client.post("/api/imports/csv", files={"file": ("waage.csv", csv_data.encode(), "text/csv")}, headers=headers)
    assert r.status_code == 200, r.text
    assert set(r.json()["columns"]) == {"weight", "body_fat", "steps"}
    d = client.get("/api/metrics/weight?start=2026-10-27&end=2026-10-30", headers=headers).json()
    assert [p["value"] for p in d["series"]] == [80.4, 80.1]


GPX = """<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Testlauf</name><type>running</type><trkseg>
{pts}</trkseg></trk></gpx>"""


def test_file_import(client):
    headers, _ = register(client)
    pts = "".join(f'<trkpt lat="{53.55 + i * 0.0002:.5f}" lon="{9.99:.5f}"><time>2026-10-01T06:{i // 60:02d}:{i % 60:02d}Z</time></trkpt>'
                  for i in range(0, 600, 5))
    r = client.post("/api/imports/files", files=[("files", ("lauf.gpx", GPX.format(pts=pts).encode(), "application/gpx+xml"))], headers=headers)
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["ok"], res
    acts = client.get("/api/activities", headers=headers).json()["items"]
    assert acts[0]["sport"] == "run" and acts[0]["has_map"]


def test_apple_health_export_upload(client):
    headers, _ = register(client)
    xml = """<?xml version="1.0" encoding="UTF-8"?><HealthData locale="de_DE">
<Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" startDate="2026-10-01 08:00:00 +0200" endDate="2026-10-01 09:00:00 +0200" value="3000"/>
<Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" unit="count" startDate="2026-10-01 08:00:00 +0200" endDate="2026-10-01 09:00:00 +0200" value="3500"/>
<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Waage" unit="kg" startDate="2026-10-01 07:00:00 +0200" endDate="2026-10-01 07:00:00 +0200" value="79.9"/>
<Record type="HKQuantityTypeIdentifierOxygenSaturation" sourceName="Watch" unit="%" startDate="2026-10-01 03:00:00 +0200" endDate="2026-10-01 03:00:00 +0200" value="0.97"/>
<Workout workoutActivityType="HKWorkoutActivityTypeCycling" duration="60" durationUnit="min" totalDistance="25" totalDistanceUnit="km" totalEnergyBurned="600" totalEnergyBurnedUnit="kcal" sourceName="Watch" startDate="2026-10-01 17:00:00 +0200" endDate="2026-10-01 18:00:00 +0200"/>
</HealthData>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("apple_health_export/export.xml", xml)
    r = client.post("/api/imports/apple-health", content=buf.getvalue(), headers={**headers, "X-Filename": "export.zip"})
    assert r.status_code == 202, r.text
    import time
    for _ in range(50):
        jobs = client.get("/api/imports/jobs", headers=headers).json()
        if jobs[0]["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert jobs[0]["status"] == "done", jobs[0]
    steps = client.get("/api/metrics/steps?start=2026-10-01&end=2026-10-01", headers=headers).json()["series"]
    assert steps[0]["value"] == 3500  # iPhone und Uhr werden nicht addiert
    spo2 = client.get("/api/metrics/spo2?start=2026-10-01&end=2026-10-01", headers=headers).json()["series"]
    assert spo2[0]["value"] == 97
    acts = client.get("/api/activities", headers=headers).json()["items"]
    assert acts[0]["sport"] == "ride" and acts[0]["distance_m"] == 25000


def test_providers_and_admin_app(client, admin):
    auth = admin
    provs = client.get("/api/providers", headers=auth).json()
    keys = {p["key"] for p in provs}
    assert {"strava", "garmin", "withings", "apple_health", "oura", "whoop", "fitbit", "polar", "intervals"} <= keys
    strava = next(p for p in provs if p["key"] == "strava")
    assert strava["redirect_uri"] == "https://bodybase.example.de/api/oauth/strava/callback"
    r = client.put("/api/admin/providers/strava", json={"values": {"client_id": "123", "client_secret": "abc"}}, headers=auth)
    assert r.status_code == 200 and r.json()["ready"]
    assert r.json()["values"]["client_secret"] == ""  # Geheimnis wird nie zurückgegeben
    url = client.post("/api/connections/strava/authorize", headers=auth).json()["url"]
    assert url.startswith("https://www.strava.com/oauth/authorize?") and "client_id=123" in url and "activity%3Aread_all" in url
    r = client.put("/api/admin/providers/strava", json={"values": {"client_id": "456", "client_secret": ""}}, headers=auth)
    assert r.json()["values"]["client_secret__set"] is True


def test_oauth_callback_rejects_bad_state(client):
    r = client.get("/api/oauth/strava/callback?code=x&state=kaputt", follow_redirects=False)
    assert r.status_code == 303 and "error=" in r.headers["location"]


def test_export(client):
    headers, _ = register(client)
    client.post("/api/entries", json={"metric": "waist", "value": 84}, headers=headers)
    r = client.get("/api/me/export", headers=headers)
    data = json.loads(r.content)
    assert data["samples"][0]["metric"] == "waist"
    r = client.get("/api/me/export?fmt=csv", headers=headers)
    assert r.text.splitlines()[0].startswith("time_utc")


def test_delete_account(client):
    headers, _ = register(client)
    assert client.post("/api/me/delete", json={"password": "falsch"}, headers=headers).status_code == 403
    assert client.post("/api/me/delete", json={"password": "geheim-123"}, headers=headers).status_code == 204
    assert client.get("/api/me", headers=headers).status_code == 401


def test_admin_public_url(client, admin):
    from app.config import settings
    before = settings.public_url
    try:
        r = client.put("/api/admin/settings", json={"values": {"public_url": "https://neu.example.de/"}}, headers=admin)
        assert r.status_code == 200 and r.json()["values"]["public_url"] == "https://neu.example.de"
        provs = client.get("/api/providers", headers=admin).json()
        withings = next(p for p in provs if p["key"] == "withings")
        assert withings["redirect_uri"] == "https://neu.example.de/api/oauth/withings/callback"
        for bad in ("neu.example.de", "ftp://x.de", "https://x.de/pfad"):
            r = client.put("/api/admin/settings", json={"values": {"public_url": bad}}, headers=admin)
            assert r.status_code == 422
    finally:
        client.put("/api/admin/settings", json={"values": {"public_url": before}}, headers=admin)
