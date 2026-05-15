from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "app_data"
APP_DB = DATA_DIR / "report_app.sqlite"
DEMO_DB = DATA_DIR / "business_data.sqlite"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_json(name: str, default: dict[str, Any]) -> dict[str, Any]:
    raw = os.getenv(name)
    if not raw:
        return dict(default)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return dict(default)
    return value if isinstance(value, dict) else dict(default)


def _cors_origins() -> list[str]:
    raw = os.getenv("REPORT_APP_CORS_ORIGINS", "*")
    return [item.strip() for item in raw.split(",") if item.strip()] or ["*"]


FIELD_OPCUA = {
    "server_url": os.getenv("REPORT_APP_OPCUA_URL", "mock://local"),
    "root_node": os.getenv("REPORT_APP_OPCUA_ROOT_NODE", "ns=6;i=1000"),
}

FIELD_MYSQL = {
    "type": "mysql",
    "name": os.getenv("REPORT_APP_MYSQL_NAME", ""),
    "host": os.getenv("REPORT_APP_MYSQL_HOST", "127.0.0.1"),
    "port": _env_int("REPORT_APP_MYSQL_PORT", 3306),
    "username": os.getenv("REPORT_APP_MYSQL_USER", ""),
    "password": os.getenv("REPORT_APP_MYSQL_PASSWORD", ""),
    "database": os.getenv("REPORT_APP_MYSQL_DATABASE", os.getenv("REPORT_APP_MYSQL_NAME", "")),
    "charset": os.getenv("REPORT_APP_MYSQL_CHARSET", "utf8mb4"),
}

DEFAULT_MOCK_OPCUA_VALUES = _env_json(
    "REPORT_APP_MOCK_OPCUA_VALUES",
    {"batch_no": "B20260514", "shift": "A", "operator": "??"},
)

CORS_ORIGINS = _cors_origins()
CORS_ALLOW_CREDENTIALS = os.getenv("REPORT_APP_CORS_ALLOW_CREDENTIALS", "false").lower() in {"1", "true", "yes"}
