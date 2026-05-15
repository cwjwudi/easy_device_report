from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import HTTPException

from .config import APP_DB
from .db import sqlite_connect


def get_template(template_id: int) -> dict[str, Any]:
    with sqlite_connect(APP_DB) as conn:
        row = conn.execute("SELECT id, name, config_json FROM report_templates WHERE id = ?", (template_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Report template not found.")
    config = json.loads(row["config_json"])
    config["id"] = row["id"]
    config["name"] = row["name"]
    return config


def row_to_data_source(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["config"] = json.loads(item["config_json"])
    item.pop("config_json", None)
    return item
