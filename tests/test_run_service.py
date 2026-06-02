from datetime import date
from unittest.mock import Mock

from app.db import make_engine
from app.models import RiskAlert, RunRequest
from app.risk_logic import ComputeResult
from app.run_service import RunService
from app.slack import SlackDeliveryResult


def _alert(
    *,
    account_id: str = "a123",
    account_name: str = "Acme Corp",
    account_region: str | None = "AMER",
    channel: str | None = "amer-risk-alerts",
) -> RiskAlert:
    return RiskAlert(
        account_id=account_id,
        account_name=account_name,
        account_region=account_region,
        channel=channel,
        month=date(2026, 1, 1),
        duration_months=3,
        risk_start_month=date(2025, 11, 1),
        arr=250_000,
        renewal_date=None,
        account_owner="owner@example.com",
        details_url=f"https://app.yourcompany.com/accounts/{account_id}",
    )


def _request(*, dry_run: bool = False) -> RunRequest:
    return RunRequest(
        source_uri="file:///tmp/monthly_account_status.parquet",
        month=date(2026, 1, 1),
        dry_run=dry_run,
    )


def _compute_result(alerts: list[RiskAlert]) -> ComputeResult:
    return ComputeResult(
        alerts=alerts,
        rows_scanned=10,
        duplicate_rows=2,
    )


def _service(tmp_path) -> RunService:
    engine = make_engine(str(tmp_path / "test.db"))
    return RunService(engine=engine)


def test_dry_run_completes_without_sending_or_recording_outcomes(tmp_path, monkeypatch):
    service = _service(tmp_path)
    alert = _alert()

    monkeypatch.setattr(
        "app.run_service.compute_alerts",
        lambda **kwargs: _compute_result([alert]),
    )

    send_mock = Mock()
    monkeypatch.setattr("app.run_service.send_alert", send_mock)

    response = service.create_run(_request(dry_run=True))
    result = service.get_run(response.run_id)

    assert result.status == "succeeded"
    assert result.counts.rows_scanned == 10
    assert result.counts.duplicate_rows == 2
    assert result.counts.alerts_sent == 0
    assert result.counts.failed_deliveries == 0
    assert result.counts.skipped_replay == 0
    assert result.sample_alerts == []
    assert result.sample_errors == []

    send_mock.assert_not_called()


def test_unknown_region_records_failed_outcome_and_notifies_support(tmp_path, monkeypatch):
    service = _service(tmp_path)
    alert = _alert(account_region=None, channel=None)

    monkeypatch.setattr(
        "app.run_service.compute_alerts",
        lambda **kwargs: _compute_result([alert]),
    )

    send_mock = Mock()
    monkeypatch.setattr("app.run_service.send_alert", send_mock)

    support_mock = Mock()
    monkeypatch.setattr("app.run_service.send_support_notification", support_mock)

    response = service.create_run(_request())
    result = service.get_run(response.run_id)

    assert result.status == "succeeded"
    assert result.counts.alerts_sent == 0
    assert result.counts.failed_deliveries == 1
    assert result.counts.skipped_replay == 0

    assert len(result.sample_errors) == 1
    assert result.sample_errors[0].status == "failed"
    assert result.sample_errors[0].error == "unknown_region"
    assert result.sample_errors[0].account_region is None

    send_mock.assert_not_called()
    support_mock.assert_called_once_with([alert])


def test_successful_slack_send_records_sent_outcome(tmp_path, monkeypatch):
    service = _service(tmp_path)
    alert = _alert()

    monkeypatch.setattr(
        "app.run_service.compute_alerts",
        lambda **kwargs: _compute_result([alert]),
    )

    send_mock = Mock(return_value=SlackDeliveryResult(ok=True, status_code=200, attempts=1))
    monkeypatch.setattr("app.run_service.send_alert", send_mock)

    response = service.create_run(_request())
    result = service.get_run(response.run_id)

    assert result.status == "succeeded"
    assert result.counts.alerts_sent == 1
    assert result.counts.failed_deliveries == 0
    assert result.counts.skipped_replay == 0

    assert len(result.sample_alerts) == 1
    assert result.sample_alerts[0].account_id == alert.account_id
    assert result.sample_errors == []

    send_mock.assert_called_once()


def test_slack_failure_records_failed_outcome_but_run_succeeds(tmp_path, monkeypatch):
    service = _service(tmp_path)
    alert = _alert()

    monkeypatch.setattr(
        "app.run_service.compute_alerts",
        lambda **kwargs: _compute_result([alert]),
    )

    send_mock = Mock(
        return_value=SlackDeliveryResult(
            ok=False,
            status_code=500,
            error="HTTP 500",
            attempts=3,
        )
    )
    monkeypatch.setattr("app.run_service.send_alert", send_mock)

    response = service.create_run(_request())
    result = service.get_run(response.run_id)

    assert result.status == "succeeded"
    assert result.counts.alerts_sent == 0
    assert result.counts.failed_deliveries == 1
    assert result.counts.skipped_replay == 0

    assert result.sample_alerts == []
    assert len(result.sample_errors) == 1
    assert result.sample_errors[0].status == "failed"
    assert result.sample_errors[0].error == "HTTP 500"

    send_mock.assert_called_once()


def test_replay_skips_previously_sent_alert(tmp_path, monkeypatch):
    service = _service(tmp_path)
    alert = _alert()

    monkeypatch.setattr(
        "app.run_service.compute_alerts",
        lambda **kwargs: _compute_result([alert]),
    )

    send_mock = Mock(return_value=SlackDeliveryResult(ok=True, status_code=200, attempts=1))
    monkeypatch.setattr("app.run_service.send_alert", send_mock)

    first_response = service.create_run(_request())
    first_result = service.get_run(first_response.run_id)

    assert first_result.counts.alerts_sent == 1
    assert first_result.counts.skipped_replay == 0

    second_response = service.create_run(_request())
    second_result = service.get_run(second_response.run_id)

    assert second_result.status == "succeeded"
    assert second_result.counts.alerts_sent == 0
    assert second_result.counts.skipped_replay == 1
    assert second_result.counts.failed_deliveries == 0

    # It should call only on the first run
    assert send_mock.call_count == 1