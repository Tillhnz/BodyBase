from datetime import date

from conftest import register

REPORT = """Labor Dr. Muster   Befund
Entnahmedatum: 03.11.2026  08:12
Untersuchung      Ergebnis   Einheit    Referenzbereich
Leukozyten        5,8        /nl        4,0 - 10,0
Hämoglobin        15,1       g/dl       13,5 - 17,5
MCV               88         fl         80 - 100
MCH               30,2       pg         27 - 34
MCHC              34,1       g/dl       32 - 36
RDW               12,6       %          11,5 - 14,5
Lymphozyten       31         %          20 - 45
Ferritin          28         ng/ml      30 - 400
25-OH-Vitamin D   42         nmol/l     75 - 250
HbA1c             36         mmol/mol   < 39
Glucose nüchtern  5,1        mmol/l     3,9 - 5,5
Cholesterin       205        mg/dl      < 200
LDL-Cholesterin   3,4        mmol/l     < 3,0
HDL-Cholesterin   62         mg/dl      > 40
Triglyceride      0,9        mmol/l     < 1,7
CRP               0,6        mg/l       < 5,0
TSH               1,8        mU/l       0,4 - 4,0
Kreatinin         88         µmol/l     62 - 106
GPT (ALAT)        24         U/l        < 50
Alkalische Phosphatase 64    U/l        40 - 130
Albumin           46         g/l        35 - 52
CK                420        U/l        < 190
"""


def test_parse_lab_report(client):
    headers, _ = register(client)
    r = client.post("/api/labs/parse", headers=headers, data={"text": REPORT}).json()
    got = {m["key"]: m["value"] for m in r["markers"]}
    assert r["day"] == "2026-11-03" and r["day_detected"]
    assert got["hemoglobin"] == 15.1 and got["mcv"] == 88 and got["mch"] == 30.2 and got["mchc"] == 34.1
    assert abs(got["vitd"] - 16.8) < 0.01  # nmol/l -> ng/ml
    assert abs(got["hba1c"] - 5.44) < 0.05  # mmol/mol -> %
    assert abs(got["lab_glucose"] - 91.9) < 0.2
    assert got["chol"] == 205 and abs(got["ldl"] - 131.5) < 0.5 and got["hdl"] == 62
    assert abs(got["creatinine"] - 0.995) < 0.01 and abs(got["albumin"] - 4.6) < 0.01
    assert got["crp"] == 0.6 and got["ck"] == 420 and got["lymph_pct"] == 31 and got["alt"] == 24 and got["alp"] == 64


def test_save_and_overview(client):
    headers, _ = register(client)
    client.put("/api/me/profile", headers=headers, json={"birth_year": date.today().year - 35, "sex": "m"})
    parsed = client.post("/api/labs/parse", headers=headers, data={"text": REPORT}).json()
    values = {m["key"]: m["value"] for m in parsed["markers"]}
    r = client.post("/api/labs", headers=headers, json={"day": parsed["day"], "values": values})
    assert r.status_code == 200 and r.json()["saved"] == len(values)
    ov = client.get("/api/labs", headers=headers).json()
    by = {m["key"]: m for m in ov["markers"]}
    assert by["ferritin"]["status"] == "low" and by["vitd"]["status"] == "low" and by["hemoglobin"]["status"] == "optimal"
    titles = " ".join(x["title"] for x in ov["links"])
    assert "Eisen" in titles and "Vitamin D" in titles and "CK" in titles
    assert ov["phenoage"] and 20 < ov["phenoage"]["value"] < 50
    assert client.get("/api/metrics/lab_ferritin?days=365", headers=headers).status_code == 200
    bio = client.get("/api/bio-age", headers=headers).json()
    assert bio.get("ready") is False or any(f["key"] == "phenoage" for f in bio["factors"])
    assert client.delete(f"/api/labs/{parsed['day']}", headers=headers).status_code == 204
    assert client.get("/api/labs", headers=headers).json()["markers"] == []


def test_parse_rejects_empty(client):
    headers, _ = register(client)
    r = client.post("/api/labs/parse", headers=headers, data={"text": "nichts hier"}).json()
    assert r["markers"] == [] and r["hint"]
