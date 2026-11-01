from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .timeutil import utcnow

# BigInteger als Primärschlüssel; SQLite (Tests) kennt Autoincrement nur bei INTEGER
BigId = BigInteger().with_variant(Integer(), "sqlite")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user")
    active: Mapped[bool | None] = mapped_column(Boolean, default=True, nullable=True)
    token_version: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "f", "m", "d"
    prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Ziele, Quellen-Reihenfolge, Startseite
    ingest_token: Mapped[str | None] = mapped_column(Text, nullable=True)  # verschlüsselt; für Webhooks (Apple Health, eigene Skripte)
    ingest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tour_done: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(String(120), nullable=True)
    used_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ServerSetting(Base):
    """Einstellungen aus der Administration, zum Beispiel Zugangsdaten der Anbieter-Apps (verschlüsselt)."""
    __tablename__ = "server_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(60))
    text: Mapped[str | None] = mapped_column(Text, nullable=True)


class Connection(Base):
    """Eine Verbindung eines Nutzers zu einem Anbieter (Strava, Withings, Garmin …)."""
    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_connection_user_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | ok | error | auth
    account: Mapped[str | None] = mapped_column(String(160), nullable=True)  # Anzeigename beim Anbieter
    auth: Mapped[str | None] = mapped_column(Text, nullable=True)  # verschlüsseltes JSON (Tokens, Schlüssel)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # nicht geheime Einstellungen
    cursor: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Stand der letzten Synchronisierung
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    syncing: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trigger: Mapped[str | None] = mapped_column(String(20), nullable=True)  # auto | manual | webhook | import


