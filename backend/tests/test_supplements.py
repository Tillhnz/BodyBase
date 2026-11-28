from datetime import date, timedelta

from conftest import register


def _fake_weather(uv, sun):
    def f(lat, lon):
        return {"uv_max": uv, "sun_h": sun, "temp_max": 20, "rain": 0, "uv_window": ["11:00", "15:00"], "tomorrow_uv": uv}
    return f


def test_supplement_tracker_and_vitd_advice(client, monkeypatch):
    from app import supplements as SP
    headers, _ = register(client)
    monkeypatch.setattr(SP, "weather", _fake_weather(2, 1))
    client.put("/api/supplements/location", headers=headers, json={"lat": 53.5, "lon": 10.0, "name": "Hamburg"})
    first = client.get("/api/supplements/today", headers=headers).json()
    assert first["weather"]["uv_max"] == 2  # Wetter auch ohne angelegte Supplements
    cat = first["catalog"]
    assert any(c["key"] == "vitd" for c in cat)
    h = client.post("/api/habits", headers=headers, json={"name": "Vitamin D3", "supplement": {"key": "vitd", "dose": 2000, "unit": "IE"}}).json()
    assert h["kind"] == "check" and h["supplement"]["dose"] == 2000
    client.put("/api/supplements/location", headers=headers, json={"lat": 50.1, "lon": 8.7, "name": "Frankfurt"})

    monkeypatch.setattr(SP, "weather", _fake_weather(1.2, 1))
    r = client.get("/api/supplements/today", headers=headers).json()
    it = r["items"][0]
    assert r["location"]["name"] == "Frankfurt" and it["advice"]["level"] == "take" and "UV" in it["advice"]["text"]

    monkeypatch.setattr(SP, "weather", _fake_weather(6.5, 9))
    it = client.get("/api/supplements/today", headers=headers).json()["items"][0]
    assert it["advice"]["level"] == "optional" and "min" in it["advice"]["text"]

    # abhaken -> Messwert supp_vitd für die Auswertungen
    d = date.today().isoformat()
    client.post(f"/api/habits/{h['id']}/log", headers=headers, json={"day": d, "value": 1})
    m = client.get("/api/metrics/supp_vitd?days=7", headers=headers).json()
    pts = m.get("series", m.get("points", []))
    assert any(p["value"] == 2000 for p in pts)
    assert client.get("/api/supplements/today", headers=headers).json()["items"][0]["taken"] is True
    client.post(f"/api/habits/{h['id']}/log", headers=headers, json={"day": d, "value": 0})
    m = client.get("/api/metrics/supp_vitd?days=7", headers=headers).json()
    assert not [p for p in m.get("series", m.get("points", [])) if p["value"]]


def test_iron_every_other_day_and_effects(client, monkeypatch):
    from app import supplements as SP
    monkeypatch.setattr(SP, "weather", _fake_weather(1, 0))
    headers, _ = register(client)
    h = client.post("/api/habits", headers=headers, json={"name": "Eisen", "supplement": {"key": "iron"}}).json()
    y = (date.today() - timedelta(days=1)).isoformat()
    client.post(f"/api/habits/{h['id']}/log", headers=headers, json={"day": y, "value": 1})
    it = client.get("/api/supplements/today", headers=headers).json()["items"][0]
    assert it["advice"]["level"] == "optional" and "zweiten Tag" in it["advice"]["text"]
    eff = client.get("/api/supplements/effects", headers=headers).json()
    assert eff and eff[0]["key"] == "iron" and eff[0]["days_taken"] == 1
    assert client.post("/api/habits", headers=headers, json={"name": "X", "supplement": {"key": "unbekannt"}}).status_code == 422
