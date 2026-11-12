from datetime import date, datetime, timedelta

from conftest import register


def test_habit_reminder_flow(client):
    headers, _ = register(client)
    h = client.post("/api/habits", headers=headers, json={"name": "Lesen", "kind": "check"}).json()
    r = client.put("/api/habit-reminder", headers=headers, json={"enabled": True, "time": "20:00", "topic": ""})
    assert r.status_code == 422  # ohne Thema geht es nicht (kein Admin-Server-Thema)
    r = client.put("/api/habit-reminder", headers=headers, json={"enabled": True, "time": "20:00", "topic": "mein-thema"})
    assert r.status_code == 200 and r.json()["enabled"]
    got = client.get("/api/habit-reminder", headers=headers).json()
    assert [o["name"] for o in got["open"]] == ["Lesen"]

    from app import reminders
    sent = []
    day = datetime.now(reminders.tz()).replace(hour=19, minute=59)
    assert reminders.run_once(day, sender=lambda *a: sent.append(a)) == 0
    assert reminders.run_once(day.replace(hour=20, minute=1), sender=lambda *a: sent.append(a)) >= 1
    mine = [s for s in sent if s[0] == "mein-thema"]
    assert mine and "Lesen" in mine[0][2] and "offen" in mine[0][1]
    # nur einmal am Tag
    sent.clear()
    reminders.run_once(day.replace(hour=21), sender=lambda *a: sent.append(a))
    assert not [s for s in sent if s[0] == "mein-thema"]
    # erledigt: keine Erinnerung mehr offen
    client.post(f"/api/habits/{h['id']}/log", headers=headers, json={"day": date.today().isoformat(), "value": 1})
    assert client.get("/api/habit-reminder", headers=headers).json()["open"] == []


def test_dynamic_sleep_need(client):
    headers, _ = register(client)
    base = client.get("/api/sleep/need", headers=headers).json()
    assert base["need"] == base["base"] == 480 and base["parts"][0]["key"] == "base"
    me = client.get("/api/me", headers=headers).json()
    from app.database import SessionLocal
    from app.models import SleepSession
    with SessionLocal() as db:
        for i in range(0, 7):
            d = date.today() - timedelta(days=i)
            end = datetime.combine(d, datetime.min.time()) + timedelta(hours=6)
            db.add(SleepSession(user_id=me["id"], source="files", source_id=f"n{i}", day=d, start=end - timedelta(hours=5),
                                end=end, asleep_min=300))
        db.commit()
    r = client.get("/api/sleep/need", headers=headers).json()
    assert r["need"] > 480 and any(p["key"] == "debt" for p in r["parts"])
    assert r["need"] <= 600 and len(r["history"]) == 14 and "bedtime" in r
