import math

from conftest import register


def test_helpers():
    from app import analysis as A
    assert A._spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == 1.0
    assert abs(A._spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) + 1) < 1e-9
    b, r2 = A._slope([(i, 2 * i + 1) for i in range(10)])
    assert abs(b - 2) < 1e-9 and abs(r2 - 1) < 1e-9
    diff, d, p = A._welch([10, 11, 12, 11, 10], [5, 6, 5, 6, 5])
    assert diff > 4 and d > 2 and p < 0.01
    assert A.num(12345.6, 1) == "12.345,6"
    assert A.fmt_metric("sleep_duration", 450) == "7:30 h"
    assert A._p_corr(0.5, 50) < 0.01 and A._p_corr(0.05, 20) > 0.5
    assert math.isclose(A._median([3, 1, 2, 4]), 2.5)


def test_analysis_report_with_demo(client):
    headers, _ = register(client)
    assert client.post("/api/me/demo", headers=headers).status_code == 201
    r = client.get("/api/analysis?days=90", headers=headers)
    assert r.status_code == 200, r.text
    rep = r.json()
    keys = {d["key"] for d in rep["domains"]}
    assert {"recovery", "sleep", "heart", "activity", "body"} <= keys
    stats = {s["key"]: s for s in rep["stats"]}
    assert stats["resting_hr"]["n"] > 60 and stats["resting_hr"]["sd"] > 0 and len(stats["resting_hr"]["weekday"]) == 7
    corr = rep["correlations"]
    assert len(corr["same_day"]) == len(corr["keys"]) == len(corr["next_day"])
    assert all(len(row) == len(corr["keys"]) for row in corr["same_day"])
    assert rep["comparisons"] and all(c["rows"] for c in rep["comparisons"])
    assert rep["training"]["count"] > 10 and rep["training"]["weeks"]
    assert len(rep["layers"]["days"]) == 90 and rep["layers"]["series"]
    assert any(s["agreement"] for s in rep["sources"]), "Schritte kommen in den Beispieldaten aus zwei Quellen"
    # kurzer Zeitraum und leeres Konto gehen auch
    assert client.get("/api/analysis?days=30", headers=headers).status_code == 200
    h2, _ = register(client)
    empty = client.get("/api/analysis?days=30", headers=h2).json()
    assert empty["stats"] == [] and empty["correlations"]["keys"] == []
