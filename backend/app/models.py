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
