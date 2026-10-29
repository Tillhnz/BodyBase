from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .config import settings


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.timezone)
    except Exception:
        return ZoneInfo("Europe/Berlin")


def utcnow() -> datetime:
    """Aktuelle Zeit in UTC ohne Zeitzone (so wird überall gespeichert)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc(dt: datetime) -> datetime:
    """Zeit mit Zeitzone nach UTC ohne Zeitzone; Zeiten ohne Zone gelten als UTC."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def local_to_utc(dt: datetime) -> datetime:
    """Lokale Zeit ohne Zone (Ortszeit des Servers) nach UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz())
    return to_utc(dt)


def local_day(dt_utc: datetime) -> date:
    """Kalendertag in der eingestellten Zeitzone für eine UTC-Zeit."""
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(tz()).date()


def today() -> date:
    return datetime.now(tz()).date()


def day_start_utc(d: date) -> datetime:
    """Tagesbeginn (00:00 Ortszeit) als UTC."""
    return local_to_utc(datetime(d.year, d.month, d.day))


def parse_iso(value) -> datetime | None:
    """Liest ISO-8601 in vielen Varianten ('Z', '+0200', ' ' statt 'T'), Millisekunden-Epoch oder Sekunden-Epoch."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return to_utc(value)
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e11:  # Millisekunden
            v /= 1000
        return datetime.fromtimestamp(v, timezone.utc).replace(tzinfo=None)
    s = str(value).strip()
    if s.isdigit():
        return parse_iso(int(s))
    s = s.replace("Z", "+00:00")
    if " " in s and "T" not in s:
        head, _, rest = s.partition(" ")
        s = head + "T" + rest.replace(" ", "")
    # +0200 -> +02:00
    if len(s) >= 5 and (s[-5] in "+-") and s[-4:].isdigit() and ":" not in s[-5:]:
        s = s[:-2] + ":" + s[-2:]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None
        return local_to_utc(dt)
    return to_utc(dt) if dt.tzinfo else local_to_utc(dt)


def parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
