"""Anbieter mit nachgebildeten API-Antworten: prüft Abfragen, Umrechnungen und das Speichern."""
import json
from datetime import timedelta

import httpx
from sqlalchemy import select

from conftest import make_ctx

from app import providers
from app.models import Activity, Sample, SleepSession


def _app_today():
    """Kalendertag in der Zeitzone der App (nicht des Testrechners)."""
    from app.timeutil import today
    return today()


TODAY = _app_today()
D1 = (TODAY - timedelta(days=1)).isoformat()


def json_response(data, status=200):
    return httpx.Response(status, json=data)


def samples(db, user, metric):
    return db.scalars(select(Sample).where(Sample.user_id == user.id, Sample.metric == metric).order_by(Sample.ts)).all()


def test_strava_refreshes_token_and_maps(db, user):
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.path == "/oauth/token":
            return json_response({"access_token": "new", "refresh_token": "ref2", "expires_at": 9999999999})
        if req.headers["Authorization"] == "Bearer tok":
            return json_response({"message": "expired"}, 401)
        if req.url.params.get("page") == "1":
            return json_response([{"id": 1, "name": "Abendrunde", "sport_type": "Ride", "start_date": f"{D1}T17:00:00Z",
                                   "elapsed_time": 3700, "moving_time": 3600, "distance": 30500.0, "total_elevation_gain": 210,
                                   "average_heartrate": 135.2, "kilojoules": 750, "map": {"summary_polyline": "abc"}}])
        return json_response([])
    p = providers.get("strava")
    ctx = make_ctx(db, user, p, handler)
    p.sync(ctx)
    ctx.writer.flush()
    assert "/oauth/token" in calls
    assert ctx.auth["access_token"] == "new" and ctx.auth["refresh_token"] == "ref2"
    a = db.scalar(select(Activity).where(Activity.user_id == user.id))
    assert a.sport == "ride" and a.distance_m == 30500 and a.calories == 750 and a.polyline == "abc"


def test_withings_measures_and_sleep(db, user):
    def handler(req: httpx.Request):
        body = dict(httpx.QueryParams(req.content.decode()))
        action = body.get("action")
        if action == "getmeas":
            return json_response({"status": 0, "body": {"measuregrps": [{"date": 1761894000, "measures": [
                {"value": 80450, "type": 1, "unit": -3}, {"value": 195, "type": 6, "unit": -1}, {"value": 121, "type": 10, "unit": 0}]}]}})
        if action == "getactivity":
            return json_response({"status": 0, "body": {"activities": [{"date": D1, "steps": 9123, "distance": 6400, "calories": 410,
                                                                         "totalcalories": 2500, "moderate": 1200, "intense": 600}]}})
        if action == "getsummary":
            return json_response({"status": 0, "body": {"series": [{"id": 5, "startdate": 1761868800, "enddate": 1761895800, "data": {
                "deepsleepduration": 5400, "remsleepduration": 6000, "lightsleepduration": 13800, "wakeupduration": 1800,
                "sleep_score": 81, "sleep_efficiency": 0.92, "rr_average": 14}}]}})
        return json_response({"status": 0, "body": {"series": []}})
    p = providers.get("withings")
    ctx = make_ctx(db, user, p, handler)
    p.sync(ctx)
    ctx.writer.flush()
    assert samples(db, user, "weight")[0].value == 80.45
    assert samples(db, user, "body_fat")[0].value == 19.5
    assert samples(db, user, "bp_systolic")[0].value == 121
    assert samples(db, user, "steps")[0].value == 9123
    assert samples(db, user, "active_minutes")[0].value == 30
    s = db.scalar(select(SleepSession).where(SleepSession.user_id == user.id))
    assert s.deep_min == 90 and s.efficiency == 92 and s.asleep_min == 420
    assert samples(db, user, "sleep_duration")[0].value == 420


