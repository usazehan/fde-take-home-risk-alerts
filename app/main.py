from fastapi import FastAPI, HTTPException

from .config import get_config
from .models import HealthResponse, PreviewResponse, RunRequest, RunResponse, RunResultResponse
from .risk_logic import compute_alerts
from .run_service import RunService
from .storage import StorageError
from contextlib import asynccontextmanager
from .db import make_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine(get_config().sqlite_db_path)
    app.state.service = RunService(engine=engine)
    try:
        yield
    finally:
        engine.dispose()

app = FastAPI(
    title="Risk Alert Service",
    description="A service to compute and send risk alerts based on monthly account status data with Slack integration.",
    version="1.0.0",
    lifespan=lifespan,
)

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()

@app.post("/runs", response_model=RunResponse)
def create_run(req: RunRequest) -> RunResponse:
    """Process the run synchronously and return its run_id after completion"""
    try:
        return app.state.service.create_run(req)
    except (StorageError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/runs/{run_id}", response_model=RunResultResponse)
def get_run(run_id: str) -> RunResultResponse:
    """Return persisted run status, counts, and sample alerts/errors"""
    # RunService.get_run raises HTTPException(404) when the run doesn't exist.
    return app.state.service.get_run(run_id)

@app.post("/preview", response_model=PreviewResponse)
def preview(req: RunRequest) -> PreviewResponse:
    """Compute alerts for the month and return them. No Slack, no persistence"""
    try:
        result = compute_alerts(
            source_uri=req.source_uri,
            target_month=req.month,
            config=get_config(),
        )
    except (StorageError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    return PreviewResponse(
        month=req.month,
        duplicate_rows=result.duplicate_rows,
        alerts=result.alerts,
    )
