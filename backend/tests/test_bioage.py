from datetime import date, datetime, timedelta

from conftest import register


def test_bioage_needs_birth_year_and_data(client):
    headers, _ = register(client)
    r = client.get("/api/bio-age", headers=headers).json()
    assert r["ready"] is False and "Geburtsjahr" in r["reason"]
    client.put("/api/me/profile", headers=headers, json={"birth_year": date.today().year - 40, "sex": "m", "height_cm": 180})
    r = client.get("/api/bio-age", headers=headers).json()
    assert r["ready"] is False and r["missing"]


def _fill(client, headers, rhr, hrv, steps, sleep_min, vo2, weight):
    me = client.get("/api/me", headers=headers).json()
    from app.database import SessionLocal
    from app.store import Writer, day_ts
    with SessionLocal() as db:
        w = Writer(db, me["id"], "files")
        for i in range(40):
            t = day_ts(date.today() - timedelta(days=i))
            w.sample("resting_hr", t, rhr)
            w.sample("hrv", t, hrv)
            w.sample("steps", t, steps)
            w.sample("sleep_duration", t, sleep_min)
        w.sample("vo2max", day_ts(date.today()), vo2)
        w.sample("weight", day_ts(date.today()), weight)
        w.flush_samples()
        db.commit()


def test_bioage_fit_is_younger(client):
    headers, _ = register(client)
    client.put("/api/me/profile", headers=headers, json={"birth_year": date.today().year - 40, "sex": "m", "height_cm": 180})
    _fill(client, headers, rhr=48, hrv=70, steps=11000, sleep_min=470, vo2=55, weight=74)
    r = client.get("/api/bio-age", headers=headers).json()
    assert r["ready"] and r["bio_age"] < r["age"] - 3
    keys = {f["key"] for f in r["factors"]}
    assert {"vo2max", "resting_hr", "hrv", "steps", "sleep", "bmi"} <= keys
    vo2 = next(f for f in r["factors"] if f["key"] == "vo2max")
    assert vo2["fitness_age"] < 30 and vo2["impact"] < 0
    assert r["history"][-1]["bio_age"] == r["bio_age"]


def test_bioage_unfit_is_older(client):
    headers, _ = register(client)
    client.put("/api/me/profile", headers=headers, json={"birth_year": date.today().year - 40, "sex": "f", "height_cm": 165})
    _fill(client, headers, rhr=78, hrv=22, steps=3000, sleep_min=340, vo2=26, weight=90)
    r = client.get("/api/bio-age", headers=headers).json()
    assert r["ready"] and r["bio_age"] > r["age"] + 3
    assert r["levers"] and all(x["years"] < 0 for x in r["levers"])
    assert abs(r["delta"]) <= 15


def test_habit_year_history_and_backfill(client):
    headers, _ = register(client)
    h = client.post("/api/habits", headers=headers, json={"name": "Dehnen", "kind": "check"}).json()
    last_year = date.today().year - 1
    r = client.post(f"/api/habits/{h['id']}/log", headers=headers, json={"day": f"{last_year}-03-05", "value": 1})
    assert r.status_code == 200
    hist = client.get(f"/api/habits/{h['id']}/history?year={last_year}", headers=headers).json()
    assert len(hist["days"]) in (365, 366)
    assert next(d for d in hist["days"] if d["day"] == f"{last_year}-03-05")["done"]
    assert hist["months"][2]["done"] == 1 and last_year in hist["years"]
    now = client.get(f"/api/habits/{h['id']}/history", headers=headers).json()
    assert now["year"] == date.today().year and any(d["future"] for d in now["days"]) == (date.today() < date(date.today().year, 12, 31))
    assert client.get(f"/api/habits/{h['id']}/history?year=1900", headers=headers).status_code == 422
    _ = datetime