def test_oura_pagination_and_sleep(db, user):
    pages = {"n": 0}

    def handler(req: httpx.Request):
        ep = req.url.path.rsplit("/", 1)[-1]
        if ep == "daily_readiness":
            if not req.url.params.get("next_token"):
                return json_response({"data": [{"day": D1, "score": 77, "temperature_deviation": 0.1}], "next_token": "p2"})
            pages["n"] += 1
            return json_response({"data": [{"day": TODAY.isoformat(), "score": 80}], "next_token": None})
        if ep == "sleep":
            return json_response({"data": [{"id": "s1", "day": D1, "type": "long_sleep", "bedtime_start": f"{D1}T00:10:00+02:00",
                                            "bedtime_end": f"{D1}T07:40:00+02:00", "total_sleep_duration": 25200,
                                            "deep_sleep_duration": 4800, "rem_sleep_duration": 6000, "light_sleep_duration": 14400,
                                            "awake_time": 1800, "average_hrv": 61, "lowest_heart_rate": 51, "average_breath": 14.5}]})
        if ep == "daily_sleep":
            return json_response({"data": [{"day": D1, "score": 85}]})
        return json_response({"data": []})
    p = providers.get("oura")
    ctx = make_ctx(db, user, p, handler)
    p.sync(ctx)
    ctx.writer.flush()
    assert [s.value for s in samples(db, user, "readiness")] == [77, 80]
    assert samples(db, user, "hrv")[0].value == 61
    assert samples(db, user, "resting_hr")[0].value == 51
    s = db.scalar(select(SleepSession).where(SleepSession.user_id == user.id))
    assert s.score == 85 and s.asleep_min == 420


def test_whoop(db, user):
    def handler(req: httpx.Request):
        path = req.url.path
        if path.endswith("/recovery"):
            return json_response({"records": [{"score_state": "SCORED", "created_at": f"{D1}T06:00:00Z", "score": {
                "recovery_score": 66, "resting_heart_rate": 53, "hrv_rmssd_milli": 71.2, "spo2_percentage": 96.5}}], "next_token": None})
        if path.endswith("/activity/sleep"):
            return json_response({"records": [{"id": "abc", "score_state": "SCORED", "nap": False, "start": f"{D1}T00:00:00Z",
                                               "end": f"{D1}T07:30:00Z", "score": {"stage_summary": {
                                                   "total_slow_wave_sleep_time_milli": 5400000, "total_rem_sleep_time_milli": 6000000,
                                                   "total_light_sleep_time_milli": 13800000, "total_awake_time_milli": 1800000},
                                                   "sleep_performance_percentage": 88, "respiratory_rate": 15.1}}]})
        if path.endswith("/activity/workout"):
            return json_response({"records": [{"id": "w1", "score_state": "SCORED", "sport_name": "running", "start": f"{D1}T17:00:00Z",
                                               "end": f"{D1}T17:45:00Z", "score": {"strain": 12.3, "kilojoule": 2092,
                                                                                    "average_heart_rate": 150, "distance_meter": 8000}}]})
        return json_response({"records": []})
    p = providers.get("whoop")
    ctx = make_ctx(db, user, p, handler)
    p.sync(ctx)
    ctx.writer.flush()
    assert samples(db, user, "recovery")[0].value == 66
    assert round(samples(db, user, "hrv")[0].value) == 71
    a = db.scalar(select(Activity).where(Activity.user_id == user.id))
    assert a.sport == "run" and round(a.calories) == 500 and a.load == 12.3


def test_intervals_wellness(db, user):
    def handler(req: httpx.Request):
        assert req.headers["Authorization"].startswith("Basic ")
        if req.url.path.endswith("/activities"):
            return json_response([{"id": "i1", "start_date": f"{D1}T05:00:00Z", "type": "VirtualRide", "name": "Zwift",
                                   "elapsed_time": 3600, "distance": 35000, "icu_training_load": 70}])
        if req.url.path.endswith("/wellness"):
            return json_response([{"id": D1, "weight": 78.2, "restingHR": 49, "hrv": 72, "sleepSecs": 27000, "readiness": 70}])
        return json_response({})
    p = providers.get("intervals")
    ctx = make_ctx(db, user, p, handler, auth={"api_key": "k"})
    p.sync(ctx)
    ctx.writer.flush()
    assert samples(db, user, "weight")[0].value == 78.2
    assert samples(db, user, "sleep_duration")[0].value == 450
    a = db.scalar(select(Activity).where(Activity.user_id == user.id))
    assert a.sport == "ride" and a.load == 70


