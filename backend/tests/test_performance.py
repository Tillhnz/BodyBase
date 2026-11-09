from datetime import datetime, timedelta

from conftest import register


def _ride(client, headers, token, start, minutes, watts, name):
    payload = {"timestamp": start.isoformat() + "Z", "app_version": "1", "exercise": [{
        "type": "biking", "title": name, "start_time": start.isoformat() + "Z",
        "end_time": (start + timedelta(minutes=minutes)).isoformat() + "Z", "duration_seconds": minutes * 60}]}
    assert client.post("/api/ingest/health-connect", json=payload, headers={"X-API-Key": token}).status_code == 200


def test_ftp_vo2_and_notices(client):
    headers, _ = register(client)
    # erster Aufruf: nichts Altes hochspülen
    first = client.get("/api/notices", headers=headers).json()
    assert first["activities"] == [] and first["ftp"] is None
    token = client.get("/api/me/ingest", headers=headers).json()["token"]
    now = datetime.utcnow().replace(microsecond=0) - timedelta(hours=3)
    _ride(client, headers, token, now, 45, 220, "Feierabendrunde")
    from app.database import SessionLocal
    from app.models import Activity
    with SessionLocal() as db:  # Wattmesser-Daten wie aus einer FIT-Datei
        a = db.query(Activity).filter(Activity.name == "Feierabendrunde").first()
        a.details = {"pc": {"300": 300, "1200": 250, "60": 400}}
        db.commit()
    client.post("/api/entries", headers=headers, json={"metric": "weight", "value": 75})
    perf = client.get("/api/performance", headers=headers).json()
    assert perf["ftp"] == 238 and perf["vo2max"] > 45
    n = client.get("/api/notices", headers=headers).json()
    assert [x["name"] for x in n["activities"]] == ["Feierabendrunde"]
    assert n["ftp"]["new"] == 238
    client.post("/api/notices/seen", headers=headers, json={"activity_id": n["max_id"], "ftp": 238})
    again = client.get("/api/notices", headers=headers).json()
    assert again["activities"] == [] and again["ftp"] is None
