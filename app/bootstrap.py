from __future__ import annotations

import json
import sqlite3
from typing import Any

from .config import APP_DB, DEFAULT_MOCK_OPCUA_VALUES, DEMO_DB, FIELD_MYSQL, FIELD_OPCUA
from .db import sqlite_connect
from .utils import now_iso


def sample_sqlite_template() -> dict[str, Any]:
    return {
        "name": "生产批次报表",
        "page": {"size": "A4", "orientation": "portrait", "margin_mm": 14, "page_number_position": "none"},
        "opcua": {"server_url": "mock://local", "node_values": DEFAULT_MOCK_OPCUA_VALUES},
        "database": {"type": "sqlite", "path": str(DEMO_DB)},
        "header": {
            "title": "页眉",
            "rows": [
                [{"type": "static", "value": "批次号"}, {"type": "opcua", "node_id": "batch_no"}, {"type": "static", "value": "班次"}, {"type": "opcua", "node_id": "shift"}],
                [{"type": "static", "value": "操作员"}, {"type": "opcua", "node_id": "operator"}, {"type": "static", "value": "数据来源"}, {"type": "static", "value": "OPC UA + SQLite"}],
            ],
        },
        "body": {
            "table": "production_records",
            "columns": [
                {"name": "record_time", "label": "时间"},
                {"name": "line_name", "label": "产线"},
                {"name": "product_code", "label": "产品"},
                {"name": "temperature", "label": "温度"},
                {"name": "pressure", "label": "压力"},
                {"name": "quantity", "label": "数量"},
                {"name": "status", "label": "状态"},
            ],
            "filters": [{"column": "batch_no", "operator": "=", "source": {"type": "opcua", "node_id": "batch_no"}}],
            "order_by": [{"column": "record_time", "direction": "ASC"}],
            "limit": 500,
        },
        "footer": {
            "title": "页脚",
            "rows": [
                [{"type": "static", "value": "记录数"}, {"type": "db_summary", "aggregate": "count"}, {"type": "static", "value": "总数量"}, {"type": "db_summary", "aggregate": "sum", "column": "quantity"}],
                [{"type": "static", "value": "审核"}, {"type": "static", "value": ""}, {"type": "static", "value": "备注"}, {"type": "static", "value": ""}],
            ],
        },
    }


def field_mysql_template() -> dict[str, Any]:
    database_name = FIELD_MYSQL.get("database") or FIELD_MYSQL.get("name") or ""
    return {
        "name": "现场 MySQL + OPC UA 示例报表",
        "page": {"size": "A4", "orientation": "landscape", "margin_mm": 12, "page_number_position": "none"},
        "opcua": FIELD_OPCUA,
        "database": FIELD_MYSQL,
        "header": {
            "title": "页眉",
            "rows": [
                [{"type": "static", "value": "OPC UA 服务器"}, {"type": "static", "value": FIELD_OPCUA["server_url"]}, {"type": "static", "value": "MySQL 库"}, {"type": "static", "value": database_name}],
                [{"type": "static", "value": "AIR 实时值"}, {"type": "opcua", "node_id": "ns=6;s=::DataGen:AIR"}, {"type": "static", "value": "AP1 实时值"}, {"type": "opcua", "node_id": "ns=6;s=::DataGen:AP1"}],
                [{"type": "static", "value": "BP1 实时值"}, {"type": "opcua", "node_id": "ns=6;s=::DataGen:BP1"}, {"type": "static", "value": "DB 筛选"}, {"type": "static", "value": "AIR >= OPC UA AIR"}],
            ],
        },
        "body": {
            "table": "Group1_20260511",
            "columns": [
                {"name": "id", "label": "ID"},
                {"name": "collection_time", "label": "采集时间"},
                {"name": "AIR", "label": "AIR"},
                {"name": "AP1", "label": "AP1"},
                {"name": "AP2", "label": "AP2"},
                {"name": "CP", "label": "CP"},
                {"name": "CT", "label": "CT"},
                {"name": "EC", "label": "EC"},
                {"name": "ES", "label": "ES"},
            ],
            "filters": [{"column": "AIR", "operator": ">=", "source": {"type": "opcua", "node_id": "ns=6;s=::DataGen:AIR"}}],
            "order_by": [{"column": "collection_time", "direction": "ASC"}],
            "limit": 80,
        },
        "footer": {
            "title": "页脚",
            "rows": [
                [{"type": "static", "value": "记录数"}, {"type": "db_summary", "aggregate": "count"}, {"type": "static", "value": "AIR 平均值"}, {"type": "db_summary", "aggregate": "avg", "column": "AIR"}],
                [{"type": "static", "value": "CP 合计"}, {"type": "db_summary", "aggregate": "sum", "column": "CP"}, {"type": "static", "value": "CT 平均值"}, {"type": "db_summary", "aggregate": "avg", "column": "CT"}],
            ],
        },
    }


def upsert_template(conn: sqlite3.Connection, template: dict[str, Any]) -> None:
    row = conn.execute("SELECT id FROM report_templates WHERE name = ?", (template["name"],)).fetchone()
    payload = json.dumps(template, ensure_ascii=False)
    if row:
        conn.execute("UPDATE report_templates SET config_json = ?, updated_at = ? WHERE id = ?", (payload, now_iso(), row["id"]))
    else:
        conn.execute("INSERT INTO report_templates (name, config_json, created_at, updated_at) VALUES (?, ?, ?, ?)", (template["name"], payload, now_iso(), now_iso()))


def upsert_data_source(conn: sqlite3.Connection, name: str, kind: str, config: dict[str, Any]) -> None:
    row = conn.execute("SELECT id FROM data_sources WHERE name = ?", (name,)).fetchone()
    payload = json.dumps(config, ensure_ascii=False)
    if row:
        conn.execute("UPDATE data_sources SET kind = ?, config_json = ?, updated_at = ? WHERE id = ?", (kind, payload, now_iso(), row["id"]))
    else:
        conn.execute("INSERT INTO data_sources (name, kind, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (name, kind, payload, now_iso(), now_iso()))


def seed_defaults() -> None:
    with sqlite_connect(APP_DB) as conn:
        if conn.execute("SELECT COUNT(*) AS value FROM report_templates").fetchone()["value"] == 0:
            upsert_template(conn, sample_sqlite_template())
            upsert_template(conn, field_mysql_template())
        upsert_data_source(conn, "演示 SQLite 数据库", "database", {"type": "sqlite", "path": str(DEMO_DB)})
        upsert_data_source(conn, "现场 MySQL", "database", FIELD_MYSQL)
        upsert_data_source(conn, "现场 OPC UA", "opcua", FIELD_OPCUA)