def test_polar(db, user):
    def handler(req: httpx.Request):
        p = req.url.path
        if p.endswith("/exercises"):
            return json_response([{"id": "e1", "start_time": f"{D1}T18:00:00", "start_time_utc_offset": 120, "duration": "PT1H0M30S",
                                   "distance": 10000, "calories": 650, "heart_rate": {"average": 145, "maximum": 170}, "sport": "RUNNING"}])
        if p.endswith("/users/sleep"):
            return json_response({"nights": [{"date": D1, "sleep_start_time": f"{D1}T00:00:00+02:00", "sleep_end_time": f"{D1}T07:00:00+02:00",
                                              "deep_sleep": 5400, "rem_sleep": 5400, "light_sleep": 13200, "total_interruption_duration": 1200,
                                              "sleep_score": 80}]})
        if p.endswith("/nightly-recharge"):
            return json_response({"recharges": [{"date": D1, "heart_rate_avg": 55, "heart_rate_variability_avg": 48,
                                                 "breathing_rate_avg": 14.2, "nightly_recharge_status": 4}]})
        return httpx.Response(204)
    prov = providers.get("polar")
    ctx = make_ctx(db, user, prov, handler, auth={"access_token": "t", "x_user_id": 42})
    prov.sync(ctx)
    ctx.writer.flush()
    a = db.scalar(select(Activity).where(Activity.user_id == user.id))
    assert a.duration_s == 3630 and a.start.hour == 16  # 18:00 Ortszeit (+2h) = 16:00 UTC
    assert samples(db, user, "readiness")[0].value == 60
    s = db.scalar(select(SleepSession).where(SleepSession.user_id == user.id))
    assert s.asleep_min == 400


def test_fitbit_series(db, user):
    def handler(req: httpx.Request):
        p = req.url.path
        if "/activities/steps/" in p:
            return json_response({"activities-steps": [{"dateTime": D1, "value": "10500"}]})
        if "/activities/heart/" in p:
            return json_response({"activities-heart": [{"dateTime": D1, "value": {"restingHeartRate": 57}}]})
        if "/cardioscore/" in p:
            return json_response({"cardioScore": [{"dateTime": D1, "value": {"vo2Max": "44-48"}}]})
        if "/body/log/weight/" in p:
            return json_response({"weight": [{"date": D1, "time": "07:10:00", "weight": 81.3, "bmi": 24.1, "fat": 18.2, "logId": 1}]})
        if "/sleep/date/" in p:
            return json_response({"sleep": [{"logId": 9, "startTime": f"{D1}T23:00:00.000", "endTime": f"{TODAY.isoformat()}T06:30:00.000",
                                             "minutesAsleep": 420, "minutesAwake": 30, "efficiency": 93, "isMainSleep": True, "type": "stages",
                                             "levels": {"summary": {"deep": {"minutes": 80}, "rem": {"minutes": 95}, "light": {"minutes": 245},
                                                                    "wake": {"minutes": 30}}}}]})
        if p.endswith("/activities/list.json"):
            return json_response({"activities": [{"logId": 77, "activityName": "Walk", "startTime": f"{D1}T12:00:00.000+02:00",
                                                  "duration": 1800000, "distance": 2.5, "distanceUnit": "Kilometer", "calories": 150}]})
        return json_response({})
    p = providers.get("fitbit")
    ctx = make_ctx(db, user, p, handler)
    p.sync(ctx)
    ctx.writer.flush()
    assert samples(db, user, "steps")[0].value == 10500
    assert samples(db, user, "vo2max")[0].value == 46
    assert samples(db, user, "weight")[0].value == 81.3
    s = db.scalar(select(SleepSession).where(SleepSession.user_id == user.id))
    assert s.deep_min == 80 and s.asleep_min == 420
    a = db.scalar(select(Activity).where(Activity.user_id == user.id))
    assert a.sport == "walk" and a.distance_m == 2500 and a.duration_s == 1800


def test_hevy_volume(db, user):
    def handler(req: httpx.Request):
        assert req.headers["api-key"] == "k"
        return json_response({"page": 1, "page_count": 1, "workouts": [{"id": "h1", "title": "Push", "start_time": f"{D1}T18:00:00Z",
                                                                          "end_time": f"{D1}T19:05:00Z", "exercises": [
            {"title": "Bankdrücken", "sets": [{"type": "warmup", "weight_kg": 40, "reps": 10}, {"type": "normal", "weight_kg": 80, "reps": 8},
                                              {"type": "normal", "weight_kg": 80, "reps": 6}]}]}]})
    p = providers.get("hevy")
    ctx = make_ctx(db, user, p, handler, auth={"api_key": "k"})
    p.sync(ctx)
    ctx.writer.flush()
    a = db.scalar(select(Activity).where(Activity.user_id == user.id))
    assert a.sport == "strength" and a.volume_kg == 1120 and a.duration_s == 3900


