import re

from fastapi import APIRouter, Depends

from ..config import settings
from ..models import User
from ..security import current_user

router = APIRouter(prefix="/api", tags=["map"])

OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende'
CARTO_ATTRIBUTION = OSM_ATTRIBUTION + ' &copy; <a href="https://carto.com/attributions">CARTO</a>'
KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{6,128}$")


def build_map_config() -> dict:
    """Kachelserver für die Karten: eigene Kachel-URL, CARTO mit Schlüssel (dunkel) oder OpenStreetMap."""
    url = (settings.map_tile_url or "").strip()
    if url.startswith("https://") and "{z}" in url:
        return {"url": url, "dark": False, "subdomains": "abc", "attribution": OSM_ATTRIBUTION, "max_zoom": 19,
                "provider": "custom"}
    key = (settings.carto_api_key or "").strip()
    if key and KEY_RE.match(key):
        return {"url": "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?key=" + key, "dark": True,
                "subdomains": "abcd", "attribution": CARTO_ATTRIBUTION, "max_zoom": 19, "provider": "carto"}
    return {"url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png", "dark": False, "subdomains": "abc",
            "attribution": OSM_ATTRIBUTION, "max_zoom": 19, "provider": "osm"}


@router.get("/map-config")
def map_config(user: User = Depends(current_user)):
    return build_map_config()
