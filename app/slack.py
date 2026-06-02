"""
app/slack.py

Slack delivery for At Risk account alerts.

Responsibilities:
  - Build the Slack webhook URL from config (base-URL mode preferred; single-webhook fallback).
  - Format a RiskAlert into a Slack message payload.
  - POST it, retrying transient failures (HTTP 429 and 5xx) with exponential backoff,
    honouring Retry-After when present.
  - Return a result (sent/failed + error) so the run can complete even when some
    sends fail. Delivery failures are returned.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import requests

from .config import AppConfig
from .models import RiskAlert

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 1.0

# (connect, read) timeout per attempt.
_TIMEOUT = (5, 10)

# Retry rate-limit + transient server errors only.
_RETRYABLE = {429, 500, 502, 503, 504}


class SlackConfigError(Exception):
    """Raised for configuration mistakes (no webhook configured) — not delivery failures."""


@dataclass(frozen=True)
class SlackDeliveryResult:
    ok: bool
    status_code: Optional[int] = None
    error: Optional[str] = None
    attempts: int = 0


def send_alert(
    alert: RiskAlert,
    config: AppConfig,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    sleep=time.sleep,
) -> SlackDeliveryResult:
    """Send one RiskAlert to its channel, retrying transient failures.

    Returns SlackDeliveryResult(ok=True) on a 2xx, or (ok=False, error=...) after
    exhausting retries or on a non-retryable status. Never raises on delivery failure
    so one bad send doesn't abort a run. `sleep` is injectable for tests.
    """
    if not alert.channel:
        # Defensive: unknown_region alerts shouldn't reach here.
        return SlackDeliveryResult(ok=False, error="unknown_region", attempts=0)

    url = build_webhook_url(alert.channel, config)
    payload = build_slack_payload(alert)

    last_status: Optional[int] = None
    last_error: Optional[str] = None
    attempts = 0

    for attempt in range(max_attempts):
        attempts = attempt + 1
        try:
            resp = requests.post(url, json=payload, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            last_status, last_error = None, f"request error: {exc}"
            if attempt < max_attempts - 1:
                sleep(_backoff(attempt, backoff_seconds, None))
                continue
            break

        if 200 <= resp.status_code < 300:
            return SlackDeliveryResult(ok=True, status_code=resp.status_code, attempts=attempts)

        last_status = resp.status_code
        last_error = f"HTTP {resp.status_code}"

        if resp.status_code in _RETRYABLE and attempt < max_attempts - 1:
            sleep(_backoff(attempt, backoff_seconds, resp.headers.get("Retry-After")))
            continue

        # Non-retryable (e.g. 400/401/403) or retries exhausted.
        break

    return SlackDeliveryResult(
        ok=False, status_code=last_status, error=last_error, attempts=attempts
    )


def build_webhook_url(channel: str, config: AppConfig) -> str:
    """Build the POST URL. SLACK_WEBHOOK_BASE_URL takes precedence; then SLACK_WEBHOOK_URL.

    Base-URL mode posts to {SLACK_WEBHOOK_BASE_URL}/{channel} (matches the mock server's
    /slack/webhook/{channel}). Single-webhook mode posts to SLACK_WEBHOOK_URL.
    """
    if config.slack_webhook_base_url:
        return f"{config.slack_webhook_base_url.rstrip('/')}/{channel}"
    if config.slack_webhook_url:
        return config.slack_webhook_url
    raise SlackConfigError(
        "Slack webhook not configured: set SLACK_WEBHOOK_BASE_URL or SLACK_WEBHOOK_URL."
    )


def build_slack_payload(alert: RiskAlert) -> dict[str, Any]:
    """Build the Slack JSON payload.

    `text` is the human-readable message (spec format). The structured fields are
    included too — harmless for real webhooks and useful for inspecting the mock's logs.
    """
    parts = [
        f"🚩 At Risk: {alert.account_name} ({alert.account_id})",
        f"Region: {_display(alert.account_region)}",
        f"At Risk for: {alert.duration_months} {_month_label(alert.duration_months)} "
            f"(since {alert.risk_start_month.isoformat()})",
        f"ARR: {_format_arr(alert.arr)}",
        f"Renewal date: {_format_date(alert.renewal_date)}",
    ]
    if alert.account_owner:
        parts.append(f"Owner: {alert.account_owner}")
    parts.append(f"Details URL: {alert.details_url}")

    return {
        "text": "\n".join(parts),
        "account_id": alert.account_id,
        "account_name": alert.account_name,
        "account_region": alert.account_region,
        "channel": alert.channel,
        "month": alert.month.isoformat(),
        "duration_months": alert.duration_months,
        "risk_start_month": alert.risk_start_month.isoformat(),
        "arr": alert.arr,
        "renewal_date": alert.renewal_date.isoformat() if alert.renewal_date else None,
        "account_owner": alert.account_owner,
        "details_url": alert.details_url,
    }


def _backoff(attempt: int, base: float, retry_after: Optional[str]) -> float:
    """Delay before next attempt: honour Retry-After (seconds) if present, else base * 2**attempt."""
    if retry_after:
        try:
            value = float(retry_after)
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    return base * (2 ** attempt)

def _month_label(duration_months: int) -> str:
    return "month" if duration_months == 1 else "months"

def _format_arr(arr: Optional[int]) -> str:
    return f"${arr:,.0f}" if arr is not None else "Unknown"

def _format_date(value: Optional[date]) -> str:
    return value.isoformat() if value is not None else "Unknown"

def _display(value: Optional[str]) -> str:
    if value is None or value.strip() == "":
        return "Unknown"
    return value