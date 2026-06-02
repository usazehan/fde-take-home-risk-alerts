"""
app/support.py

Aggregated support notification for At Risk accounts that cannot be routed
to Slack because their region is missing or unknown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from collections.abc import Sequence

from .models import RiskAlert

logger = logging.getLogger(__name__)

DEFAULT_SUPPORT_EMAIL = "support@quadsci.ai"


@dataclass(frozen=True)
class SupportNotificationResult:
    sent: bool
    recipient: str
    account_count: int
    message: str


def send_support_notification(
    alerts: Sequence[RiskAlert],
    *,
    recipient: str = DEFAULT_SUPPORT_EMAIL,
) -> SupportNotificationResult:
    """
    Send one aggregated support notification for unknown-region alerts.

    For this assignment, this logs the notification instead of sending real email.
    The function still returns a result so run_service.py can call it like a real
    integration and keep the behavior easy to replace later.
    """
    unknown_region_alerts = [alert for alert in alerts if alert.channel is None]

    if not unknown_region_alerts:
        return SupportNotificationResult(
            sent=False,
            recipient=recipient,
            account_count=0,
            message="No unknown-region alerts to notify support about.",
        )

    message = build_support_message(unknown_region_alerts)

    logger.warning(
        "Support notification would be sent to %s for %s unknown-region account(s):\n%s",
        recipient,
        len(unknown_region_alerts),
        message,
    )

    return SupportNotificationResult(
        sent=True,
        recipient=recipient,
        account_count=len(unknown_region_alerts),
        message=message,
    )


def build_support_message(alerts: Sequence[RiskAlert]) -> str:
    lines = [
        "Unknown-region At Risk accounts require manual routing.",
        "",
        "These accounts were not sent to Slack because no channel could be resolved.",
        "",
    ]

    for alert in alerts:
        lines.extend(
            [
                f"- {alert.account_name} ({alert.account_id})",
                f"  Region: {_display(alert.account_region)}",
                f"  Month: {alert.month.isoformat()}",
                f"  At Risk for: {alert.duration_months} month(s) since {alert.risk_start_month.isoformat()}",
                f"  ARR: {_format_arr(alert.arr)}",
                f"  Renewal date: {_display_date(alert.renewal_date)}",
                f"  Owner: {_display(alert.account_owner)}",
                f"  Details URL: {alert.details_url}",
                "",
            ]
        )

    return "\n".join(lines).rstrip()

def _format_arr(arr: int | None) -> str:
    if arr is None:
        return "Unknown"

    return f"${arr:,.0f}"

def _display_date(value) -> str:
    if value is None:
        return "Unknown"

    return value.isoformat()

def _display(value: str | None) -> str:
    if value is None or value.strip() == "":
        return "Unknown"

    return value