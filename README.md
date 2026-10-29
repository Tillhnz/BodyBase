# BodyBase

Der Kern, an dem alle deine Fitness- und Gesundheitsdaten zusammenkommen: Uhr, Ring, Waage, Radcomputer, Schlafsensor, Glukosesensor und Trainings-Apps an einem Ort, auf deinem eigenen Server. Läuft als LXC-Container auf Proxmox, Design wie bei BikeHelper und NetworkHelper.

## Was BodyBase kann

- **Tageskern auf der Startseite:** Ringe für Bewegung, Schlaf, Erholung und Herz, dazu die wichtigsten Werte des Tages mit Vergleich zu deinem 30-Tage-Schnitt.
- **Ein Wert, viele Quellen:** Liefern Garmin und Withings beide ein Gewicht, entscheidet eine Rangfolge pro Kategorie, welche Quelle zählt. Doppelte Aktivitäten (Strava + Garmin + intervals.icu) werden erkannt und zusammengeführt.
- **Bereiche:** Aktivitäten (mit Strecke, Puls, Leistung, Karte), Schlaf (Phasen, Effizienz, Regelmäßigkeit), Gesundheit (Gewicht, Körperfett, Blutdruck, Glukose, SpO₂ …) und Trends mit frei kombinierbaren Werten.
- **Automatischer Abgleich** aller Verbindungen im Hintergrund (Standard: stündlich), beim ersten Verbinden 90 Tage rückwirkend. Zugänge der Anbieter liegen verschlüsselt in der Datenbank.
- **Mehrere Personen:** Das erste Konto wird Administrator, weitere kommen per Einladung. Jede Person sieht nur ihre eigenen Daten.
- **Updates und Sicherungen** per Klick unter Administration, Sicherungen optional mit age verschlüsselt und auf ein NAS.
- **Beispieldaten** zum Ausprobieren: auf der leeren Startseite „Beispieldaten laden“, oder `bodybase demo du@example.de`.

## Schnittstellen

| Quelle | Verbindung | Daten |
|---|---|---|
| Garmin Connect | Anmeldung (E-Mail/Passwort) | Schritte, Schlaf, HRV, Ruhepuls, Body Battery, Stress, SpO₂, VO₂max, Index-Waage, Aktivitäten |
| Strava | OAuth | Aktivitäten mit Strecke, Puls, Leistung, Karte |
| Apple Health | Push (Health Auto Export) oder Export-Datei | Alles aus iPhone und Apple Watch |
| Android Health Connect | Push (Weiterleitungs-App) | Samsung Health, Google Fit, Xiaomi, Zepp … |
| Withings | OAuth | Waage, Körperzusammensetzung, Blutdruck, Schlaf, Schritte |
| Fitbit / Google Pixel Watch | OAuth | Schritte, Ruhepuls, HRV, Schlafphasen, SpO₂, VO₂max, Gewicht, Trainings |
| Polar | OAuth (AccessLink) | Trainings, Schlaf, Nightly Recharge, Aktivität |
| Oura | OAuth | Schlaf, Bereitschaft, HRV, Temperatur, SpO₂, Schritte |
| WHOOP | OAuth | Recovery, HRV, Strain, Schlaf, Trainings |
| Suunto | OAuth | Trainings |
| Wahoo | OAuth | ELEMNT, KICKR, Wahoo-App |
| intervals.icu | API-Schlüssel | Aktivitäten (auch COROS, Zwift …) und Wellness |
| Concept2 Logbook | OAuth | RowErg, SkiErg, BikeErg |
| Hevy | API-Schlüssel | Krafttraining mit Sätzen und Gewichten |
| Dexcom | OAuth | Glukose (CGM) |
| Nightscout | Adresse + Token | Glukose (Libre, Dexcom … über xDrip, Juggluco) |
| Home Assistant | Adresse + Token | Beliebige Sensoren, z. B. Waage über ESPHome |
| Eigene Skripte | HTTP-API mit Token | Alles, z. B. aus Node-RED, Tasker, iOS-Kurzbefehlen |
| Trainingsdateien | Upload | FIT, GPX, TCX (auch .gz, mehrere auf einmal) |
| CSV-Tabellen | Upload | Renpho, Eufy, Libra, Cronometer, eigene Tabellen |
| Eigene Eingaben | von Hand | Gewicht, Blutdruck, Umfänge … |

