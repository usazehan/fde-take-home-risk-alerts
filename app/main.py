from fastapi import FastAPI
from pydantic import BaseModel

from .config import get_config
from .models import HealthResponse, PreviewResponse, RunRequest
from .risk_logic import compute_alerts

app = FastAPI(title="Risk Alert Service")

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()

@app.post("/runs")
def create_run(req: RunRequest):
    # TODO:
    # - open parquet via storage.open_uri
    # - compute alerts for req.month
    # - send to Slack unless dry_run
    # - persist run and alert outcomes
    return {"run_id": "TODO"}

@app.get("/runs/{run_id}")
def get_run(run_id: str):
    # TODO: return run status + counts + samples
    return {"run_id": run_id, "status": "TODO"}

@app.post("/preview", response_model=PreviewResponse)
def preview(req: RunRequest) -> PreviewResponse:
    result = compute_alerts(
        source_uri=req.source_uri,
        target_month=req.month,
        config=get_config(),
    )
    
    return PreviewResponse(
        month=req.month,
        duplicate_rows=result.duplicate_rows,
        alerts=result.alerts,
    )
