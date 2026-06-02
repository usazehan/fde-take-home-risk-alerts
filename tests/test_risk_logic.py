from datetime import date, datetime

import pyarrow as pa
import pyarrow.parquet as pq

from app.config import AppConfig
from app.risk_logic import compute_alerts


_SCHEMA = pa.schema(
    [
        ("account_id", pa.string()),
        ("account_name", pa.string()),
        ("account_region", pa.string()),
        ("month", pa.date32()),
        ("status", pa.string()),
        ("renewal_date", pa.date32()),
        ("account_owner", pa.string()),
        ("arr", pa.int64()),
        ("updated_at", pa.timestamp("us")),
    ]
)


def _row(
    *,
    account_id: str,
    month: date,
    status: str,
    updated_at: datetime,
    account_name: str | None = None,
    account_region: str | None = "AMER",
    renewal_date: date | None = None,
    account_owner: str | None = "owner@example.com",
    arr: int | None = 50_000,
) -> dict:
    return {
        "account_id": account_id,
        "account_name": account_name or f"Account {account_id}",
        "account_region": account_region,
        "month": month,
        "status": status,
        "renewal_date": renewal_date,
        "account_owner": account_owner,
        "arr": arr,
        "updated_at": updated_at,
    }


def _write_parquet(tmp_path, rows: list[dict]) -> str:
    path = tmp_path / "monthly_account_status.parquet"
    table = pa.Table.from_pylist(rows, schema=_SCHEMA)
    pq.write_table(table, path)
    return f"file://{path}"


def _config(arr_threshold: int = 25_000) -> AppConfig:
    return AppConfig(
        arr_threshold=arr_threshold,
        details_base_url="https://app.yourcompany.com",
    )


def test_computes_duration_and_routes_channel(tmp_path):
    source_uri = _write_parquet(
        tmp_path,
        [
            _row(
                account_id="a123",
                month=date(2025, 11, 1),
                status="At Risk",
                updated_at=datetime(2025, 11, 2, 12),
            ),
            _row(
                account_id="a123",
                month=date(2025, 12, 1),
                status="At Risk",
                updated_at=datetime(2025, 12, 2, 12),
            ),
            _row(
                account_id="a123",
                month=date(2026, 1, 1),
                status="At Risk",
                updated_at=datetime(2026, 1, 2, 12),
                account_region="AMER",
                arr=100_000,
            ),
        ],
    )

    result = compute_alerts(
        source_uri=source_uri,
        target_month=date(2026, 1, 1),
        config=_config(),
    )

    assert result.rows_scanned == 3
    assert result.duplicate_rows == 0
    assert len(result.alerts) == 1

    alert = result.alerts[0]
    assert alert.account_id == "a123"
    assert alert.channel == "amer-risk-alerts"
    assert alert.duration_months == 3
    assert alert.risk_start_month == date(2025, 11, 1)
    assert alert.details_url == "https://app.yourcompany.com/accounts/a123"


def test_missing_month_stops_duration(tmp_path):
    source_uri = _write_parquet(
        tmp_path,
        [
            _row(
                account_id="a123",
                month=date(2025, 11, 1),
                status="At Risk",
                updated_at=datetime(2025, 11, 2, 12),
            ),
            # December is intentionally missing.
            _row(
                account_id="a123",
                month=date(2026, 1, 1),
                status="At Risk",
                updated_at=datetime(2026, 1, 2, 12),
            ),
        ],
    )

    result = compute_alerts(
        source_uri=source_uri,
        target_month=date(2026, 1, 1),
        config=_config(),
    )

    assert len(result.alerts) == 1
    assert result.alerts[0].duration_months == 1
    assert result.alerts[0].risk_start_month == date(2026, 1, 1)


def test_latest_updated_at_wins_and_duplicate_rows_reported(tmp_path):
    source_uri = _write_parquet(
        tmp_path,
        [
            _row(
                account_id="a123",
                month=date(2026, 1, 1),
                status="At Risk",
                updated_at=datetime(2026, 1, 2, 12),
            ),
            _row(
                account_id="a123",
                month=date(2026, 1, 1),
                status="Healthy",
                updated_at=datetime(2026, 1, 3, 12),
            ),
        ],
    )

    result = compute_alerts(
        source_uri=source_uri,
        target_month=date(2026, 1, 1),
        config=_config(),
    )

    assert result.duplicate_rows == 1
    assert result.alerts == []


def test_arr_threshold_filters_low_arr_but_allows_missing_arr(tmp_path):
    source_uri = _write_parquet(
        tmp_path,
        [
            _row(
                account_id="low_arr",
                month=date(2026, 1, 1),
                status="At Risk",
                updated_at=datetime(2026, 1, 2, 12),
                arr=24_999,
            ),
            _row(
                account_id="missing_arr",
                month=date(2026, 1, 1),
                status="At Risk",
                updated_at=datetime(2026, 1, 2, 12),
                arr=None,
            ),
        ],
    )

    result = compute_alerts(
        source_uri=source_uri,
        target_month=date(2026, 1, 1),
        config=_config(arr_threshold=25_000),
    )

    assert [alert.account_id for alert in result.alerts] == ["missing_arr"]
    assert result.alerts[0].arr is None


def test_unknown_region_alert_is_included_with_no_channel(tmp_path):
    source_uri = _write_parquet(
        tmp_path,
        [
            _row(
                account_id="a123",
                month=date(2026, 1, 1),
                status="At Risk",
                updated_at=datetime(2026, 1, 2, 12),
                account_region=None,
            ),
        ],
    )

    result = compute_alerts(
        source_uri=source_uri,
        target_month=date(2026, 1, 1),
        config=_config(),
    )

    assert len(result.alerts) == 1
    assert result.alerts[0].account_region is None
    assert result.alerts[0].channel is None