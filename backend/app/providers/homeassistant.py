from datetime import timedelta

from .. import metrics as M
from ..timeutil import local_day, parse_iso
from .base import Field, Provider, SyncError


class HomeAssistant(Provider):
    key = "homeassistant"
    name = "Home Assistant"
    kind = "apikey"
    color = "#18bcf2"
    initials = "HA"
    website = "https://www.home-assistant.io"
    delivers = ["body", "heart", "activity", "sleep"]
    summary = "Beliebige Sensoren aus Home Assistant übernehmen, zum Beispiel eine Waage (Xiaomi, Renpho über ESPHome), Blutdruck oder Schritte der Companion-App."
    setup = [
        "In Home Assistant unter Profil → Sicherheit ein langlebiges Zugriffstoken erstellen.",
        "Adresse und Token eintragen.",
        "Danach in der Verbindung festlegen, welcher Sensor zu welcher Messgröße gehört (z. B. sensor.waage_gewicht → Gewicht).",
    ]
    fields = [Field("url", "Home-Assistant-Adresse", "url", placeholder="http://192.168.1.20:8123"),
              Field("token", "Langlebiges Zugriffstoken", "password", secret=True),
              Field("mapping", "Sensoren", "textarea", required=False,
                    help="Eine Zeile pro Sensor: entity_id = Messgröße, z. B. sensor.waage_gewicht = weight",
                    placeholder="sensor.waage_gewicht = weight\nsensor.handy_schritte = steps")]

    def _h(self, ctx):
        return {"Authorization": f"Bearer {ctx.auth.get('token', '')}"}

    def connect(self, ctx, values):
        url = (values.get("url") or "").strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise SyncError("Die Adresse muss mit http:// oder https:// beginnen.")
        ctx.config["url"] = url
        ctx.config["mapping"] = parse_mapping(values.get("mapping") or "")
        ctx.auth = {"token": (values.get("token") or "").strip()}
        info = ctx.get(f"{url}/api/config", headers=self._h(ctx), auth="none") or {}
        return info.get("location_name") or url

    def sync(self, ctx):
        mapping = ctx.config.get("mapping") or {}
        if not mapping:
            ctx.note("Noch keine Sensoren zugeordnet.")
            return
        url = ctx.config.get("url", "")
        counters: dict = {}  # Summen-Größen (Schritte …) sind in HA Tageszähler: höchster Stand des Tages zählt
        start = ctx.since
        while start < ctx.until:
            end = min(ctx.until, start + timedelta(days=10))
            data = ctx.get(f"{url}/api/history/period/{start.isoformat()}+00:00", headers=self._h(ctx), auth="none", params={
                "filter_entity_id": ",".join(mapping), "end_time": end.isoformat() + "+00:00",
                "minimal_response": "", "no_attributes": "", "significant_changes_only": "0"}) or []
            for series in data:
                entity = None
                for st in series:
                    entity = st.get("entity_id") or entity
                    metric = mapping.get(entity)
                    if not metric:
                        continue
                    state = st.get("state")
                    if state in (None, "unknown", "unavailable", ""):
                        continue
                    ts = parse_iso(st.get("last_changed") or st.get("last_updated"))
                    if M.METRICS[metric].agg == "sum":
                        try:
                            v = float(state)
                        except ValueError:
                            continue
                        key = (metric, local_day(ts)) if ts else None
                        if key and v > counters.get(key, float("-inf")):
                            counters[key] = v
                    else:
                        ctx.writer.sample(metric, ts, state)
            start = end
        for (metric, day), value in counters.items():
            ctx.writer.daily(metric, day, value)


def parse_mapping(text: str | dict) -> dict:
    if isinstance(text, dict):
        return {k: v for k, v in text.items() if v in M.METRICS}
    out = {}
    for line in str(text).splitlines():
        if "=" not in line:
            continue
        ent, metric = (x.strip() for x in line.split("=", 1))
        if ent and metric in M.METRICS:
            out[ent] = metric
    return out
