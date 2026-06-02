from datetime import date

from app.models import RiskAlert
from app.slack import build_slack_payload, build_webhook_url
from app.config import AppConfig


def test_build_webhook_url_prefers_base_url():
    config = AppConfig(
        slack_webhook_base_url="http://localhost:9000/slack/webhook",
        slack_webhook_url="https://hooks.slack.com/real-webhook",
    )

    url = build_webhook_url("amer-risk-alerts", config)

    assert url == "http://localhost:9000/slack/webhook/amer-risk-alerts"


def test_build_slack_payload_matches_required_format():
    alert = RiskAlert(
        account_id="a123",
        account_name="Acme Corp",
        account_region="AMER",
        channel="amer-risk-alerts",
        month=date(2026, 1, 1),
        duration_months=3,
        risk_start_month=date(2025, 11, 1),
        arr=250000,
        renewal_date=None,
        account_owner="owner@example.com",
        details_url="https://app.quadsci.ai/accounts/a123",
    )

    payload = build_slack_payload(alert)
    text = payload["text"]

    assert "🚩 At Risk: Acme Corp (a123)" in text
    assert "Region: AMER" in text
    assert "At Risk for: 3 months (since 2025-11-01)" in text
    assert "ARR: $250,000" in text
    assert "Renewal date: Unknown" in text
    assert "Owner: owner@example.com" in text
    assert "Details URL: https://app.quadsci.ai/accounts/a123" in text