"""Garmin Connect über die inoffizielle Anmeldung (Python-Paket garminconnect).

Garmin bietet seine offizielle Schnittstelle nur Firmen an. Für den Eigengebrauch meldet sich BodyBase daher wie die
Garmin-App an. Gespeichert wird nur das Anmelde-Token (verschlüsselt), nicht das Passwort.
"""
import logging
import threading
import time
from datetime import date, timedelta

from ..store import ActivityIn, SleepIn
from ..timeutil import parse_date, parse_iso, today
from .base import AuthError, Field, Provider, SyncError, num

log = logging.getLogger("bodybase.garmin")

DAYS_PER_RUN = 21  # Tageswerte brauchen mehrere Abfragen je Tag; große Zeiträume verteilen sich auf mehrere Durchläufe
_pending_mfa: dict[int, tuple[float, object, object]] = {}
_lock = threading.Lock()


class MfaRequired(SyncError):
    pass


class Garmin(Provider):
    key = "garmin"
    name = "Garmin Connect"
    kind = "login"
    color = "#1d8fd6"
    initials = "Ga"
    website = "https://connect.garmin.com"
    official = False
    delivers = ["activity", "sleep", "heart", "recovery", "body", "workouts"]
    summary = "Schritte, Schlaf, HRV, Ruhepuls, Body Battery, Stress, SpO₂, VO₂max, Index-Waage und alle Aktivitäten."
    setup = [
        "E-Mail und Passwort deines Garmin-Kontos eintragen. Das Passwort wird nur zur Anmeldung benutzt und nicht gespeichert.",
        "Ist die Zwei-Faktor-Anmeldung aktiv, fragt BodyBase danach nach dem Code aus der Mail bzw. App.",
    ]
    fields = [Field("email", "E-Mail"), Field("password", "Passwort", "password", secret=True),
              Field("mfa_code", "Bestätigungscode", required=False, help="Nur nötig, wenn Garmin danach fragt.")]
    note = ("Inoffiziell: nutzt dieselbe Anmeldung wie die Garmin-App. Garmin kann das jederzeit ändern. "
            "Zuverlässige Alternative für Aktivitäten: Garmin mit Strava oder intervals.icu verbinden.")
    interval_minutes = 120

    # ---------- Anmeldung ----------

    def connect(self, ctx, values):
        try:
            from garminconnect import Garmin as GC
        except ImportError as e:
            raise SyncError("Das Paket garminconnect fehlt im Server.") from e
        uid = ctx.user.id
        code = (values.get("mfa_code") or "").strip()
        with _lock:
            pending = _pending_mfa.pop(uid, None)
        try:
            if code and pending and time.time() - pending[0] < 600:
                _, client, state = pending
                client.resume_login(state, code)
            else:
                client = GC(email=(values.get("email") or "").strip(), password=values.get("password") or "", return_on_mfa=True)
                res = client.login()
                if isinstance(res, tuple) and res and res[0] == "needs_mfa":
                    with _lock:
                        _pending_mfa[uid] = (time.time(), client, res[1])
                    raise MfaRequired("Garmin hat einen Bestätigungscode geschickt. Bitte trage ihn ein und verbinde erneut.")
        except SyncError:
            raise
        except Exception as e:
            raise SyncError(f"Anmeldung bei Garmin fehlgeschlagen: {e}") from e
        ctx.auth = {"tokens": client.garth.dumps()}
        name = getattr(client, "full_name", None) or getattr(client, "display_name", None)
        return name or (values.get("email") or "").strip()

    def _client(self, ctx):
        try:
            from garminconnect import Garmin as GC
        except ImportError as e:
            raise SyncError("Das Paket garminconnect fehlt im Server.") from e
        tokens = ctx.auth.get("tokens")
        if not tokens:
            raise AuthError("Kein Garmin-Zugang gespeichert. Bitte verbinde dich erneut.")
        client = GC()
        try:
            client.login(tokens)
        except Exception as e:
            raise AuthError(f"Der Garmin-Zugang ist abgelaufen ({e}). Bitte verbinde dich erneut.") from e
        return client

    # ---------- Abgleich ----------

    def sync(self, ctx):
        client = self._client(ctx)
        w = ctx.writer
        try:
            start, end = ctx.since_date, today()
            for a in client.get_activities_by_date(start.isoformat(), end.isoformat()) or []:
                w.activity(map_activity(a))
            body = client.get_body_composition(start.isoformat(), end.isoformat()) or {}
            for item in body.get("dateWeightList", []) or []:
                map_weight(w, item)
            # Tageswerte: vom gespeicherten Fortschritt an, höchstens DAYS_PER_RUN Tage je Durchlauf
            nxt = parse_date(ctx.cursor.get("garmin_next")) or start
            nxt = min(nxt, max(start, end - timedelta(days=2)))  # die letzten Tage immer neu holen
            stop = min(end, nxt + timedelta(days=DAYS_PER_RUN - 1))
            d = nxt
            while d <= stop:
                self._day(client, w, d)
                d += timedelta(days=1)
            ctx.cursor["garmin_next"] = (stop + timedelta(days=1) if stop < end else end - timedelta(days=2)).isoformat()
            if stop < end:
                ctx.note(f"Tageswerte bis {stop.strftime('%d.%m.%Y')} geholt, der Rest folgt beim nächsten Abgleich.")
        finally:
            try:
                ctx.auth["tokens"] = client.garth.dumps()  # erneuerte Tokens behalten
                ctx.save_auth()
            except Exception:
                pass

    def _day(self, client, w, d: date):
        ds = d.isoformat()

        def safe(fn, *args):
            try:
                return fn(*args) or {}
            except Exception as e:  # einzelne Tageswerte dürfen fehlen
                log.debug("Garmin %s %s: %s", getattr(fn, "__name__", fn), ds, e)
                return {}
        stats = safe(client.get_stats, ds)
        w.daily("steps", d, stats.get("totalSteps"))
        w.daily("resting_hr", d, stats.get("restingHeartRate"))
        w.daily("active_energy", d, stats.get("activeKilocalories"))
        w.daily("total_energy", d, stats.get("totalKilocalories"))
        w.daily("floors", d, stats.get("floorsAscended"))
        w.daily("stress", d, stats.get("averageStressLevel") if (num(stats.get("averageStressLevel")) or -1) >= 0 else None)
        w.daily("body_battery", d, stats.get("bodyBatteryHighestValue"))
        if stats.get("totalDistanceMeters") is not None:
            w.daily("distance", d, num(stats.get("totalDistanceMeters")) / 1000)
        mins = (num(stats.get("moderateIntensityMinutes")) or 0) + (num(stats.get("vigorousIntensityMinutes")) or 0)
        if stats.get("moderateIntensityMinutes") is not None:
            w.daily("active_minutes", d, mins)
        sleep = safe(client.get_sleep_data, ds)
        s = map_sleep(sleep)
        if s:
            w.sleep(s)
        hrv = safe(client.get_hrv_data, ds)
        w.daily("hrv", d, (hrv.get("hrvSummary") or {}).get("lastNightAvg"))
        spo2 = safe(client.get_spo2_data, ds)
        w.daily("spo2", d, spo2.get("averageSpO2"))
        resp = safe(client.get_respiration_data, ds)
        w.daily("respiratory_rate", d, resp.get("avgSleepRespirationValue") or resp.get("avgWakingRespirationValue"))
        maxm = safe(client.get_max_metrics, ds)
        if isinstance(maxm, list) and maxm:
            gen = (maxm[0] or {}).get("generic") or {}
            w.daily("vo2max", d, gen.get("vo2MaxPreciseValue") or gen.get("vo2MaxValue"))