class Sample(Base):
    """Ein Messwert: Gewicht, Ruhepuls, Schritte eines Tages, Blutzucker … immer in der Basiseinheit der Metrik."""
    __tablename__ = "samples"
    __table_args__ = (
        UniqueConstraint("user_id", "metric", "source", "ts", name="uq_sample"),
        Index("ix_samples_user_metric_day", "user_id", "metric", "day"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(40))
    ts: Mapped[datetime] = mapped_column(DateTime)  # UTC
    day: Mapped[date] = mapped_column(Date)  # Kalendertag in der eingestellten Zeitzone
    value: Mapped[float] = mapped_column(Float)


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "source_id", name="uq_activity"),
        Index("ix_activities_user_start", "user_id", "start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(120))
    sport: Mapped[str] = mapped_column(String(30), default="other")  # eigene Kategorien, siehe sports.py
    sport_raw: Mapped[str | None] = mapped_column(String(80), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    start: Mapped[datetime] = mapped_column(DateTime)  # UTC
    day: Mapped[date] = mapped_column(Date)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moving_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    load: Mapped[float | None] = mapped_column(Float, nullable=True)  # Trainingsbelastung (TSS, Strain …)
    volume_kg: Mapped[float | None] = mapped_column(Float, nullable=True)  # Krafttraining: bewegtes Gewicht
    polyline: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duplicate_of: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SleepSession(Base):
    __tablename__ = "sleep_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "source_id", name="uq_sleep"),
        Index("ix_sleep_user_day", "user_id", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(120))
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    day: Mapped[date] = mapped_column(Date)  # Tag des Aufwachens
    asleep_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    deep_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    rem_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    light_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    awake_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    efficiency: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv: Mapped[float | None] = mapped_column(Float, nullable=True)
    nap: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | done | failed
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------- Krafttraining (eigener Tracker, wie Hevy) ----------

class Exercise(Base):
    """Übung. user_id leer = eingebaute Übung aus dem Katalog (strength_catalog.py)."""
    __tablename__ = "exercises"
    __table_args__ = (Index("ix_exercises_user", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    key: Mapped[str | None] = mapped_column(String(60), nullable=True, unique=True)  # nur eingebaute
    name: Mapped[str] = mapped_column(String(120))
    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)  # andere Namen (Hevy, Strong, Englisch)
    equipment: Mapped[str] = mapped_column(String(20), default="other")
    primary: Mapped[str] = mapped_column(String(20), default="other")
    secondary: Mapped[list | None] = mapped_column(JSON, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="weight_reps")  # weight_reps | bodyweight | weighted_bw | assisted_bw | duration | distance
    archived: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    media: Mapped[str | None] = mapped_column(String(80), nullable=True)  # Kennung in free-exercise-db (Bilder, Anleitung)
    media_checked: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    merged_into: Mapped[int | None] = mapped_column(Integer, nullable=True)  # zusammengeführt: Importe landen dort
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Routine(Base):
    __tablename__ = "routines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    folder: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    # [{exercise_id, rest_s, notes, superset, sets: [{type, kg, reps, duration_s, distance_m}]}]
    exercises: Mapped[list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Workout(Base):
    __tablename__ = "workouts"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "source_id", name="uq_workout"),
        Index("ix_workouts_user_start", "user_id", "start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(20), default="bodybase")  # bodybase | hevy | strong
    source_id: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    start: Mapped[datetime] = mapped_column(DateTime)  # UTC
    end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    day: Mapped[date] = mapped_column(Date)
    routine_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Reihenfolge, Notizen, Pausenzeit und Supersätze je Übung: [{exercise_id, notes, rest_s, superset}]
    layout: Mapped[list | None] = mapped_column(JSON, nullable=True)
    volume_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    sets_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prs: Mapped[list | None] = mapped_column(JSON, nullable=True)  # bei diesem Training aufgestellte Rekorde
    hr: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Pulsverlauf live per Bluetooth {start, t, v, marks}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkoutSet(Base):
    __tablename__ = "workout_sets"
    __table_args__ = (Index("ix_wsets_user_ex", "user_id", "exercise_id", "start"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("workouts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(Integer)
    exercise_id: Mapped[int] = mapped_column(Integer)
    start: Mapped[datetime] = mapped_column(DateTime)  # Beginn des Trainings, für schnelle Verläufe
    ex_pos: Mapped[int] = mapped_column(Integer)
    pos: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(10), default="normal")  # normal | warmup | failure | drop
    kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)


class ActiveWorkout(Base):
    """Laufendes Training, damit es Neuladen, Handywechsel und Funklöcher im Studio übersteht."""
    __tablename__ = "active_workouts"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class HeartRateRaw(Base):
    """Einzelne Pulswerte, nur die letzten Tage (siehe heartrate.py). Danach bleiben Stundenmittel in samples
    und der Verlauf jeder Trainingseinheit in activities.details["hr"]."""
    __tablename__ = "heart_rate_raw"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "ts", name="uq_hr_raw"),
        Index("ix_hr_raw_user_ts", "user_id", "ts"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(40))
    ts: Mapped[datetime] = mapped_column(DateTime)
    bpm: Mapped[float] = mapped_column(Float)


# ---------- Gewohnheiten ----------

class Habit(Base):
    """Tägliche Gewohnheit, z. B. Liegestütze mit Ziel, das jeden Montag steigt."""
    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="count")  # count (Zahl erreichen) | check (erledigt ja/nein)
    exercise_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # zählt dann für die Körperkarte
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)  # Ziel in der Startwoche
    increment: Mapped[float | None] = mapped_column(Float, nullable=True)  # Erhöhung je Woche (Montag)
    max_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    start: Mapped[date] = mapped_column(Date)
    weekdays: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 0=Mo … 6=So, leer = täglich
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    archived: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class HabitLog(Base):
    __tablename__ = "habit_logs"
    __table_args__ = (UniqueConstraint("habit_id", "day", name="uq_habit_day"), Index("ix_habit_logs_user_day", "user_id", "day"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(Integer)
    day: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApiKey(Base):
    """Persönlicher API-Schlüssel für andere Programme (Home Assistant, Skripte, Auswertungen)."""
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(16))  # zum Wiedererkennen, z. B. "bbk_a1b2"
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(10), default="read")  # read | write
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BodySegment(Base):
    """Körperzusammensetzung je Segment (Arme, Beine, Rumpf), z. B. von Withings Body Scan / Body Segment."""
    __tablename__ = "body_segments"
    __table_args__ = (UniqueConstraint("user_id", "source", "ts", "kind", "position", name="uq_body_segment"),
                      Index("ix_body_segments_user_ts", "user_id", "ts"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(40))
    ts: Mapped[datetime] = mapped_column(DateTime)
    day: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(10))  # muscle | fat | ffm
    position: Mapped[int] = mapped_column(Integer)  # Segment-Code der Quelle
    value: Mapped[float] = mapped_column(Float)  # kg
