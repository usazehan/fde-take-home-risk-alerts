import pytest

from app.config import DEFAULT_ARR_THRESHOLD, get_config


@pytest.fixture(autouse=True)
def clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def test_get_config_uses_defaults():
    config = get_config()

    assert config.arr_threshold == DEFAULT_ARR_THRESHOLD
    assert config.sqlite_db_path == "risk_alerts.db"
    assert config.details_base_url == "https://app.yourcompany.com"


def test_arr_threshold_from_env(monkeypatch):
    monkeypatch.setenv("ARR_THRESHOLD", "50000")

    config = get_config()

    assert config.arr_threshold == 50_000


def test_sqlite_db_path_from_env(monkeypatch):
    monkeypatch.setenv("SQLITE_DB_PATH", "tmp/test.db")

    config = get_config()

    assert config.sqlite_db_path == "tmp/test.db"


def test_slack_webhook_base_url_from_env(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_BASE_URL", "http://localhost:9000/slack/webhook")

    config = get_config()

    assert config.slack_webhook_base_url == "http://localhost:9000/slack/webhook"


def test_channel_for_known_region():
    config = get_config()

    assert config.channel_for_region("AMER") == "amer-risk-alerts"
    assert config.channel_for_region("emea") == "emea-risk-alerts"
    assert config.channel_for_region(" APAC ") == "apac-risk-alerts"


def test_channel_for_unknown_or_missing_region():
    config = get_config()

    assert config.channel_for_region(None) is None
    assert config.channel_for_region("") is None
    assert config.channel_for_region("LATAM") is None


def test_details_url_for_account():
    config = get_config()

    assert (
        config.details_url_for_account("a123")
        == "https://app.yourcompany.com/accounts/a123"
    )


def test_details_url_uses_env_base_url(monkeypatch):
    monkeypatch.setenv("DETAILS_BASE_URL", "https://example.com/")

    config = get_config()

    assert config.details_url_for_account("a123") == "https://example.com/accounts/a123"