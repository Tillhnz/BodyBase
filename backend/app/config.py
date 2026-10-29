from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./bodybase.db"
    secret_key: str = "dev-secret-change-me"
    public_url: str = "http://localhost:8080"
    allow_registration: bool = False  # nur das erste Konto und Eingeladene dürfen sich registrieren
    trusted_proxies: int = 0  # Proxys vor dem Webserver (Nginx Proxy Manager = 1), für die Login-Drosselung
    token_expire_days: int = 30
    cookie_samesite: str = "strict"
    frame_ancestors: str = ""  # Adressen, die BodyBase einbetten dürfen (z. B. Home Assistant)
    updater_url: str = ""  # leer = kein Update-Dienst
    timezone: str = "Europe/Berlin"
    background_jobs: bool = True  # Abgleich mit den Anbietern im Hintergrund (in Tests aus)
    sync_interval_minutes: int = 60  # wie oft jede Verbindung abgeglichen wird
    backfill_days: int = 90  # so weit zurück holt die erste Synchronisierung Daten
    max_upload_mb: int = 4096  # Apple-Health-Export kann mehrere GB groß sein
    data_dir: str = "/data"


settings = Settings()
