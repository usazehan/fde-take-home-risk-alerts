from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Risk Alert Service")

class RunRequest(BaseModel):
    source_uri: str
    month: str  # YYYY-MM-01
    dry_run: bool = False

@app.get("/health")
def health():
    return {"ok": True}

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

@app.post("/preview")
def preview(req: RunRequest):
    # TODO: compute alerts but do not send
    return {"alerts": [], "month": req.month}
