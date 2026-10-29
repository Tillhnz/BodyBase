"""Beispieldaten zum Ausprobieren (und für die Screenshots in der CI): 180 Tage aus mehreren Quellen."""
from __future__ import annotations

import math
import random
from datetime import timedelta

from sqlalchemy import select

from .models import Connection, User
from .store import ActivityIn, SleepIn, Writer
from .timeutil import day_start_utc, today, utcnow

DEMO_SOURCES = ["withings", "oura", "garmin", "strava", "apple_health"]


def generate(db, user: User, days: int = 180, seed: int = 7) -> dict:
    rnd = random.Random(seed)
    end = today()
    start = end - timedelta(days=days - 1)
    ws = {s: Writer(db, user.id, s) for s in DEMO_SOURCES}
    fitness = 0.0
    for i in range(days):
        d = start + timedelta(days=i)
        t = i / days
        weekend = d.weekday() >= 5
        base = day_start_utc(d)
        # Körper (Waage, morgens)
        weight = 83.5 - 4.2 * t + 0.6 * math.sin(i / 9) + rnd.gauss(0, 0.25)
        if rnd.random() < 0.8:
            ts = base + timedelta(hours=6, minutes=rnd.randint(30, 80))
            ws["withings"].sample("weight", ts, round(weight, 2))
            ws["withings"].sample("body_fat", ts, round(21.5 - 3.0 * t + rnd.gauss(0, 0.3), 1))
            ws["withings"].sample("muscle_mass", ts, round(37.0 + 0.8 * t + rnd.gauss(0, 0.15), 1))
            ws["withings"].sample("body_water", ts, round(56 + 1.5 * t + rnd.gauss(0, 0.4), 1))
        if d.weekday() in (0, 3):
            ts = base + timedelta(hours=7, minutes=10)
            ws["withings"].sample("bp_systolic", ts, round(126 - 6 * t + rnd.gauss(0, 4)))
            ws["withings"].sample("bp_diastolic", ts, round(82 - 4 * t + rnd.gauss(0, 3)))
        # Training (Uhr) und teils doppelt über Strava
        sport = None
        if d.weekday() in (1, 3) or (d.weekday() == 5 and rnd.random() < 0.7):
            sport = "running"
        elif d.weekday() == 6 and rnd.random() < 0.8:
            sport = "cycling"
        elif d.weekday() in (0, 4) and rnd.random() < 0.6:
            sport = "strength_training"
        load = 0
        if sport:
            hour = 18 if not weekend else 9
            st = base + timedelta(hours=hour, minutes=rnd.randint(0, 40))
            if sport == "running":
                km = rnd.uniform(6, 13) if d.weekday() != 5 else rnd.uniform(14, 21)
                pace = rnd.uniform(5.0, 5.8) - 0.4 * t
                dur = km * pace * 60
                act = ActivityIn(source_id=f"g{i}", start=st, sport_raw="running", name="Lauf am Abend" if not weekend else "Langer Lauf",
                                 duration_s=dur, moving_s=dur * 0.97, distance_m=km * 1000, elevation_m=km * rnd.uniform(3, 12),
                                 calories=km * 68, avg_hr=rnd.uniform(142, 156) - 6 * t, max_hr=rnd.uniform(168, 182), load=dur / 60 * 1.1)
            elif sport == "cycling":
                km = rnd.uniform(45, 95)
                dur = km / rnd.uniform(25, 30) * 3600
                act = ActivityIn(source_id=f"g{i}", start=st, sport_raw="road_biking", name="Sonntagsrunde", duration_s=dur,
                                 moving_s=dur * 0.93, distance_m=km * 1000, elevation_m=km * rnd.uniform(6, 14), calories=km * 26,
                                 avg_hr=rnd.uniform(128, 140), max_hr=rnd.uniform(160, 175), avg_power=rnd.uniform(170, 205), load=dur / 60 * 0.9)
            else:
                dur = rnd.uniform(45, 70) * 60
                act = ActivityIn(source_id=f"g{i}", start=st, sport_raw="strength_training", name="Krafttraining", duration_s=dur,
                                 calories=dur / 60 * 6, avg_hr=rnd.uniform(105, 120), volume_kg=rnd.uniform(6000, 9000), load=dur / 60 * 0.7)
            ws["garmin"].activity(act)
            load = act.load or 0
            if sport != "strength_training" and rnd.random() < 0.7:
                dup = ActivityIn(**{**act.__dict__, "source_id": f"s{i}", "start": st + timedelta(seconds=rnd.randint(-20, 40)),
                                    "avg_hr": None, "name": act.name})
                ws["strava"].activity(dup)
        fitness += (load - fitness) / 42
        # Alltag
        steps = rnd.gauss(9500 if not weekend else 11500, 2600) + (8000 if sport == "running" else 0)
        ws["garmin"].daily("steps", d, max(1500, round(steps)))
        ws["apple_health"].daily("steps", d, max(1200, round(steps * rnd.uniform(0.85, 0.95))))
        ws["garmin"].daily("active_minutes", d, max(5, round(rnd.gauss(35, 12) + (act.duration_s / 60 if sport else 0))))
        ws["garmin"].daily("active_energy", d, round(rnd.gauss(520, 120) + ((act.calories or 0) if sport else 0)))
        ws["garmin"].daily("floors", d, max(0, round(rnd.gauss(9, 4))))
        ws["garmin"].daily("stress", d, max(5, min(90, round(rnd.gauss(32 - 6 * t, 8)))))
        ws["garmin"].daily("body_battery", d, max(20, min(100, round(rnd.gauss(78 + 6 * t, 9)))))
        ws["garmin"].daily("vo2max", d, round(47.0 + 3.2 * t + rnd.gauss(0, 0.15), 1))
        rhr = 58.5 - 4.0 * t + rnd.gauss(0, 1.3) + (2 if rnd.random() < 0.08 else 0)
        ws["garmin"].daily("resting_hr", d, round(rhr))
        # Schlaf (Ring)
        bed = base - timedelta(hours=1, minutes=rnd.randint(-40, 70))
        asleep = rnd.gauss(445 if not weekend else 480, 35)
        deep, rem = asleep * rnd.uniform(0.15, 0.22), asleep * rnd.uniform(0.19, 0.25)
        light = asleep - deep - rem
        awake = rnd.uniform(15, 45)
        end_ts = bed + timedelta(minutes=asleep + awake)
        hrv = 52 + 10 * t + rnd.gauss(0, 6)
        ws["oura"].sleep(SleepIn(source_id=f"o{i}", start=bed, end=end_ts, asleep_min=asleep, deep_min=deep, rem_min=rem, light_min=light,
                                 awake_min=awake, score=round(max(50, min(98, 72 + (asleep - 440) / 6 + rnd.gauss(0, 5)))),
                                 efficiency=round(asleep / (asleep + awake) * 100), avg_hr=round(rhr + 2), hrv=round(hrv)))
        ws["oura"].daily("readiness", d, round(max(40, min(98, 74 + (hrv - 55) * 0.8 - (rhr - 56) * 1.5 + rnd.gauss(0, 4)))))
        ws["oura"].daily("skin_temp_dev", d, round(rnd.gauss(0, 0.25), 2))
        ws["oura"].daily("respiratory_rate", d, round(rnd.gauss(14.6, 0.4), 1))
        ws["oura"].daily("spo2", d, round(min(99.5, rnd.gauss(96.8, 0.7)), 1))
        # Ernährung (manche Tage)
        if rnd.random() < 0.6:
            ws["apple_health"].daily("calories_in", d, round(rnd.gauss(2350, 250)))
            ws["apple_health"].daily("protein", d, round(rnd.gauss(135, 20)))
            ws["apple_health"].daily("water", d, round(rnd.gauss(2300, 400)))
    counts = {s: w.flush() for s, w in ws.items()}
    for s in DEMO_SOURCES:
        c = db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == s))
        if c is None:
            c = Connection(user_id=user.id, provider=s, enabled=True, status="ok", config={"demo": True}, cursor={},
                           account="Beispieldaten", last_sync_at=utcnow(), last_success_at=utcnow())
            db.add(c)
    db.commit()
    return counts
