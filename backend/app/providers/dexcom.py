from datetime import timedelta

from ..timeutil import parse_iso
from .base import Field, OAuthSpec, Provider


class Dexcom(Provider):
    key = "dexcom"
    name = "Dexcom"
    color = "#58a618"
    initials = "Dx"
    website = "https://developer.dexcom.com"
    delivers = ["metabolic"]
    summary = "Glukosewerte (CGM) aus dem Dexcom-Konto, alle 5 Minuten."
    setup = ["Region wählen (Europa oder USA) und auf „Verbinden“ klicken."]
    app_setup = [
        "Auf https://developer.dexcom.com ein Konto anlegen und eine App erstellen.",
        "Als Redirect URI die unten angezeigte Rücksprung-Adresse eintragen.",
        "Client ID und Client Secret hier eintragen. Für echte Daten muss Dexcom die App für den Produktivbetrieb freischalten.",
    ]
    app_fields = [Field("client_id", "Client ID"), Field("client_secret", "Client Secret", "password", secret=True),
                  Field("region", "Region", "select", options=[{"value": "eu", "label": "Europa (api.dexcom.eu)"},
                                                                {"value": "us", "label": "USA (api.dexcom.com)"}], default="eu")]
    oauth = OAuthSpec("https://api.dexcom.eu/v2/oauth2/login", "https://api.dexcom.eu/v2/oauth2/token", ["offline_access"])
    note = "Dexcom stellt Daten mit etwa 1–3 Stunden Verzögerung bereit."

    def base(self, app: dict) -> str:
        return "https://api.dexcom.com" if app.get("region") == "us" else "https://api.dexcom.eu"

    def oauth_spec(self, app: dict) -> OAuthSpec:
        b = self.base(app)
        return OAuthSpec(f"{b}/v2/oauth2/login", f"{b}/v2/oauth2/token", ["offline_access"])

    def sync(self, ctx):
        base = self.base(ctx.app)
        start = ctx.since
        while start < ctx.until:
            end = min(ctx.until, start + timedelta(days=30))
            data = ctx.get(f"{base}/v3/users/self/egvs", params={
                "startDate": start.strftime("%Y-%m-%dT%H:%M:%S"), "endDate": end.strftime("%Y-%m-%dT%H:%M:%S")}) or {}
            for r in data.get("records", []):
                value = r.get("value")
                if r.get("unit") == "mmol/L" and value is not None:
                    value = float(value) * 18.0182
                ctx.writer.sample("glucose", parse_iso(r.get("systemTime") + "Z" if r.get("systemTime") and "Z" not in r.get("systemTime") else r.get("systemTime")), value)
            start = end
