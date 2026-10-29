import hashlib

from ..timeutil import parse_iso
from .base import Field, Provider, SyncError, epoch


class Nightscout(Provider):
    key = "nightscout"
    name = "Nightscout"
    kind = "apikey"
    color = "#4f6d7a"
    initials = "Ns"
    website = "https://nightscout.github.io"
    official = True
    delivers = ["metabolic"]
    summary = "Glukosewerte aus deiner eigenen Nightscout-Instanz (Libre, Dexcom, Medtronic … über xDrip, Juggluco & Co.)."
    setup = [
        "Adresse deiner Nightscout-Seite eintragen.",
        "In Nightscout unter Admin-Werkzeuge einen Zugangs-Token mit der Rolle „readable“ anlegen und hier eintragen. "
        "Alternativ das API_SECRET verwenden.",
    ]
    fields = [Field("url", "Nightscout-Adresse", "url", placeholder="https://mein-ns.example.de"),
              Field("token", "Zugangs-Token oder API_SECRET", "password", secret=True)]

    def _req(self, ctx, path, params=None):
        url = ctx.config.get("url", "").rstrip("/")
        token = ctx.auth.get("token", "")
        params = dict(params or {})
        headers = {"Accept": "application/json"}
        if "-" in token and len(token) < 60:
            params["token"] = token  # Zugangs-Token
        else:
            headers["api-secret"] = hashlib.sha1(token.encode()).hexdigest()
        return ctx.get(f"{url}{path}", params=params, headers=headers, auth="none")

    def connect(self, ctx, values):
        url = (values.get("url") or "").strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise SyncError("Die Adresse muss mit http:// oder https:// beginnen.")
        ctx.config["url"] = url
        ctx.auth = {"token": (values.get("token") or "").strip()}
        status = self._req(ctx, "/api/v1/status.json") or {}
        return status.get("name") or url

    def sync(self, ctx):
        since = epoch(ctx.since) * 1000
        for _ in range(100):
            items = self._req(ctx, "/api/v1/entries/sgv.json", {"count": 5000, "find[date][$gt]": since}) or []
            if not items:
                break
            for e in items:
                ctx.writer.sample("glucose", parse_iso(e.get("date")), e.get("sgv"))
            newest = max(int(e.get("date") or 0) for e in items)
            if len(items) < 5000 or newest <= since:
                break
            since = newest
