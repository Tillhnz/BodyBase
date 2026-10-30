from datetime import date, timedelta


def test_target_grows_each_monday():
    from app.habits import target_for
    from app.models import Habit
    h = Habit(kind="count", target=20, increment=5, max_target=40, start=date(2026, 10, 1))  # Donnerstag
    assert target_for(h, date(2026, 10, 4)) == 20   # Sonntag derselben Woche
    assert target_for(h, date(2026, 10, 5)) == 25   # Montag
    assert target_for(h, date(2026, 10, 19)) == 35
    assert target_for(h, date(2027, 1, 1)) == 40    # gedeckelt


def test_habit_flow_and_body_map(client, auth):
    exs = client.get("/api/strength/exercises", headers=auth).json()
    push_up = next(e for e in exs if e["name"] == "Liegestütze")
    start = (date.today() - timedelta(days=9)).isoformat()
    r = client.post("/api/habits", json={"name": "Liegestütze", "target": 20, "increment": 5, "exercise_id": push_up["id"],
                                         "start": start}, headers=auth)
    assert r.status_code == 201, r.text
    h = r.json()
    assert h["unit"] == "Wdh."
    for i in range(9, 0, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        client.post(f"/api/habits/{h['id']}/log", json={"day": d, "value": 60}, headers=auth)
    h = client.post(f"/api/habits/{h['id']}/log", json={"add": 10}, headers=auth).json()
    assert h["today"]["value"] == 10 and not h["today"]["done"]
    assert h["streak"] == 9  # heute noch offen: Serie zählt bis gestern
    h = client.post(f"/api/habits/{h['id']}/log", json={"value": 100}, headers=auth).json()
    assert h["today"]["done"] and h["streak"] == 10
    assert client.post(f"/api/habits/{h['id']}/log", json={"day": "2999-01-01", "value": 1}, headers=auth).status_code == 422

    load = client.get("/api/strength/body-load?days=30", headers=auth).json()
    chest = next(m for m in load["muscles"] if m["muscle"] == "chest")
    assert chest["habits"] == round((9 * 60 + 100) / 12, 1)
    assert load["habits"][0]["habit"] == "Liegestütze"

    tips = client.get("/api/insights", headers=auth).json()
    assert any("10 Tage in Folge" in t["title"] for t in tips)
    assert any(t["type"] == "warn" and t.get("group") == "Beine" for t in tips)  # nur Brust trainiert
    leg = next(t for t in tips if t.get("group") == "Beine")
    assert leg["exercises"]

    assert client.post("/api/habits", json={"name": "x", "kind": "count"}, headers=auth).status_code == 422
    chk = client.post("/api/habits", json={"name": "Dehnen", "kind": "check", "weekdays": [0, 2, 4]}, headers=auth).json()
    assert chk["today"]["target"] == 1
    assert client.delete(f"/api/habits/{chk['id']}", headers=auth).status_code == 204
