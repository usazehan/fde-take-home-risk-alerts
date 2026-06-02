"""
app/run_service.py

Orchestration layer for POST /runs and GET /runs/{run_id}.

This module wires together:
  - risk_logic.compute_alerts
  - db run/outcome persistence
  - slack delivery
  - support notification for unknown-region alerts
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.engine import Engine

from .config import get_config
from .db import (
    complete_run,
    create_run,
    get_run_result,
    make_engine,
    record_alert_outcome,
    was_already_sent,
)
from .models import RunCounts, RunRequest, RunResponse, RunResultResponse
from .risk_logic import compute_alerts
from .slack import SlackConfigError, send_alert
from .support import send_support_notification


@dataclass(frozen=True)
class RunService:
    engine: Engine

    def create_run(self, request: RunRequest) -> RunResponse:
        """
        Execute one alert batch and persist the run result.

        dry_run behavior:
          - compute alerts
          - create/complete a run row
          - do NOT send Slack
          - do NOT record alert_outcomes
          - do NOT send support notification

        This keeps dry_run side-effect free with respect to the delivery ledger.
        """
        config = get_config()

        run_id = create_run(
            self.engine,
            source_uri=request.source_uri,
            month=request.month,
            dry_run=request.dry_run,
        )

        counts = RunCounts()

        try:
            result = compute_alerts(
                source_uri=request.source_uri,
                target_month=request.month,
                config=config,
            )

            counts.rows_scanned = result.rows_scanned
            counts.duplicate_rows = result.duplicate_rows

            if request.dry_run:
                complete_run(
                    self.engine,
                    run_id=run_id,
                    status="succeeded",
                    counts=counts,
                )
                return RunResponse(run_id=run_id)

            unknown_region_alerts = []

            for alert in result.alerts:
                if was_already_sent(self.engine, alert):
                    counts.skipped_replay += 1
                    continue

                if alert.channel is None:
                    counts.failed_deliveries += 1
                    unknown_region_alerts.append(alert)

                    record_alert_outcome(
                        self.engine,
                        run_id=run_id,
                        alert=alert,
                        status="failed",
                        error="unknown_region",
                    )
                    continue

                try:
                    delivery = send_alert(alert, config)
                except SlackConfigError as exc:
                    counts.failed_deliveries += 1
                    record_alert_outcome(
                        self.engine,
                        run_id=run_id,
                        alert=alert,
                        status="failed",
                        error=str(exc),
                    )
                    continue

                if delivery.ok:
                    counts.alerts_sent += 1
                    record_alert_outcome(
                        self.engine,
                        run_id=run_id,
                        alert=alert,
                        status="sent",
                    )
                else:
                    counts.failed_deliveries += 1
                    record_alert_outcome(
                        self.engine,
                        run_id=run_id,
                        alert=alert,
                        status="failed",
                        error=delivery.error,
                    )

            if unknown_region_alerts:
                send_support_notification(unknown_region_alerts)

            complete_run(
                self.engine,
                run_id=run_id,
                status="succeeded",
                counts=counts,
            )

            return RunResponse(run_id=run_id)

        except Exception:
            complete_run(
                self.engine,
                run_id=run_id,
                status="failed",
                counts=counts,
            )
            raise

    def get_run(self, run_id: str) -> RunResultResponse:
        result = get_run_result(self.engine, run_id)

        if result is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        return result