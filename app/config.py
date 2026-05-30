import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


DEFAULT_REGION_CHANNELS = {
    "AMER": "amer-risk-alerts",
    "EMEA": "emea-risk-alerts",
    "APAC": "apac-risk-alerts",
}


@dataclass(frozen=True)
class AppConfig:
    arr_threshold: int = 100_000
    sqlite_db_path: str = "risk_alerts.db"
    details_base_url: str = "https://app.quadsci.ai"

    slack_webhook_base_url: Optional[str] = None
    slack_webhook_url: Optional[str] = None

    def channel_for_region(self, region: Optional[str]) -> Optional[str]:
        if not region:
            return None

        return DEFAULT_REGION_CHANNELS.get(region.strip().upper())

    def details_url_for_account(self, account_id: str) -> str:
        return f"{self.details_base_url.rstrip('/')}/accounts/{account_id}"


def _get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)

    if value is None or value.strip() == "":
        return default

    return int(value)


@lru_cache
def get_config() -> AppConfig:
    return AppConfig(
        arr_threshold=_get_int_env("ARR_THRESHOLD", 100_000),
        sqlite_db_path=os.getenv("SQLITE_DB_PATH", "risk_alerts.db"),
        details_base_url=os.getenv("DETAILS_BASE_URL", "https://app.quadsci.ai"),
        slack_webhook_base_url=os.getenv("SLACK_WEBHOOK_BASE_URL"),
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
    )