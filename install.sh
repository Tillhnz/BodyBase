#!/usr/bin/env bash
# BodyBase – Installations- und Hilfsskript
#
# Installieren (auf einer frischen Debian-/Ubuntu-Maschine):
#   curl -fsSL https://raw.githubusercontent.com/Tillhnz/BodyBase/main/install.sh | bash
#   oder im geklonten Projektordner: ./install.sh
#
# Weitere Befehle:
#   ./install.sh update          Neueste Version holen und neu starten
#   ./install.sh lock            Neue Registrierungen sperren
#   ./install.sh unlock          Neue Registrierungen wieder erlauben
#   ./install.sh url <adresse>   Öffentliche Adresse ändern (z. B. https://body.example.de)
#   ./install.sh backup          Datenbank sichern (Ordner backups/ oder BACKUP_DIR, verschlüsselt wenn eingerichtet)
#   ./install.sh restore <datei> Eine Sicherung zurückspielen (ersetzt alle aktuellen Daten)
#   ./install.sh backup-dir <pfad>  Sicherungen in einen anderen Ordner legen (z. B. NFS-Freigabe)
#   ./install.sh backup-key      Schlüsselpaar für verschlüsselte Sicherungen erzeugen (privater Teil wird einmal angezeigt)
#   ./install.sh logs            Protokolle anzeigen
#   ./install.sh demo <e-mail>   Beispieldaten für ein Konto erzeugen (zum Ausprobieren)
#
# Nach der Installation gibt es alle Befehle auch kurz als „bodybase“, z. B.: bodybase update
#
# Umgebungsvariablen (optional):
#   BODYBASE_DIR=<ordner>        Zielordner bei der Installation (Standard: /opt/BodyBase)
#   BODYBASE_PUBLIC_URL=<url>    Öffentliche Adresse ohne Rückfrage setzen
#   BODYBASE_REPO=<git-url>      Anderes Repository verwenden
set -euo pipefail

REPO_URL="${BODYBASE_REPO:-https://github.com/Tillhnz/BodyBase.git}"
DEFAULT_DIR="${BODYBASE_DIR:-/opt/BodyBase}"

info() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✔\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m✘\033[0m %s\n' "$*" >&2; exit 1; }

# ---------- Hilfsfunktionen ----------

as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    die "Dafür sind Root-Rechte nötig. Melde dich als root an oder installiere sudo (apt install sudo)."
  fi
}

random_hex() { # $1 = Anzahl Bytes
  head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'
}

ask() { # $1 = Frage, $2 = Standardwert; funktioniert auch bei "curl | bash"
  local answer=""
  if [ -t 0 ]; then
    read -r -p "$1 [$2]: " answer || answer=""
  elif (exec </dev/tty) 2>/dev/null; then
    read -r -p "$1 [$2]: " answer </dev/tty || answer=""
  fi
  printf '%s' "${answer:-$2}"
}

# Ordner bestimmen: neben diesem Skript, falls dort das Projekt liegt, sonst Standardordner
script_dir=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  script_dir="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
fi
if [ -n "$script_dir" ] && [ -f "$script_dir/docker-compose.yml" ]; then
  APP_DIR="$script_dir"
else
  APP_DIR="$DEFAULT_DIR"
fi

get_env() { # KEY
  [ -f "$APP_DIR/.env" ] || return 0
  grep -E "^$1=" "$APP_DIR/.env" | head -n 1 | cut -d= -f2- || true
}

set_env() { # KEY VALUE
  local key="$1" raw="$2" file="$APP_DIR/.env" value
  value="${raw//\\/\\\\}"
  value="${value//&/\\&}"
  value="${value//|/\\|}"
  if grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    printf '%s=%s\n' "$key" "$raw" >> "$file"
  fi
}

web_port() { local p; p="$(get_env WEB_PORT)"; printf '%s' "${p:-8080}"; }

local_ip() {
  local ip=""
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || ip=""
  printf '%s' "${ip:-localhost}"
}

# ---------- Schritte ----------

