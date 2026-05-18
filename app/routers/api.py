from __future__ import annotations

import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from ..bootstrap import field_mysql_template, seed_defaults
from ..config import APP_DB, DEMO_DB, FIELD_MYSQL, FIELD_OPCUA, STATIC_DIR
from ..db import init_app_db, init_demo_db, inspect_database_schema, mysql_connect, run_query, sqlite_connect
from ..exporters import make_excel, make_pdf, report_to_html
from ..opcua import browse_opcua_nodes, read_opcua_values, test_opcua_connection
from ..repositories import get_template, row_to_data_source
from ..reports import generate_report
from ..schemas import (
    DatabaseConnection,
    GenerateReportRequest,
    OpcUaBrowseRequest,
    OpcUaPointPayload,
    OpcUaReadRequest,
    OpcUaTestRequest,
    QueryPreviewRequest,
    TemplatePayload,
)
from ..utils import make_jsonable, now_iso, resolve_path

router = APIRouter()


def unique_template_name(name: str, exclude_id: int | None = None) -> str:
    base = name.strip() or "未命名模板"
    with sqlite_connect(APP_DB) as conn:
        rows = conn.execute("SELECT id, name FROM report_templates").fetchall()
    existing = {
        row["name"]
        for row in rows
        if exclude_id is None or int(row["id"]) != int(exclude_id)
    }
    if base not in existing:
        return base
    index = 2
    while f"{base} {index}" in existing:
        index += 1
    return f"{base} {index}"


@router.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "time": now_iso(), "app_db": str(APP_DB), "demo_db": str(DEMO_DB), "field_opcua": FIELD_OPCUA, "field_mysql": {**FIELD_MYSQL, "password": "***"}}


@router.post("/api/startup/one-click")
async def one_click_startup() -> dict[str, Any]:
    steps: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: Any = None) -> None:
        steps.append({"name": name, "ok": ok, "detail": make_jsonable(detail)})

    try:
        init_app_db()
        init_demo_db()
        seed_defaults()
        record("初始化本地配置库和演示数据", True, {"app_db": str(APP_DB), "demo_db": str(DEMO_DB)})
    except Exception as exc:
        record("初始化本地配置库和演示数据", False, str(exc))

    try:
        opcua_result = await test_opcua_connection(OpcUaTestRequest(**FIELD_OPCUA))
        record("连接 OPC UA 服务器", True, opcua_result)
    except Exception as exc:
        record("连接 OPC UA 服务器", False, str(getattr(exc, "detail", exc)))

    try:
        nodes = ["ns=6;s=::DataGen:AIR", "ns=6;s=::DataGen:AP1", "ns=6;s=::DataGen:BP1"]
        values = await read_opcua_values(FIELD_OPCUA, nodes)
        record("读取 OPC UA 参考节点", True, values)
    except Exception as exc:
        record("读取 OPC UA 参考节点", False, str(getattr(exc, "detail", exc)))

    try:
        mysql_conn = DatabaseConnection(**FIELD_MYSQL)
        conn = mysql_connect(mysql_conn)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                row = cursor.fetchone()
        finally:
            conn.close()
        record("连接 MySQL 数据库", True, row)
    except Exception as exc:
        record("连接 MySQL 数据库", False, str(getattr(exc, "detail", exc)))

    try:
        schema = inspect_database_schema(DatabaseConnection(**FIELD_MYSQL), table_limit=30)
        target = next((item for item in schema["tables"] if item["table"] == "Group1_20260511"), schema["tables"][0] if schema["tables"] else None)
        record("读取 MySQL 表结构", True, {"table_count": len(schema["tables"]), "target_table": target})
    except Exception as exc:
        record("读取 MySQL 表结构", False, str(getattr(exc, "detail", exc)))

    report: dict[str, Any] | None = None
    template_id: int | None = None
    try:
        with sqlite_connect(APP_DB) as conn:
            row = conn.execute("SELECT id FROM report_templates WHERE name = ?", (field_mysql_template()["name"],)).fetchone()
            template_id = row["id"] if row else None
        if template_id is None:
            raise RuntimeError("现场 MySQL + OPC UA 示例报表模板不存在")
        report = await generate_report(get_template(template_id))
        record("生成现场示例报表", True, {"template_id": template_id, "rows": report["body"]["row_count"], "sql": report["body"]["sql"]})
    except Exception as exc:
        record("生成现场示例报表", False, str(getattr(exc, "detail", exc)))

    ok = all(step["ok"] for step in steps)
    return {
        "ok": ok,
        "time": now_iso(),
        "template_id": template_id,
        "report": report,
        "steps": steps,
    }