Für die OAuth-Anbieter legt der Administrator einmal eine (kostenlose) Entwickler-App beim Anbieter an. BodyBase zeigt unter **Administration → Anbieter** für jeden Anbieter die Schritte und die genaue Rückruf-Adresse an. Dafür braucht BodyBase eine öffentliche HTTPS-Adresse (siehe unten). Garmin, intervals.icu, Hevy, Nightscout, Home Assistant und alle Uploads funktionieren auch ohne.

## Installation auf Proxmox

### Variante A: Ein Befehl auf dem Proxmox-Host (empfohlen)

In der Proxmox-Oberfläche: Rechenzentrum → dein Knoten → **Shell**, dann:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Tillhnz/BodyBase/main/proxmox/create-lxc.sh)"
```

Das Skript legt einen Debian-12-LXC an (2 Kerne, 2 GB RAM, 12 GB Festplatte, `nesting` und `keyctl` für Docker), startet ihn und installiert BodyBase unter `/opt/BodyBase`. Anpassen lässt sich alles über Variablen:

```bash
CTID=140 STORAGE=local-zfs IP=192.168.1.60/24 GW=192.168.1.1 bash -c "$(curl -fsSL https://raw.githubusercontent.com/Tillhnz/BodyBase/main/proxmox/create-lxc.sh)"
```

### Variante B: In einem vorhandenen LXC oder einer VM

Debian oder Ubuntu, bei einem LXC mit **nesting** und **keyctl** (Container → Optionen → Features). Im Container als root:

```bash
curl -fsSL https://raw.githubusercontent.com/Tillhnz/BodyBase/main/install.sh | bash
```

Danach ist BodyBase unter `http://<IP-des-Containers>:8080` erreichbar. Das erste Konto, das du anlegst, wird Administrator.

## Von außen erreichbar machen

Im Nginx Proxy Manager einen Proxy Host auf `<IP>:8080` anlegen, SSL aktivieren, dann im Container:

```bash
bodybase url https://body.deine-domain.de
```

Im Proxy Host unter *Advanced* für große Apple-Health-Exporte am besten `client_max_body_size 0;` eintragen.

## Befehle im Container

```bash
bodybase update                 # neueste Version holen und neu starten
bodybase lock | unlock          # Registrierung sperren / erlauben
bodybase url <adresse>          # öffentliche Adresse ändern
bodybase backup                 # Datenbank sichern
bodybase restore <datei>        # Sicherung zurückspielen
bodybase backup-dir /mnt/nas    # Sicherungen auf ein NAS legen
bodybase backup-key             # Sicherungen verschlüsseln (age)
bodybase demo <e-mail>          # Beispieldaten erzeugen
bodybase logs                   # Protokolle
```

Passwort vergessen: `cd /opt/BodyBase && docker compose exec backend python -m app.cli reset-password du@example.de NeuesPasswort`

## Aufbau

- `backend/` FastAPI + SQLAlchemy (PostgreSQL), Sync-Engine und ein Modul pro Anbieter unter `app/providers/`
- `frontend/` React + Vite, ausgeliefert von nginx
- `updater/` kleiner Dienst für Updates und Sicherungen aus der Oberfläche
- `proxmox/create-lxc.sh`, `install.sh` Installation

Einen neuen Anbieter hinzufügen: Klasse von `Provider` ableiten (`app/providers/base.py`), `sync()` implementieren und in `app/providers/__init__.py` eintragen. Oberfläche, Einrichtungsschritte und Status kommen automatisch.

Entwicklung:

```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest -q
cd frontend && npm install && npm run dev
```
