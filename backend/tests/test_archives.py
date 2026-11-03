import io
import time
import zipfile

from conftest import register

GPX = """<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Runde</name><trkseg>
<trkpt lat="50.0" lon="8.0"><ele>100</ele><time>2026-10-05T07:31:12Z</time></trkpt>
<trkpt lat="50.001" lon="8.001"><ele>101</ele><time>2026-10-05T07:32:12Z</time></trkpt>
<trkpt lat="50.002" lon="8.002"><ele>102</ele><time>2026-10-05T07:33:12Z</time></trkpt></trkseg></trk></gpx>"""

STRAVA_CSV = ("Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Max Heart Rate,Filename,"
              "Elapsed Time,Moving Time,Distance,Elevation Gain,Average Heart Rate,Calories\n"
              '111,"Oct 5, 2026, 7:31:12 AM",Morgenlauf,Run,1800,5.2,171,activities/111.gpx,1800,1750,5200.0,40,148,420\n'
              '222,"Oct 6, 2026, 5:00:00 PM",Feierabendrunde,Ride,3600,30.1,160,,3600,3500,30100.0,250,135,800\n')

CYCLES = ("Cycle start time,Cycle end time,Cycle timezone,Recovery score %,Resting heart rate (bpm),Heart rate variability (ms),"
          "Skin temp (celsius),Blood oxygen %,Day Strain,Energy burned (cal),Max HR (bpm),Average HR (bpm),Sleep onset,Wake onset,"
          "Sleep performance %,Respiratory rate (rpm),Asleep duration (min),In bed duration (min),Light sleep duration (min),"
          "Deep (SWS) duration (min),REM duration (min),Awake duration (min),Sleep need (min),Sleep debt (min),Sleep efficiency %,"
          "Sleep consistency %\n"
          "2026-10-04 23:10:00,2026-10-05 23:00:00,UTC+02:00,71,52,64,33.6,96.5,12.4,2600,171,70,2026-10-04 23:10:00,2026-10-05 06:50:00,"
          "88,14.8,420,460,210,95,115,40,480,30,91,80\n")
SLEEPS = ("Cycle start time,Cycle end time,Cycle timezone,Sleep onset,Wake onset,Sleep performance %,Respiratory rate (rpm),"
          "Asleep duration (min),In bed duration (min),Light sleep duration (min),Deep (SWS) duration (min),REM duration (min),"
          "Awake duration (min),Sleep need (min),Sleep debt (min),Sleep efficiency %,Sleep consistency %,Nap\n"
          "2026-10-04 23:10:00,2026-10-05 23:00:00,UTC+02:00,2026-10-04 23:10:00,2026-10-05 06:50:00,88,14.8,420,460,210,95,115,40,480,30,91,80,false\n")
WORKOUTS = ("Cycle start time,Cycle end time,Cycle timezone,Workout start time,Workout end time,Duration (min),Activity name,"
            "Activity Strain,Energy burned (cal),Max HR (bpm),Average HR (bpm),HR Zone 1 %,HR Zone 2 %,HR Zone 3 %,HR Zone 4 %,HR Zone 5 %,"
            "GPS enabled,Distance (meters),Altitude gain (meters),Altitude change (meters)\n"
            "2026-10-04 23:10:00,2026-10-05 23:00:00,UTC+02:00,2026-10-05 18:00:00,2026-10-05 19:00:00,60,Weightlifting,9.1,410,152,118,"
            "20,40,30,10,0,false,,,\n")


def _upload(client, headers, kind, data, name):
    half = len(data) // 2
    parts = [data[:half], data[half:]]
    r = None
    for i, part in enumerate(parts):
        r = client.post("/api/imports/archive/chunk", content=part, headers={
            **headers, "X-Kind": kind, "X-Upload-Id": "abc123", "X-Chunk-Index": str(i), "X-Chunk-Total": "2", "X-Filename": name})
        assert r.status_code == 200, r.text
    for _ in range(80):
        job = client.get("/api/imports/jobs", headers=headers).json()[0]
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.1)
    return job


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue()


def test_strava_export(client):
    headers, _ = register(client)
    job = _upload(client, headers, "strava", _zip({"export_1/activities.csv": STRAVA_CSV, "export_1/activities/111.gpx": GPX}), "export.zip")
    assert job["status"] == "done", job
    assert job["counts"]["activities"] == 2 and job["counts"]["with_track"] == 1
    acts = {a["name"]: a for a in client.get("/api/activities", headers=headers).json()["items"]}
    assert acts["Morgenlauf"]["sport"] == "run" and acts["Morgenlauf"]["has_map"] and acts["Morgenlauf"]["avg_hr"] == 148
    assert acts["Feierabendrunde"]["distance_m"] == 30100 and acts["Feierabendrunde"]["source"] == "strava"
    # erneut hochgeladen: keine Doppelten
    _upload(client, headers, "strava", _zip({"activities.csv": STRAVA_CSV}), "export.zip")
    assert client.get("/api/activities", headers=headers).json()["total"] == 2


def test_whoop_export(client):
    headers, _ = register(client)
    data = _zip({"my_whoop_data/physiological_cycles.csv": CYCLES, "my_whoop_data/sleeps.csv": SLEEPS,
                 "my_whoop_data/workouts.csv": WORKOUTS, "my_whoop_data/journal_entries.csv": "x"})
    job = _upload(client, headers, "whoop", data, "my_whoop_data.zip")
    assert job["status"] == "done", job
    assert job["counts"]["cycles"] == 1 and job["counts"]["sleeps"] == 1 and job["counts"]["workouts"] == 1
    hrv = client.get("/api/metrics/hrv?start=2026-10-05&end=2026-10-05", headers=headers).json()["series"]
    assert hrv[0]["value"] == 64 and hrv[0]["source"] == "whoop"
    nights = client.get("/api/sleep?days=3650", headers=headers).json()["nights"]
    n = next(x for x in nights if x["day"] == "2026-10-05")
    assert round(n["deep_min"]) == 95 and n["start"].startswith("2026-10-04T21:10")
    acts = client.get("/api/activities", headers=headers).json()["items"]
    assert acts[0]["sport"] == "strength" and acts[0]["avg_hr"] == 118
    # zweiter Import derselben Daten verdoppelt nichts
    _upload(client, headers, "whoop", data, "my_whoop_data.zip")
    assert client.get("/api/activities", headers=headers).json()["total"] == 1
    assert len([x for x in client.get("/api/sleep?days=3650", headers=headers).json()["nights"] if x["day"] == "2026-10-05"]) == 1


def test_archive_rejects_bad_input(client):
    headers, _ = register(client)
    r = client.post("/api/imports/archive/chunk", content=b"x", headers={**headers, "X-Kind": "garmin", "X-Upload-Id": "a",
                                                                         "X-Chunk-Index": "0", "X-Chunk-Total": "1"})
    assert r.status_code == 422
    job = _upload(client, headers, "whoop", b"kein zip und kein csv", "foo.txt")
    assert job["status"] == "failed" and "WHOOP" in job["message"]
