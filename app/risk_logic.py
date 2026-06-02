from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pyarrow.dataset as ds

from .config import AppConfig
from .models import RiskAlert
from .storage import read_table

AT_RISK = "At Risk"

# Columns the logic needs from the source dataset
_COLUMNS = [
    "account_id",
    "account_name",
    "account_region",
    "month",
    "status",
    "renewal_date",
    "account_owner",
    "arr",
    "updated_at",
]


@dataclass(frozen=True)
class ComputeResult:
    alerts: list[RiskAlert]
    rows_scanned: int
    duplicate_rows: int


def compute_alerts(
    source_uri: str,
    target_month: date,
    config: AppConfig,
) -> ComputeResult:
    """Compute at risk alerts for the target month"""
    if target_month.day != 1:
        raise ValueError("target_month must be the first day of the month")

    table = read_table(
        source_uri,
        columns=_COLUMNS,
        filter_expression=ds.field("month") <= target_month,
    )
    rows: list[dict[str, Any]] = table.to_pylist()
    rows_scanned = len(rows)

    latest, duplicate_rows = _dedupe_latest(rows)

    status_by_account: dict[str, dict[date, str]] = {}
    for (account_id, month), row in latest.items():
        status_by_account.setdefault(account_id, {})[month] = row.get("status")

    alerts: list[RiskAlert] = []

    for (account_id, month), row in latest.items():
        if month != target_month:
            continue

        if not _is_at_risk(row.get("status")):
            continue

        arr = row.get("arr")
        if arr is not None and arr < config.arr_threshold:
            continue

        duration, risk_start = _duration_and_start(
            target_month=target_month,
            status_by_month=status_by_account[account_id],
        )

        region = _optional_str(row.get("account_region"))
        channel = config.channel_for_region(region)

        alerts.append(
            RiskAlert(
                account_id=account_id,
                account_name=row["account_name"],
                account_region=region,
                channel=channel,
                month=target_month,
                duration_months=duration,
                risk_start_month=risk_start,
                arr=arr,
                renewal_date=row.get("renewal_date"),
                account_owner=_optional_str(row.get("account_owner")),
                details_url=config.details_url_for_account(account_id),
            )
        )

    # Unknown-region first, then longest duration, then stable account_id ordering.
    alerts.sort(key=lambda alert: (alert.channel is not None, -alert.duration_months, alert.account_id))

    return ComputeResult(
        alerts=alerts,
        rows_scanned=rows_scanned,
        duplicate_rows=duplicate_rows,
    )


def _dedupe_latest(rows: list[dict[str, Any]]) -> tuple[dict[tuple[str, date], dict[str, Any]], int]:
    """
    Collapse duplicate (account_id, month) rows, keeping the latest updated_at

    duplicate_rows is the number of rows dropped as duplicates
    """
    latest: dict[tuple[str, date], dict[str, Any]] = {}
    duplicates = 0

    for row in rows:
        account_id = row.get("account_id")
        month = row.get("month")

        if account_id is None or month is None:
            continue

        key = (str(account_id), month)
        existing = latest.get(key)

        if existing is None:
            latest[key] = row
            continue

        duplicates += 1

        if row["updated_at"] > existing["updated_at"]:
            latest[key] = row

    return latest, duplicates


def _duration_and_start(
    target_month: date,
    status_by_month: dict[date, str],
) -> tuple[int, date]:
    """
    Count consecutive at risk months ending at target_month.

    Stops when the previous calendar month is missing or no longer at risk
    """
    duration = 1
    start = target_month
    cursor = _previous_month(target_month)

    while _is_at_risk(status_by_month.get(cursor)):
        duration += 1
        start = cursor
        cursor = _previous_month(cursor)

    return duration, start


def _previous_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)

    return date(value.year, value.month - 1, 1)


def _is_at_risk(status: object) -> bool:
    if status is None:
        return False

    return str(status).strip().lower() == AT_RISK.lower()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    return cleaned or None