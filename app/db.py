"""
app/db.py

Two tables:
  runs            
    - one row per run
    - two-phase lifecycle (running -> succeeded/failed)
  alert_outcomes  
    - durable cross-run per-alert ledger
    - UNIQUE(account_id, month, alert_type) which enforces replay safety

Replay safety:
    - If an alert was already sent, callers should skip Slack and increment
    skipped_replay in RunCounts.
    - record_alert_outcome() also protects previously sent rows at the DB layer.
    - Previously failed outcomes can be retried and overwritten.

Lifecycle:
  create_run inserts a 'running' row first (so alert_outcomes.run_id can FK to it),
  outcomes are recorded during the run, then complete_run sets the final status and
  counts. alert_json stores the computed RiskAlert so GET /runs/{id} can rehydrate
  the full alert for sample_alerts without re-scanning the parquet.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    event,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from .models import AlertOutcome, AlertStatus, AlertType, RiskAlert, RunCounts, RunResultResponse

DEFAULT_ALERT_TYPE: AlertType = "at_risk"

metadata = MetaData()

runs = Table(
    "runs",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("source_uri", String, nullable=False),
    Column("month", Date, nullable=False),
    Column("dry_run", Integer, nullable=False, default=0),  
    Column("status", String, nullable=False),               # running | succeeded | failed
    Column("rows_scanned", Integer, nullable=False, default=0),
    Column("alerts_sent", Integer, nullable=False, default=0),
    Column("skipped_replay", Integer, nullable=False, default=0),
    Column("failed_deliveries", Integer, nullable=False, default=0),
    Column("duplicate_rows", Integer, nullable=False, default=0),
    Column("created_at", DateTime, nullable=False),
    Column("completed_at", DateTime, nullable=True),
)

alert_outcomes = Table(
    "alert_outcomes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False),
    Column("account_id", String, nullable=False),
    Column("account_name", String, nullable=False),
    Column("account_region", String, nullable=True),
    Column("month", Date, nullable=False),
    Column("channel", String, nullable=True),
    Column("alert_type", String, nullable=False),
    Column("status", String, nullable=False),               # sent | skipped_replay | failed
    Column("sent_at", DateTime, nullable=True),
    Column("error", String, nullable=True),
    Column("alert_json", String, nullable=False),           # RiskAlert JSON, for rehydration
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    UniqueConstraint("account_id", "month", "alert_type", name="uq_alert_identity"),
)


def make_engine(db_path: str) -> Engine:
    """Create an Engine for a SQLite file, enable FK enforcement, ensure tables exist."""
    parent = Path(db_path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{db_path}", future=True)

    # SQLite ignores foreign keys unless this PRAGMA is set per connection.
    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):  # pragma: no cover 
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    metadata.create_all(engine)
    return engine


# ---- runs 


def create_run(
    engine: Engine, *, source_uri: str, month: date, dry_run: bool
) -> str:
    """Insert a 'running' run row and return its id (called at the start of a POST /runs)."""
    run_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            runs.insert().values(
                run_id=run_id,
                source_uri=source_uri,
                month=month,
                dry_run=1 if dry_run else 0,
                status="running",
                created_at=_utc_now(),
            )
        )
    return run_id


def complete_run(
    engine: Engine, *, run_id: str, status: str, counts: RunCounts
) -> None:
    """Set the final status and counts on a POST /runs (called once at the end)."""
    if status not in ("succeeded", "failed"):
        raise ValueError(f"Invalid run status: {status}")
    with engine.begin() as conn:
        result = conn.execute(
            update(runs)
            .where(runs.c.run_id == run_id)
            .values(
                status=status,
                rows_scanned=counts.rows_scanned,
                alerts_sent=counts.alerts_sent,
                skipped_replay=counts.skipped_replay,
                failed_deliveries=counts.failed_deliveries,
                duplicate_rows=counts.duplicate_rows,
                completed_at=_utc_now(),
            )
        )
        if result.rowcount == 0:
            raise ValueError(f"Run not found: {run_id}")


# ---- alert outcomes 


def get_existing_outcome(
    engine: Engine,
    *,
    account_id: str,
    month: date,
    alert_type: AlertType = DEFAULT_ALERT_TYPE,
) -> Optional[AlertOutcome]:
    """Idempotency lookup by the unique key (account_id, month, alert_type)"""
    with engine.begin() as conn:
        row = (
            conn.execute(
                select(alert_outcomes).where(
                    alert_outcomes.c.account_id == account_id,
                    alert_outcomes.c.month == month,
                    alert_outcomes.c.alert_type == alert_type,
                )
            )
            .mappings()
            .first()
        )
    return _row_to_outcome(row) if row else None


def was_already_sent(engine: Engine, alert: RiskAlert) -> bool:
    """True if this alert key already has a 'sent' outcome (skip on replay)."""
    existing = get_existing_outcome(
        engine, account_id=alert.account_id, month=alert.month, alert_type=DEFAULT_ALERT_TYPE
    )
    return existing is not None and existing.status == "sent"


def record_alert_outcome(
    engine: Engine,
    *,
    run_id: str,
    alert: RiskAlert,
    status: AlertStatus,
    error: Optional[str] = None,
    sent_at: Optional[datetime] = None,
) -> None:
    """Persist the outcome for one alert key.

    Atomic upsert: inserts a new row, or on conflict updates the existing one
    ONLY when its status is not already 'sent'. So a previously sent alert is
    never overwritten (DB-enforced idempotency); a previously failed alert is
    overwritten on retry.
    """
    now = _utc_now()
    if status == "sent" and sent_at is None:
        sent_at = now

    alert_json = alert.model_dump_json()

    values = dict(
        run_id=run_id,
        account_id=alert.account_id,
        account_name=alert.account_name,
        account_region=alert.account_region,
        month=alert.month,
        channel=alert.channel,
        alert_type=DEFAULT_ALERT_TYPE,
        status=status,
        sent_at=sent_at,
        error=error,
        alert_json=alert_json,
        created_at=now,
        updated_at=now,
    )

    stmt = (
        sqlite_insert(alert_outcomes)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["account_id", "month", "alert_type"],
            set_=dict(
                run_id=run_id,
                account_name=alert.account_name,
                account_region=alert.account_region,
                channel=alert.channel,
                status=status,
                sent_at=sent_at,
                error=error,
                alert_json=alert_json,
                updated_at=now,
            ),
            where=(alert_outcomes.c.status != "sent"),  # never clobber a sent alert
        )
    )
    with engine.begin() as conn:
        conn.execute(stmt)


# ---- GET /runs/{run_id} 


def get_run_result(
    engine: Engine, run_id: str, *, sample_limit: int = 10
) -> Optional[RunResultResponse]:
    """Assemble the GET /runs/{id} response, or None if the run doesn't exist"""
    with engine.begin() as conn:
        run = (
            conn.execute(select(runs).where(runs.c.run_id == run_id))
            .mappings()
            .first()
        )
        if run is None:
            return None

        alert_rows = (
            conn.execute(
                select(alert_outcomes.c.alert_json)
                .where(
                    alert_outcomes.c.run_id == run_id,
                    alert_outcomes.c.status == "sent",
                )
                .order_by(alert_outcomes.c.id)
                .limit(sample_limit)
            )
            .scalars()
            .all()
        )

        error_rows = (
            conn.execute(
                select(alert_outcomes)
                .where(
                    alert_outcomes.c.run_id == run_id,
                    alert_outcomes.c.status == "failed",
                )
                .order_by(alert_outcomes.c.id)
                .limit(sample_limit)
            )
            .mappings()
            .all()
        )

    counts = RunCounts(
        rows_scanned=run["rows_scanned"],
        alerts_sent=run["alerts_sent"],
        skipped_replay=run["skipped_replay"],
        failed_deliveries=run["failed_deliveries"],
        duplicate_rows=run["duplicate_rows"],
    )

    return RunResultResponse(
        run_id=run_id,
        status=run["status"],
        counts=counts,
        sample_alerts=[
            RiskAlert.model_validate_json(j) 
            for j in alert_rows
        ],
        sample_errors=[
            _row_to_outcome(r) 
            for r in error_rows
        ],
    )


# ---- helpers 


def _row_to_outcome(row) -> AlertOutcome:
    return AlertOutcome(
        account_id=row["account_id"],
        account_name=row["account_name"],
        account_region=row["account_region"],
        month=row["month"],
        channel=row["channel"],
        alert_type=row["alert_type"],
        status=row["status"],
        sent_at=row["sent_at"],
        error=row["error"],
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)