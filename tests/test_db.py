from datetime import date

from app.db import (
    complete_run,
    create_run,
    get_existing_outcome,
    get_run_result,
    make_engine,
    record_alert_outcome,
    was_already_sent,
)
from app.models import RiskAlert, RunCounts


def _alert() -> RiskAlert:
    return RiskAlert(
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
        details_url="https://app.yourcompany.com/accounts/a123",
    )


def test_create_and_complete_run(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))

    run_id = create_run(
        engine,
        source_uri="file:///tmp/monthly_account_status.parquet",
        month=date(2026, 1, 1),
        dry_run=False,
    )

    complete_run(
        engine,
        run_id=run_id,
        status="succeeded",
        counts=RunCounts(
            rows_scanned=100,
            alerts_sent=1,
            skipped_replay=0,
            failed_deliveries=0,
            duplicate_rows=2,
        ),
    )

    result = get_run_result(engine, run_id)

    assert result is not None
    assert result.run_id == run_id
    assert result.status == "succeeded"
    assert result.counts.rows_scanned == 100
    assert result.counts.alerts_sent == 1
    assert result.counts.duplicate_rows == 2


def test_record_sent_outcome_and_detect_replay(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    alert = _alert()

    run_id = create_run(
        engine,
        source_uri="file:///tmp/monthly_account_status.parquet",
        month=alert.month,
        dry_run=False,
    )

    record_alert_outcome(
        engine,
        run_id=run_id,
        alert=alert,
        status="sent",
    )

    existing = get_existing_outcome(
        engine,
        account_id=alert.account_id,
        month=alert.month,
    )

    assert existing is not None
    assert existing.status == "sent"
    assert was_already_sent(engine, alert) is True


def test_existing_sent_outcome_is_not_overwritten(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    alert = _alert()

    first_run_id = create_run(
        engine,
        source_uri="file:///tmp/monthly_account_status.parquet",
        month=alert.month,
        dry_run=False,
    )

    record_alert_outcome(
        engine,
        run_id=first_run_id,
        alert=alert,
        status="sent",
    )

    second_run_id = create_run(
        engine,
        source_uri="file:///tmp/monthly_account_status.parquet",
        month=alert.month,
        dry_run=False,
    )

    record_alert_outcome(
        engine,
        run_id=second_run_id,
        alert=alert,
        status="failed",
        error="should_not_overwrite_sent",
    )

    existing = get_existing_outcome(
        engine,
        account_id=alert.account_id,
        month=alert.month,
    )

    assert existing is not None
    assert existing.status == "sent"
    assert existing.error is None


def test_failed_outcome_can_be_overwritten_on_retry(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    alert = _alert()

    first_run_id = create_run(
        engine,
        source_uri="file:///tmp/monthly_account_status.parquet",
        month=alert.month,
        dry_run=False,
    )

    record_alert_outcome(
        engine,
        run_id=first_run_id,
        alert=alert,
        status="failed",
        error="HTTP 500",
    )

    second_run_id = create_run(
        engine,
        source_uri="file:///tmp/monthly_account_status.parquet",
        month=alert.month,
        dry_run=False,
    )

    record_alert_outcome(
        engine,
        run_id=second_run_id,
        alert=alert,
        status="sent",
    )

    existing = get_existing_outcome(
        engine,
        account_id=alert.account_id,
        month=alert.month,
    )

    assert existing is not None
    assert existing.status == "sent"
    assert existing.error is None