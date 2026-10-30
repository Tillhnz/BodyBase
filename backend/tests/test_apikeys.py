def test_api_keys_read_write_and_limits(client, auth):
    r = client.post("/api/me/api-keys", json={"name": "Home Assistant"}, headers=auth)
    assert r.status_code == 201, r.text
    ro = r.json()
    assert ro["key"].startswith("bbk_") and ro["scope"] == "read"
    rw = client.post("/api/me/api-keys", json={"name": "Skript", "scope": "write"}, headers=auth).json()

    hdr_ro = {"Authorization": f"Bearer {ro['key']}"}
    assert client.get("/api/me", headers=hdr_ro).status_code == 200
    assert client.get("/api/activities", headers={"X-API-Key": ro["key"]}).status_code == 200
    # nur lesen
    assert client.post("/api/entries", json={"metric": "weight", "value": 80}, headers=hdr_ro).status_code == 403
    # schreiben
    hdr_rw = {"Authorization": f"Bearer {rw['key']}"}
    assert client.post("/api/entries", json={"metric": "weight", "value": 80}, headers=hdr_rw).status_code == 201
    assert client.post("/api/ingest/json", json={"samples": [{"metric": "weight", "value": 79}]}, headers=hdr_rw).status_code == 200
    assert client.post("/api/ingest/json", json={}, headers=hdr_ro).status_code == 401
    # gesperrte Bereiche
    assert client.get("/api/me/api-keys", headers=hdr_rw).status_code == 403
    assert client.post("/api/me/api-keys", json={"name": "x"}, headers=hdr_rw).status_code == 403
    assert client.get("/api/me/ingest", headers=hdr_rw).status_code == 403
    assert client.get("/api/admin/status", headers=hdr_rw).status_code == 403
    # Liste zeigt den Schlüssel nicht, Widerruf wirkt sofort
    listed = client.get("/api/me/api-keys", headers=auth).json()
    assert all("key" not in k for k in listed) and listed[0]["last_used_at"]
    assert client.delete(f"/api/me/api-keys/{ro['id']}", headers=auth).status_code == 204
    assert client.get("/api/me", headers=hdr_ro).status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer bbk_falsch"}).status_code == 401


def test_openapi_is_public_and_documented(client):
    spec = client.get("/api/openapi.json").json()
    assert "/api/habits" in spec["paths"] and "bbk_" in spec["info"]["description"]