ensure_packages() {
  local missing=()
  command -v git >/dev/null 2>&1 || missing+=(git)
  command -v curl >/dev/null 2>&1 || missing+=(curl)
  if [ "${#missing[@]}" -gt 0 ]; then
    command -v apt-get >/dev/null 2>&1 || die "Bitte installiere ${missing[*]} und starte das Skript erneut."
    info "Installiere ${missing[*]} …"
    as_root apt-get update -qq
    as_root apt-get install -y -qq "${missing[@]}"
  fi
}

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    info "Installiere Docker (offizielles Skript von get.docker.com) …"
    local tmp; tmp="$(mktemp)"
    curl -fsSL https://get.docker.com -o "$tmp"
    as_root sh "$tmp"
    rm -f "$tmp"
    if [ "$(id -u)" -ne 0 ]; then
      as_root usermod -aG docker "${USER:-$(id -un)}" || true
    fi
  fi
  pick_docker
  "${DOCKER[@]}" compose version >/dev/null 2>&1 \
    || die "Docker Compose fehlt. Bitte installiere das Docker-Compose-Plugin (siehe docs.docker.com/compose/install)."
  ok "Docker ist bereit."
}

# Mit oder ohne Root-Rechte, je nachdem, ob der Benutzer schon in der docker-Gruppe ist
pick_docker() {
  if docker info >/dev/null 2>&1; then
    DOCKER=(docker)
  elif as_root docker info >/dev/null 2>&1; then
    DOCKER=(as_root docker)
  else
    die "Der Docker-Dienst antwortet nicht. Prüfe mit: sudo systemctl status docker"
  fi
}

ensure_repo() {
  if [ -f "$APP_DIR/docker-compose.yml" ]; then
    return
  fi
  info "Lade BodyBase nach $APP_DIR …"
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
}

setup_env() {
  local env="$APP_DIR/.env"
  if [ -f "$env" ]; then
    ok ".env existiert bereits und bleibt unverändert."
    return
  fi
  cp "$APP_DIR/.env.example" "$env"
  chmod 600 "$env"
  set_env POSTGRES_PASSWORD "$(random_hex 16)"
  set_env SECRET_KEY "$(random_hex 32)"

  local url="${BODYBASE_PUBLIC_URL:-}"
  if [ -z "$url" ]; then
    echo
    echo "Unter welcher Adresse wird BodyBase später erreichbar sein?"
    echo "Noch keine Domain? Dann einfach Enter drücken, das lässt sich später ändern."
    url="$(ask "Adresse" "http://$(local_ip):$(web_port)")"
  fi
  url="${url%/}"
  set_env PUBLIC_URL "$url"
  ok ".env mit zufälligen Passwörtern angelegt."
}

start_stack() {
  info "Baue und starte BodyBase (der erste Start dauert einige Minuten) …"
  (cd "$APP_DIR" && "${DOCKER[@]}" compose up -d --build)
}

