"""Verzeichnis aller Anbieter."""
from .base import Provider
from .concept2 import Concept2
from .dexcom import Dexcom
from .fitbit import Fitbit
from .garmin import Garmin
from .hevy import Hevy
from .homeassistant import HomeAssistant
from .intervals import Intervals
from .nightscout import Nightscout
from .oura import Oura
from .polar import Polar
from .push import Api, AppleHealth, Csv, Files, HealthConnect, Manual, StrengthLog
from .strava import Strava
from .suunto import Suunto
from .wahoo import Wahoo
from .whoop import Whoop
from .withings import Withings

_ALL: list[Provider] = [
    Garmin(), Strava(), AppleHealth(), Withings(), Fitbit(), Polar(), Oura(), Whoop(), Suunto(), Wahoo(), Intervals(),
    Concept2(), Hevy(), HealthConnect(), HomeAssistant(), Nightscout(), Dexcom(), StrengthLog(), Api(), Files(), Csv(), Manual(),
]
PROVIDERS: dict[str, Provider] = {p.key: p for p in _ALL}


def get(key: str) -> Provider | None:
    return PROVIDERS.get(key)


def all_providers() -> list[Provider]:
    return list(_ALL)


def name_of(key: str) -> str:
    p = PROVIDERS.get(key)
    return p.name if p else key
