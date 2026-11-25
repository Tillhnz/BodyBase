from datetime import date, datetime, timedelta

from conftest import register


def _ride(db, uid, day, pts, sport="ride", sid="r"):
    from app.importers.polyline import encode
    from app.models import Activity
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=9)
    db.add(Activity(user_id=uid, source="files", source_id=sid, sport=sport, day=day, start=start, duration_s=3600,
                    distance_m=20000, polyline=encode(pts), name="Runde"))


def test_explorer_tiles_square_and_filters(client):
    headers, _ = register(client)
    me = client.get("/api/me", headers=headers).json()
    from app.database import SessionLocal
    from app.explorer import tile_of
    x0, y0 = tile_of(50.0, 8.0)
    from app.explorer import tile_bounds
    # drei waagerechte Fahrten über je 3 Kacheln -> 3x3-Quadrat; eine Laufrunde ein Jahr früher weiter weg
    with SessionLocal() as db:
        for i in range(3):
            b0 = tile_bounds(x0, y0 + i)
            lat = (b0[0][0] + b0[1][0]) / 2
            w = tile_bounds(x0, y0)[0][1] + 0.001
            e = tile_bounds(x0 + 2, y0)[1][1] - 0.001
            _ride(db, me["id"], date(2025, 6, 1 + i), [(lat, w), (lat, e)], sid=f"r{i}")
        _ride(db, me["id"], date(2024, 5, 1), [(51.0, 9.0), (51.0, 9.05)], sport="run", sid="run1")
        db.commit()
    r = client.get("/api/explorer", headers=headers).json()
    assert r["square"]["size"] == 3 and r["stats"]["tiles"] >= 9 + 3
    assert set(r["sports"]) == {"ride", "run"} and r["years"] == [2024, 2025]
    assert r["target"]["size"] == 4 and r["target"]["count"] == 7
    assert r["timeline"][-1]["total"] == r["stats"]["tiles"]
    only_run = client.get("/api/explorer?sports=run", headers=headers).json()
    assert only_run["square"]["size"] == 1 and len(only_run["routes"]) == 1
    up_to_2024 = client.get("/api/explorer?to=2024", headers=headers).json()
    assert len(up_to_2024["routes"]) == 1
    yr = client.get("/api/explorer?from=2025&to=2025", headers=headers).json()
    assert yr["stats"]["new_in_range"] == 9 and len(yr["routes"]) == 3