wait_healthy() {
  local port; port="$(web_port)"
  info "Warte, bis BodyBase antwortet …"
  for _ in $(seq 1 60); do
    if curl -fsS "http://localhost:${port}/api/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

report_start() {
  if wait_healthy; then
    ok "BodyBase läuft."
  else
    warn "BodyBase antwortet noch nicht. Die letzten Protokollzeilen:"
    (cd "$APP_DIR" && "${DOCKER[@]}" compose logs --tail 40) || true
    die "Start nicht bestätigt. Mehr Details mit: ./install.sh logs"
  fi
}

# ---------- Befehle ----------

cmd_install() {
  ensure_packages
  ensure_docker
  ensure_repo
  setup_env
  start_stack
  report_start
  as_root ln -sf "$APP_DIR/install.sh" /usr/local/bin/bodybase 2>/dev/null || true

  local port ip; port="$(web_port)"; ip="$(local_ip)"
  cat <<EOF

────────────────────────────────────────────────────────
 BodyBase ist installiert.

 Öffnen:        http://${ip}:${port}
 Ordner:        ${APP_DIR}

 Nächste Schritte
 1. Öffne die Adresse oben und lege dein Konto an.
 2. Danach neue Registrierungen sperren:
      bodybase lock
 3. Für den Zugriff aus dem Internet im Nginx Proxy Manager einen
    Proxy Host auf ${ip} Port ${port} anlegen, SSL aktivieren und
    dann die Adresse eintragen:
      bodybase url https://deine-domain.de
 4. Unter „Quellen“ Garmin, Strava, Withings & Co. verbinden.

 Aktualisieren:  bodybase update   (oder in der App unter Administration)
────────────────────────────────────────────────────────
EOF
}

require_install() {
  [ -f "$APP_DIR/docker-compose.yml" ] && [ -f "$APP_DIR/.env" ] \
    || die "Keine Installation in $APP_DIR gefunden. Starte zuerst: ./install.sh"
  command -v docker >/dev/null 2>&1 || die "Docker ist nicht installiert."
  pick_docker
}

cmd_update() {
  require_install
  if [ -d "$APP_DIR/.git" ]; then
    info "Hole die neueste Version …"
    git -C "$APP_DIR" pull --ff-only
  else
    warn "Kein Git-Ordner, überspringe das Herunterladen."
  fi
  start_stack
  report_start
  ok "Update abgeschlossen."
}

cmd_registration() { # true|false
  require_install
  set_env ALLOW_REGISTRATION "$1"
  (cd "$APP_DIR" && "${DOCKER[@]}" compose up -d)
  if [ "$1" = "false" ]; then ok "Neue Registrierungen sind gesperrt."; else ok "Neue Registrierungen sind erlaubt."; fi
}

cmd_url() {
  [ -n "${1:-}" ] || die "Bitte eine Adresse angeben, z. B.: ./install.sh url https://body.example.de"
  case "$1" in http://*|https://*) ;; *) die "Die Adresse muss mit http:// oder https:// beginnen." ;; esac
  require_install
  set_env PUBLIC_URL "${1%/}"
  (cd "$APP_DIR" && "${DOCKER[@]}" compose up -d)
  ok "Öffentliche Adresse gesetzt: ${1%/}"
}

cmd_logs() {
  require_install
  (cd "$APP_DIR" && "${DOCKER[@]}" compose logs --tail 100 -f)
}

backup_dir() { local d; d="$(get_env BACKUP_DIR)"; d="${d:-./backups}"; case "$d" in /*) printf '%s' "$d" ;; *) printf '%s' "$APP_DIR/${d#./}" ;; esac; }

ensure_age() {
  command -v age >/dev/null 2>&1 && return 0
  command -v apt-get >/dev/null 2>&1 || die "Bitte installiere das Programm „age“ und starte erneut."
  info "Installiere age …"
  as_root apt-get update -qq
  as_root apt-get install -y -qq age
}

apply_backup_env() { (cd "$APP_DIR" && "${DOCKER[@]}" compose up -d --build updater); }

cmd_backup_dir() {
  [ -n "${1:-}" ] || die "Bitte einen Ordner angeben, z. B.: ./install.sh backup-dir /mnt/nas/bodybase"
  require_install
  case "$1" in /*) ;; *) die "Bitte einen absoluten Pfad angeben (beginnt mit /)." ;; esac
  mkdir -p "$1" 2>/dev/null || die "Der Ordner $1 lässt sich nicht anlegen."
  local t="$1/.bodybase-test.$$"
  ( : > "$t" ) 2>/dev/null || die "In $1 kann nicht geschrieben werden. Bei NFS: Rechte der Freigabe und root_squash prüfen."
  rm -f "$t"
  set_env BACKUP_DIR "$1"
  apply_backup_env
  ok "Sicherungen landen jetzt in $1"
}

cmd_backup_key() {
  require_install
  ensure_age
  if [ -n "$(get_env BACKUP_AGE_RECIPIENT)" ]; then
    warn "Es gibt schon einen Schlüssel. Ein neuer macht künftige Sicherungen mit dem alten Schlüssel unlesbar für den neuen."
    read -r -p "Trotzdem neu erzeugen? „ja“ eingeben: " answer </dev/tty
    [ "$answer" = "ja" ] || die "Abgebrochen."
  fi
  local tmp; tmp="$(mktemp)"
  age-keygen -o "$tmp" 2>/dev/null
  local pub; pub="$(grep -o 'age1[0-9a-z]*' "$tmp" | head -n 1)"
  [ -n "$pub" ] || { rm -f "$tmp"; die "Der Schlüssel konnte nicht erzeugt werden."; }
  set_env BACKUP_AGE_RECIPIENT "$pub"
  apply_backup_env
  echo
  warn "Das ist der PRIVATE Schlüssel. Speichere ihn jetzt im Passwortmanager. Er wird nie wieder angezeigt und nirgends gespeichert."
  warn "Ohne ihn lassen sich die Sicherungen nicht zurückspielen."
  echo
  grep '^AGE-SECRET-KEY' "$tmp"
  echo
  shred -u "$tmp" 2>/dev/null || rm -f "$tmp"
  ok "Neue Sicherungen werden ab sofort verschlüsselt."
}

cmd_backup() {
  require_install
  local dir rcp f; dir="$(backup_dir)"; rcp="$(get_env BACKUP_AGE_RECIPIENT)"
  mkdir -p "$dir"
  f="$dir/bodybase-$(date +%Y%m%d-%H%M%S).sql.gz"
  if [ -n "$rcp" ]; then
    ensure_age
    f="$f.age"
    (cd "$APP_DIR" && "${DOCKER[@]}" compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip | age -r "$rcp" > "$f")
  else
    (cd "$APP_DIR" && "${DOCKER[@]}" compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$f")
  fi
  chmod 600 "$f" 2>/dev/null || true
  [ "$(stat -c %s "$f")" -gt 100 ] || { rm -f "$f"; die "Die Sicherung ist leer, bitte Protokolle prüfen."; }
  ok "Gesichert: $f$([ -n "$rcp" ] && echo ' (verschlüsselt)')"
}

cmd_restore() {
  [ -n "${1:-}" ] && [ -f "$1" ] || die "Bitte eine Sicherungsdatei angeben, z. B.: ./install.sh restore backups/bodybase-20261024-120000.sql.gz"
  require_install
  local file key; file="$(readlink -f "$1")"
  if [[ "$file" == *.age ]]; then
    ensure_age
    read -r -s -p "Privater Schlüssel (beginnt mit AGE-SECRET-KEY-): " key </dev/tty; echo
    [[ "$key" == AGE-SECRET-KEY-* ]] || die "Das ist kein privater Schlüssel."
    # vorab prüfen, damit bei falschem Schlüssel nichts gelöscht wird
    age -d -i <(printf '%s\n' "$key") "$file" 2>/dev/null | gunzip -t 2>/dev/null || die "Entschlüsseln fehlgeschlagen: falscher Schlüssel oder beschädigte Datei."
  fi
  warn "Das ersetzt ALLE aktuellen Daten durch den Stand der Sicherung."
  read -r -p "Zum Fortfahren „ja“ eingeben: " answer </dev/tty
  [ "$answer" = "ja" ] || die "Abgebrochen."
  (cd "$APP_DIR" && "${DOCKER[@]}" compose stop backend)
  (cd "$APP_DIR" && "${DOCKER[@]}" compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\"" -c "CREATE DATABASE \"$POSTGRES_DB\""')
  if [[ "$file" == *.age ]]; then
    age -d -i <(printf '%s\n' "$key") "$file" | gunzip | (cd "$APP_DIR" && "${DOCKER[@]}" compose exec -T db sh -c 'psql -q -U "$POSTGRES_USER" "$POSTGRES_DB"')
  else
    gunzip -c "$file" | (cd "$APP_DIR" && "${DOCKER[@]}" compose exec -T db sh -c 'psql -q -U "$POSTGRES_USER" "$POSTGRES_DB"')
  fi
  (cd "$APP_DIR" && "${DOCKER[@]}" compose start backend)
  ok "Sicherung zurückgespielt."
}

cmd_demo() {
  [ -n "${1:-}" ] || die "Bitte die E-Mail des Kontos angeben, z. B.: bodybase demo du@example.de"
  require_install
  (cd "$APP_DIR" && "${DOCKER[@]}" compose exec -T backend python -m app.cli demo-data "$1")
}

case "${1:-install}" in
  install)  cmd_install ;;
  update)   cmd_update ;;
  lock)     cmd_registration false ;;
  unlock)   cmd_registration true ;;
  url)      cmd_url "${2:-}" ;;
  backup)   cmd_backup ;;
  restore)  cmd_restore "${2:-}" ;;
  backup-dir) cmd_backup_dir "${2:-}" ;;
  backup-key) cmd_backup_key ;;
  logs)     cmd_logs ;;
  demo)     cmd_demo "${2:-}" ;;
  -h|--help|help) sed -n '2,30p' "${BASH_SOURCE[0]:-$0}" | sed 's/^# \{0,1\}//' ;;
  *) die "Unbekannter Befehl: $1 (erlaubt: install, update, lock, unlock, url, backup, restore, backup-dir, backup-key, logs, demo)" ;;
esac
