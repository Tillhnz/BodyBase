from datetime import datetime, timedelta

from conftest import register


def test_ftp_vo2_and_notices(client):
    headers, _ = register(client)
    # erster Aufruf: nichts Altes hochspülen
    first = client.get("/api/notices", headers=headers).json()
    assert first["activities"] == [] and first["ftp"] is None
    me = client.get("/api/me", headers=headers).json()
    from app.database import SessionLocal
    from app.store import ActivityIn, Writer
    now = datetime.utcnow().replace(microsecond=0) - timedelta(hours=3)
    with SessionLocal() as db:  # Fahrt mit Wattmesser-Daten wie aus einer FIT-Datei
        w = Writer(db, me["id"], "files")
        w.activity(ActivityIn(source_id="r1", start=now, sport_raw="Ride", name="Feierabendrunde", duration_s=2700,
                              avg_power=220, details={"pc": {"300": 300, "1200": 250, "60": 400}}))
        w.flush()
    client.post("/api/entries", headers=headers, json={"metric": "weight", "value": 75})
    perf = client.get("/api/performance", headers=headers).json()
    assert perf["ftp"] == 238 and perf["vo2max"] > 45
    n = client.get("/api/notices", headers=headers).json()
    assert [x["name"] for x in n["activities"]] == ["Feierabendrunde"]
    assert n["ftp"]["new"] == 238
    client.post("/api/notices/seen", headers=headers, json={"activity_id": n["max_id"], "ftp": 238})
    again = client.get("/api/notices", headers=headers).json()
    assert again["activities"] == [] and again["ftp"] is None
