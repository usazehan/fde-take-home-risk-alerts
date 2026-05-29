# Risk Alert Service (Take-home scaffold)

This repository is a minimal scaffold for the take-home exercise.

## Quickstart (local)
1. Create a virtualenv and install deps:
   - `pip install -r requirements.txt`
2. Run the API:
   - `uvicorn app.main:app --reload --port 8000`
3. Health check:
   - `curl http://localhost:8000/health`

## Configuration (examples)
- `SOURCE_URI=file:///path/to/monthly_account_status.parquet`
- `SLACK_WEBHOOK_URL=...`
- `DETAILS_BASE_URL=https://app.yourcompany.com/accounts`
- `REGION_CHANNEL_MAP={"default":"risk-alerts","regions":{"AMER":"amer-risk-alerts","EMEA":"emea-risk-alerts","APAC":"apac-risk-alerts"}}`

## GCS auth (examples)
- `GOOGLE_APPLICATION_CREDENTIALS=/path/to/service_account.json`
- Alternatively, Workload Identity in GKE/Cloud Run.

## Notes
- Most modules contain TODOs. Implement as part of the exercise.