def map_activity(a: dict) -> ActivityIn:
    start = parse_iso(str(a.get("startTimeGMT") or "") + "+00:00") if a.get("startTimeGMT") else parse_iso(a.get("startTimeLocal"))
    return ActivityIn(
        source_id=str(a.get("activityId")), start=start, sport_raw=(a.get("activityType") or {}).get("typeKey"),
        name=a.get("activityName"), duration_s=num(a.get("elapsedDuration")) or num(a.get("duration")),
        moving_s=num(a.get("movingDuration")), distance_m=num(a.get("distance")), elevation_m=num(a.get("elevationGain")),
        calories=num(a.get("calories")), avg_hr=num(a.get("averageHR")), max_hr=num(a.get("maxHR")),
        avg_power=num(a.get("avgPower")), load=num(a.get("activityTrainingLoad")),
    )


def map_weight(w, item: dict) -> None:
    ts = parse_iso(item.get("date") or item.get("timestampGMT"))
    if ts is None:
        return
    grams = num(item.get("weight"))
    if grams:
        w.sample("weight", ts, grams / 1000)
    w.sample("body_fat", ts, item.get("bodyFat"))
    w.sample("body_water", ts, item.get("bodyWater"))
    w.sample("bmi", ts, item.get("bmi"))
    if num(item.get("muscleMass")):
        w.sample("muscle_mass", ts, num(item.get("muscleMass")) / 1000)
    if num(item.get("boneMass")):
        w.sample("bone_mass", ts, num(item.get("boneMass")) / 1000)


def map_sleep(data: dict) -> SleepIn | None:
    dto = (data or {}).get("dailySleepDTO") or {}
    if not dto.get("sleepStartTimestampGMT") or not dto.get("sleepEndTimestampGMT"):
        return None

    def mins(k):
        return num(dto.get(k)) / 60 if dto.get(k) is not None else None
    score = ((dto.get("sleepScores") or {}).get("overall") or {}).get("value")
    return SleepIn(
        source_id=str(dto.get("id") or dto.get("calendarDate")), start=parse_iso(dto.get("sleepStartTimestampGMT")),
        end=parse_iso(dto.get("sleepEndTimestampGMT")), asleep_min=mins("sleepTimeSeconds"), deep_min=mins("deepSleepSeconds"),
        rem_min=mins("remSleepSeconds"), light_min=mins("lightSleepSeconds"), awake_min=mins("awakeSleepSeconds"),
        score=num(score), avg_hr=num(dto.get("avgHeartRate")), hrv=num((data or {}).get("avgOvernightHrv")),
    )