@router.post("/api/opcua/test")
async def opcua_test(request: OpcUaTestRequest) -> dict[str, Any]:
    return await test_opcua_connection(request)


@router.post("/api/opcua/read")
async def opcua_read(request: OpcUaReadRequest) -> dict[str, Any]:
    values = await read_opcua_values(request.model_dump(), request.nodes)
    return {"ok": True, "values": values}


@router.post("/api/opcua/browse")
async def opcua_browse(request: OpcUaBrowseRequest) -> dict[str, Any]:
    return await browse_opcua_nodes(request)


@router.post("/api/database/test")
def database_test(connection: DatabaseConnection) -> dict[str, Any]:
    if connection.type == "sqlite":
        path = resolve_path(connection.path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Database not found: {path}")
        with sqlite_connect(path) as conn:
            conn.execute("SELECT 1").fetchone()
        return {"ok": True, "message": "SQLite connection succeeded.", "path": str(path)}

    conn = mysql_connect(connection)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 AS ok")
            row = cursor.fetchone()
    finally:
        conn.close()
    return {"ok": True, "message": "MySQL connection succeeded.", "result": row, "database": connection.database}


@router.post("/api/database/schema")
def database_schema(connection: DatabaseConnection) -> dict[str, Any]:
    return inspect_database_schema(connection)


@router.post("/api/database/query-preview")
def database_query_preview(request: QueryPreviewRequest) -> dict[str, Any]:
    return run_query(request)


@router.get("/api/data-sources")
def list_data_sources() -> list[dict[str, Any]]:
    with sqlite_connect(APP_DB) as conn:
        rows = conn.execute("SELECT * FROM data_sources ORDER BY id DESC").fetchall()
    return [row_to_data_source(row) for row in rows]


@router.post("/api/data-sources")
def create_data_source(payload: dict[str, Any]) -> dict[str, Any]:
    name = payload.get("name") or "Untitled Data Source"
    kind = payload.get("kind") or "database"
    config = payload.get("config") or {}
    with sqlite_connect(APP_DB) as conn:
        cursor = conn.execute(
            "INSERT INTO data_sources (name, kind, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name, kind, json.dumps(config, ensure_ascii=False), now_iso(), now_iso()),
        )
    return {"id": cursor.lastrowid, "name": name, "kind": kind, "config": config}


@router.get("/api/opcua/points")
def list_opcua_points() -> list[dict[str, Any]]:
    with sqlite_connect(APP_DB) as conn:
        rows = conn.execute("SELECT * FROM data_sources WHERE kind = 'opcua_point' ORDER BY name").fetchall()
    return [row_to_data_source(row) for row in rows]


@router.post("/api/opcua/points")
def create_opcua_point(payload: OpcUaPointPayload) -> dict[str, Any]:
    alias = payload.alias.strip() or payload.display_name or payload.browse_name or payload.node_id
    config = payload.model_dump()
    config["alias"] = alias
    with sqlite_connect(APP_DB) as conn:
        row = conn.execute(
            "SELECT id FROM data_sources WHERE kind = 'opcua_point' AND json_extract(config_json, '$.node_id') = ?",
            (payload.node_id,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE data_sources SET name = ?, config_json = ?, updated_at = ? WHERE id = ?",
                (alias, json.dumps(config, ensure_ascii=False), now_iso(), row["id"]),
            )
            point_id = row["id"]
        else:
            cursor = conn.execute(
                "INSERT INTO data_sources (name, kind, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (alias, "opcua_point", json.dumps(config, ensure_ascii=False), now_iso(), now_iso()),
            )
            point_id = cursor.lastrowid
    return {"id": point_id, "name": alias, "kind": "opcua_point", "config": config}


@router.put("/api/opcua/points/{point_id}")
def update_opcua_point(point_id: int, payload: OpcUaPointPayload) -> dict[str, Any]:
    alias = payload.alias.strip() or payload.display_name or payload.browse_name or payload.node_id
    config = payload.model_dump()
    config["alias"] = alias
    with sqlite_connect(APP_DB) as conn:
        row = conn.execute("SELECT id FROM data_sources WHERE id = ? AND kind = 'opcua_point'", (point_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="OPC UA point not found.")
        conn.execute(
            "UPDATE data_sources SET name = ?, config_json = ?, updated_at = ? WHERE id = ?",
            (alias, json.dumps(config, ensure_ascii=False), now_iso(), point_id),
        )
    return {"id": point_id, "name": alias, "kind": "opcua_point", "config": config}


@router.delete("/api/opcua/points/{point_id}")
def delete_opcua_point(point_id: int) -> dict[str, Any]:
    with sqlite_connect(APP_DB) as conn:
        conn.execute("DELETE FROM data_sources WHERE id = ? AND kind = 'opcua_point'", (point_id,))
    return {"ok": True}


@router.get("/api/report-templates")
def list_report_templates() -> list[dict[str, Any]]:
    with sqlite_connect(APP_DB) as conn:
        rows = conn.execute("SELECT id, name, config_json, created_at, updated_at FROM report_templates ORDER BY id DESC").fetchall()
    return [{**dict(row), "config": json.loads(row["config_json"])} for row in rows]


@router.get("/api/report-templates/{template_id}")
def read_report_template(template_id: int) -> dict[str, Any]:
    return get_template(template_id)


@router.post("/api/report-templates")
def create_report_template(payload: TemplatePayload) -> dict[str, Any]:
    config = payload.config
    name = unique_template_name(payload.name)
    config["name"] = name
    with sqlite_connect(APP_DB) as conn:
        cursor = conn.execute(
            "INSERT INTO report_templates (name, config_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, json.dumps(config, ensure_ascii=False), now_iso(), now_iso()),
        )
    return {"id": cursor.lastrowid, "name": name, "config": config}


@router.put("/api/report-templates/{template_id}")
def update_report_template(template_id: int, payload: TemplatePayload) -> dict[str, Any]:
    get_template(template_id)
    config = payload.config
    name = unique_template_name(payload.name, exclude_id=template_id)
    config["name"] = name
    with sqlite_connect(APP_DB) as conn:
        conn.execute(
            "UPDATE report_templates SET name = ?, config_json = ?, updated_at = ? WHERE id = ?",
            (name, json.dumps(config, ensure_ascii=False), now_iso(), template_id),
        )
    return {"id": template_id, "name": name, "config": config}


@router.post("/api/report-templates/{template_id}/copy")
def copy_report_template(template_id: int) -> dict[str, Any]:
    template = get_template(template_id)
    copied_name = unique_template_name(f"{template['name']} 副本")
    template.pop("id", None)
    template["name"] = copied_name
    return create_report_template(TemplatePayload(name=copied_name, config=template))


@router.delete("/api/report-templates/{template_id}")
def delete_report_template(template_id: int) -> dict[str, Any]:
    get_template(template_id)
    with sqlite_connect(APP_DB) as conn:
        conn.execute("DELETE FROM report_templates WHERE id = ?", (template_id,))
    return {"ok": True}


@router.post("/api/reports/generate")
async def reports_generate(request: GenerateReportRequest) -> dict[str, Any]:
    template = request.template or get_template(int(request.template_id or 0))
    try:
        report = await generate_report(template)
        if request.persist_run:
            with sqlite_connect(APP_DB) as conn:
                conn.execute(
                    "INSERT INTO report_runs (template_id, status, message, rendered_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (report.get("template_id"), "success", "ok", json.dumps(report, ensure_ascii=False), now_iso()),
                )
        return report
    except HTTPException as exc:
        if request.persist_run:
            with sqlite_connect(APP_DB) as conn:
                conn.execute(
                    "INSERT INTO report_runs (template_id, status, message, rendered_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (template.get("id"), "failed", str(exc.detail), None, now_iso()),
                )
        raise


@router.post("/api/reports/export/html")
async def reports_export_html(request: GenerateReportRequest) -> StreamingResponse:
    template = request.template or get_template(int(request.template_id or 0))
    report = await generate_report(template)
    content = report_to_html(report).encode("utf-8")
    return StreamingResponse(io.BytesIO(content), media_type="text/html; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="report.html"'})


@router.post("/api/reports/export/excel")
async def reports_export_excel(request: GenerateReportRequest) -> StreamingResponse:
    template = request.template or get_template(int(request.template_id or 0))
    report = await generate_report(template)
    content = make_excel(report)
    return StreamingResponse(io.BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="report.xlsx"'})


@router.post("/api/reports/export/pdf")
async def reports_export_pdf(request: GenerateReportRequest) -> StreamingResponse:
    template = request.template or get_template(int(request.template_id or 0))
    report = await generate_report(template)
    content = make_pdf(report)
    return StreamingResponse(io.BytesIO(content), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="report.pdf"'})


@router.get("/api/report-runs")
def list_report_runs() -> list[dict[str, Any]]:
    with sqlite_connect(APP_DB) as conn:
        rows = conn.execute("SELECT id, template_id, status, message, created_at FROM report_runs ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(row) for row in rows]