def test_nightscout_and_homeassistant(db, user):
    now_ms = int(__import__("time").time() * 1000)

    def ns(req: httpx.Request):
        assert req.url.params.get("token") == "readable-abc123"
        return json_response([{"sgv": 112, "date": now_ms - 600000}, {"sgv": 118, "date": now_ms - 300000}])
    p = providers.get("nightscout")
    ctx = make_ctx(db, user, p, ns, auth={"token": "readable-abc123"}, config={"url": "https://ns.example"})
    p.sync(ctx)
    ctx.writer.flush()
    assert [s.value for s in samples(db, user, "glucose")] == [112, 118]

    def ha(req: httpx.Request):
        assert req.headers["Authorization"] == "Bearer hatoken"
        return json_response([
            [{"entity_id": "sensor.waage", "state": "79.6", "last_changed": f"{D1}T05:00:00+00:00"}, {"state": "unavailable",
                                                                                                  "last_changed": f"{D1}T06:00:00+00:00"}],
            [{"entity_id": "sensor.schritte", "state": "1200", "last_changed": f"{D1}T08:00:00+00:00"},
             {"state": "8400", "last_changed": f"{D1}T19:00:00+00:00"}],
        ])
    p = providers.get("homeassistant")
    ctx = make_ctx(db, user, p, ha, auth={"token": "hatoken"}, config={
        "url": "http://ha.local:8123", "mapping": {"sensor.waage": "weight", "sensor.schritte": "steps"}})
    p.sync(ctx)
    ctx.writer.flush()
    assert samples(db, user, "weight")[0].value == 79.6
    assert [s.value for s in samples(db, user, "steps")] == [8400]  # Tageszähler: höchster Stand


def test_concept2_and_wahoo(db, user):
    def c2(req: httpx.Request):
        return json_response({"data": [{"id": 5, "type": "rower", "date": f"{D1} 07:30:00", "timezone": "Europe/Berlin",
                                        "distance": 5000, "time": 12345, "calories_total": 300, "heart_rate": {"average": 150}}],
                              "meta": {"pagination": {"total_pages": 1}}})
    p = providers.get("concept2")
    ctx = make_ctx(db, user, p, c2)
    p.sync(ctx)
    ctx.writer.flush()
    a = db.scalar(select(Activity).where(Activity.user_id == user.id, Activity.source == "concept2"))
    assert a.sport == "row" and abs(a.duration_s - 1234) <= 1

    def wa(req: httpx.Request):
        return json_response({"workouts": [{"id": 9, "starts": f"{D1}T16:00:00.000Z", "name": "KICKR", "workout_type_id": 12,
                                            "workout_summary": {"duration_total_accum": "3600.0", "distance_accum": "30000.0",
                                                                "power_avg": "210", "calories_accum": "800"}}], "total": 1})
    p = providers.get("wahoo")
    ctx = make_ctx(db, user, p, wa)
    p.sync(ctx)
    ctx.writer.flush()
    a = db.scalar(select(Activity).where(Activity.user_id == user.id, Activity.source == "wahoo"))
    assert a.sport == "ride" and a.avg_power == 210


def test_auth_error_on_401_without_refresh(db, user):
    from app.providers.base import AuthError

    def handler(req):
        return json_response({"error": "nope"}, 401)
    p = providers.get("oura")
    ctx = make_ctx(db, user, p, handler, auth={"access_token": "x"})
    try:
        p.sync(ctx)
        raise AssertionError("AuthError erwartet")
    except AuthError:
        pass


def test_every_provider_describes_itself():
    for p in providers.all_providers():
        d = p.describe(True)
        assert d["name"] and d["summary"] and d["setup"], p.key
        json.dumps(d)
        if p.kind == "oauth":
            assert p.oauth is not None and p.app_fields and p.app_setup, p.key
