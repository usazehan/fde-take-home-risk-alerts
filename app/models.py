from datetime import date, datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field


AlertStatus = Literal["sent", "skipped_replay", "failed"]
 
RunStatus = Literal["succeeded", "failed"]
 
AlertType = Literal["at_risk"]

class RunCounts(BaseModel):
    rows_scanned: int = 0
    alerts_sent: int = 0
    skipped_replay: int = 0
    failed_deliveries: int = 0
    duplicate_rows: int = 0

# Domain Models
class RiskAlert(BaseModel):
    account_id: str
    account_name: str
    account_region: Optional[str] = None
    channel: Optional[str] = None

    month: date

    duration_months: int
    risk_start_month: date

    arr: Optional[int] = None
    renewal_date: Optional[date] = None
    account_owner: Optional[str] = None

    details_url: str
    
class AlertOutcome(BaseModel):
    account_id: str
    account_name: str
    account_region: Optional[str] = None # surfaced so unknown_region errors are self-explanatory
    month: date
    channel: Optional[str] = None
    alert_type: AlertType = "at_risk"
    status: AlertStatus
    sent_at: Optional[datetime] = None
    error: Optional[str] = None # "unknown_region" | HTTP error detail | None
    
# API Request Models
class RunRequest(BaseModel):
    source_uri: str = Field(..., examples=["file:///tmp/monthly_account_status.parquet"])
    month: date = Field(..., examples=["2026-01-01"])
    dry_run: bool = False

# API Response Models
class HealthResponse(BaseModel):
    ok: bool = True
    
class RunResponse(BaseModel):
    run_id: str

class RunResultResponse(BaseModel):
    run_id: str
    status: RunStatus
    counts: RunCounts
    sample_alerts: list[RiskAlert] = Field(default_factory=list)
    sample_errors: list[AlertOutcome] = Field(default_factory=list)

class PreviewResponse(BaseModel):
    month: date
    alerts: list[RiskAlert] = Field(default_factory=list)
