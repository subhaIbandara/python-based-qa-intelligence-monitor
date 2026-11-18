"""Configuration. DB settings come from environment variables, falling back to
the project's .env file (simple KEY=VALUE lines; no extra dependency)."""
import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file(BASE_DIR / ".env")

DB_CONFIG = {
    "host": os.environ.get("QA_DB_HOST", "localhost"),
    "port": int(os.environ.get("QA_DB_PORT", "5432")),
    "dbname": os.environ.get("QA_DB_NAME", "qa_intelligence"),
    "user": os.environ.get("QA_DB_USER", "qa_app"),
    "password": os.environ.get("QA_DB_PASSWORD", ""),
    "connect_timeout": 3,
}

# Site under test (live project). Override with QA_BASE_URL in the environment or .env.
DEFAULT_BASE_URL = "https://www.qa-practice.com"
QA_BASE_URL = os.environ.get("QA_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
TARGET_HOST = urlparse(QA_BASE_URL).netloc.removeprefix("www.")   # e.g. "qa-practice.com"

# Analysis settings (documented in MAPPING.md)
HISTORY_DAYS = 90
SHORT_MA, LONG_MA = 7, 28
RSI_PERIOD = 14
FPI_HIGH, FPI_LOW = 70, 30
FPI_FLOOR = 0.05            # FPI only escalates when 7d failure rate >= 5%
BOLLINGER_N, BOLLINGER_K = 20, 2.0
ATR_PERIOD = 14
MOMENTUM_DAYS = 7

RISK_WEIGHTS = {
    "failure_rate": 0.25,
    "momentum": 0.15,
    "volatility": 0.15,
    "criticality": 0.20,
    "coverage_gap": 0.15,
    "change_volume": 0.10,
}
