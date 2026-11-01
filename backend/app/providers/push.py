"""Quellen ohne Abfrage: Daten kommen per Webhook, Datei-Upload oder Eingabe."""
from .base import Provider


class AppleHealth(Provider):
    key = "apple_health"
    name = "Apple Health"
    kind = "push"
    color = "#ff375f"
    initials = "AH"
    website = "https://www.apple.com/health/"
    delivers = ["activity", "sleep", "heart", "body", "nutrition", "metabolic", "workouts"]
    summary = "iPhone und Apple Watch: automatisch per App „Health Auto Export“ oder einmalig über den Export der Health-App."
    setup = [
        "Automatisch: Die iOS-App „Health Auto Export – JSON+CSV“ installieren (Premium-Funktion „REST API“).",
        "In der App eine Automatisierung „REST API“ anlegen: URL siehe unten, Format JSON, Gruppierung „Tag“ "
        "für Summen wie Schritte, Häufigkeit z. B. stündlich.",
        "Einmalig: In der Health-App auf dein Profilbild → „Alle Gesundheitsdaten exportieren“ und die export.zip unter "
        "„Datei importieren“ hochladen. Große Exporte brauchen einige Minuten.",
    ]
    note = "Apple bietet keine Online-Schnittstelle; Daten kommen deshalb vom iPhone zu BodyBase, nicht umgekehrt."


class HealthConnect(Provider):
    key = "health_connect"
    name = "Android Health Connect"
    kind = "push"
    color = "#4285f4"
    initials = "HC"
    website = "https://health.google/health-connect-android/"
    delivers = ["activity", "sleep", "heart", "body", "nutrition"]
    summary = "Google Fit, Samsung Health, Fitbit, Xiaomi, Zepp, Oura & Co. landen auf dem Handy in Health Connect. Die App „HC Webhook“ schickt alles automatisch an BodyBase."
    setup = [
        "Auf dem Android-Handy die App „HC Webhook“ installieren (Google Play oder github.com/mcnaveen/health-connect-webhook).",
        "In der App den Zugriff auf Health Connect erlauben und unter „Data Types“ auswählen, was übertragen werden soll.",
        "Unter „Webhooks“ einen neuen Webhook anlegen: Adresse unten einfügen, Format JSON.",
        "Bei „Headers“ den Namen „X-API-Key“ und als Wert den Schlüssel unten eintragen. Mit „Test“ prüfen.",
        "Unter „Sync“ ein Intervall wählen (z. B. alle 30 Minuten). Fertig: Neue Werte kommen von selbst.",
    ]
    note = ("Google schaltet die alte Google-Fit-Schnittstelle Ende 2026 ab. Health Connect ist der Nachfolger und läuft nur auf dem Handy, "
            "deshalb braucht es die kleine Weiterleitungs-App. Tipp: In HC Webhook den Puls auf „1 Minute“ stellen, das spart Datenvolumen.")


class Api(Provider):
    key = "api"
    name = "Eigene Skripte (API)"
    kind = "push"
    color = "#8fa2ff"
    initials = "{}"
    delivers = ["activity", "sleep", "heart", "body", "nutrition", "metabolic", "workouts"]
    summary = "Beliebige Werte per HTTP an BodyBase schicken: aus Skripten, Node-RED, Tasker, iOS-Kurzbefehlen oder einer Waage."
    setup = ["Werte als JSON an die Adresse unten senden (Beispiel siehe dort)."]


class Files(Provider):
    key = "file"
    name = "Trainingsdateien"
    kind = "file"
    color = "#9aa6b8"
    initials = "FIT"
    delivers = ["workouts"]
    summary = "FIT-, GPX- und TCX-Dateien von jeder Uhr und jedem Radcomputer, auch mehrere auf einmal oder als .gz."
    setup = ["Dateien unter „Datei importieren“ hochladen."]


class Csv(Provider):
    key = "csv"
    name = "CSV-Tabellen"
    kind = "file"
    color = "#64c08b"
    initials = "CSV"
    delivers = ["body", "nutrition", "activity", "heart"]
    summary = "Exporte von Waagen-Apps (Renpho, Eufy, Libra), Ernährungs-Apps (Cronometer) oder eigene Tabellen."
    setup = [
        "Erste Zeile: Spaltennamen. Eine Spalte mit Datum (z. B. „Datum“ oder „Date“), dazu Spalten wie Gewicht, Körperfett, "
        "Schritte, Ruhepuls, Kalorien, Eiweiß. Einheiten in Klammern werden umgerechnet (z. B. „Weight (lb)“).",
        "Oder lang: Spalten „Datum“, „Metrik“, „Wert“.",
    ]


class StrengthLog(Provider):
    key = "strength"
    name = "Krafttraining"
    kind = "file"
    color = "#f5a524"
    initials = "KT"
    delivers = ["workouts"]
    summary = "Eigener Trainings-Tracker in BodyBase: Übungen, Sätze, Routinen, Rekorde. Übernimmt auch Exporte aus Hevy und Strong."
    setup = ["Im Bereich „Kraft“ ein Training starten oder unter „Importieren“ den CSV-Export aus Hevy bzw. Strong hochladen."]


class Manual(Provider):
    key = "manual"
    name = "Eigene Eingaben"
    kind = "file"
    color = "#e9eef1"
    initials = "✎"
    delivers = ["body", "heart", "nutrition"]
    summary = "Werte von Hand eintragen, zum Beispiel Gewicht, Blutdruck oder Taillenumfang."
    setup = ["Auf der Seite „Körper“ oder „Trends“ auf „Wert eintragen“ klicken."]
