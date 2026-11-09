"""Update-Wächter: neue Versionen einmal per Push melden."""


def test_update_watch_pushes_each_version_once(client):
    from app import updatewatch
    from app.config import settings
    settings.ntfy_topic, settings.update_notify = "bb-test", True
    try:
        sent = []
        status = lambda: {"behind": 1, "changes": ["2026-11-09  Bump pyjwt from 2.15.0 to 2.15.1 in /backend (#3)"]}  # noqa: E731
        assert updatewatch.run_once(status, lambda t, b, p: sent.append((t, p)))
        assert not updatewatch.run_once(status, lambda t, b, p: sent.append((t, p)))
        assert sent == [("Sicherheitsupdate für BodyBase verfügbar", 4)]
        # ohne Thema nichts senden
        settings.ntfy_topic = ""
        assert not updatewatch.run_once(lambda: {"behind": 1, "changes": ["neu"]}, lambda *a: sent.append(a))
    finally:
        settings.ntfy_topic = ""



def test_push_options_are_saved():
    from app import server_settings
    from app.config import settings
    from app.database import SessionLocal
    with SessionLocal() as db:
        values = server_settings.save_options(db, {"ntfy_topic": " bb-abc ", "update_notify": False})
        assert values["ntfy_topic"] == "bb-abc" and values["update_notify"] is False
        server_settings.save_options(db, {"ntfy_topic": "", "update_notify": True})
    assert settings.update_notify is True
