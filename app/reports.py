from __future__ import annotations

from typing import Any

from .db import normalize_columns, run_query
from .opcua import read_opcua_values
from .schemas import DatabaseConnection, QueryPreviewRequest
from .utils import make_jsonable, now_iso


def normalize_body_tables(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a normalized list of body tables (mix of query/custom items).

    Backwards compatible with the legacy layout where ``body`` holds a single
    query (table/columns/filters/order_by/limit) plus a ``custom_tables`` list.
    """

    raw = body.get("tables")
    if isinstance(raw, list) and raw:
        result: list[dict[str, Any]] = []
        raw_custom: list[dict[str, Any]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            entry: dict[str, Any] = {
                "id": str(item.get("id") or f"t_{index}"),
                "title": item.get("title") or "",
            }
            if kind == "custom":
                entry["kind"] = "custom"
                entry["rows"] = item.get("rows", [])
                raw_custom.append(entry)
            else:
                entry["kind"] = "query"
                entry["table"] = item.get("table", "")
                entry["columns"] = item.get("columns", [])
                entry["filters"] = item.get("filters", [])
                entry["order_by"] = item.get("order_by", [])
                entry["limit"] = item.get("limit", 500)
                result.append(entry)
        for index, table in enumerate(body.get("custom_tables", []) or []):
            if not isinstance(table, dict):
                continue
            result.append(
                {
                    "id": f"t_custom_legacy_{index}",
                    "kind": "custom",
                    "title": table.get("title", ""),
                    "rows": table.get("rows", []),
                }
            )
        result.extend(raw_custom)
        return result

    # Legacy layout: synthesize a tables list.
    legacy: list[dict[str, Any]] = []
    has_query = any(body.get(key) for key in ("table", "columns", "filters", "order_by")) or "limit" in body
    if has_query:
        legacy.append(
            {
                "id": "t_query_legacy",
                "kind": "query",
                "title": "",
                "table": body.get("table", ""),
                "columns": body.get("columns", []),
                "filters": body.get("filters", []),
                "order_by": body.get("order_by", []),
                "limit": body.get("limit", 500),
            }
        )
    for index, table in enumerate(body.get("custom_tables", []) or []):
        if not isinstance(table, dict):
            continue
        legacy.append(
            {
                "id": f"t_custom_legacy_{index}",
                "kind": "custom",
                "title": table.get("title", ""),
                "rows": table.get("rows", []),
            }
        )
    return legacy


def collect_opcua_nodes(template: dict[str, Any]) -> list[str]:
    nodes: set[str] = set()
    for region_name in ("header", "footer"):
        for row in template.get(region_name, {}).get("rows", []):
            for cell in row:
                if isinstance(cell, dict) and cell.get("type") == "opcua" and cell.get("node_id"):
                    nodes.add(str(cell["node_id"]))
    body = template.get("body", {}) or {}
    for item in normalize_body_tables(body):
        if item["kind"] == "custom":
            for row in item.get("rows", []):
                for cell in row:
                    if isinstance(cell, dict) and cell.get("type") == "opcua" and cell.get("node_id"):
                        nodes.add(str(cell["node_id"]))
        else:
            for filter_item in item.get("filters", []) or []:
                source = (filter_item or {}).get("source") or {}
                if source.get("type") == "opcua" and source.get("node_id"):
                    nodes.add(str(source["node_id"]))
    return sorted(nodes)


def resolve_cell(
    cell: Any,
    opcua_values: dict[str, Any],
    body_rows: list[dict[str, Any]],
    rows_by_source: dict[str, list[dict[str, Any]]] | None = None,
) -> Any:
    if not isinstance(cell, dict):
        return cell
    cell_type = cell.get("type", "static")
    if cell_type == "static":
        return cell.get("value", "")
    if cell_type == "opcua":
        return opcua_values.get(str(cell.get("node_id", "")), "")
    source_id = cell.get("source_id")
    rows = body_rows
    if source_id and rows_by_source and source_id in rows_by_source:
        rows = rows_by_source[source_id]
    if cell_type == "db_summary":
        aggregate = cell.get("aggregate", "count")
        column = cell.get("column")
        if aggregate == "count":
            return len(rows)
        if aggregate == "sum" and column:
            return round(sum(float(row.get(column) or 0) for row in rows), 4)
        if aggregate == "avg" and column and rows:
            values = [float(row.get(column) or 0) for row in rows]
            return round(sum(values) / len(values), 4)
    if cell_type == "db_field" and rows:
        return rows[0].get(str(cell.get("column", "")), "")
    return ""


def render_region(
    region: dict[str, Any],
    opcua_values: dict[str, Any],
    body_rows: list[dict[str, Any]],
    rows_by_source: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    rows = []
    for row in region.get("rows", []):
        rows.append([resolve_cell(cell, opcua_values, body_rows, rows_by_source) for cell in row])
    return {"title": region.get("title", ""), "rows": rows, "repeat_pdf_each_page": bool(region.get("repeat_pdf_each_page"))}


async def generate_report(template: dict[str, Any]) -> dict[str, Any]:
    opcua_config = template.get("opcua", {})
    nodes = collect_opcua_nodes(template)
    opcua_values = await read_opcua_values(opcua_config, nodes)

    body = template.get("body", {}) or {}
    body_items = normalize_body_tables(body)

    # Execute each query item; collect rows keyed by item id (for db_field/db_summary lookup).
    rows_by_source: dict[str, list[dict[str, Any]]] = {}
    query_outputs: dict[str, dict[str, Any]] = {}
    first_query_rows: list[dict[str, Any]] = []
    connection_payload = template.get("database", {}) or {}

    for item in body_items:
        if item["kind"] != "query":
            continue
        query_request = QueryPreviewRequest(
            connection=DatabaseConnection(**connection_payload),
            table=item.get("table") or "production_records",
            columns=[column.get("name") if isinstance(column, dict) else column for column in item.get("columns", [])],
            filters=item.get("filters", []),
            order_by=item.get("order_by", []),
            limit=int(item.get("limit", 500) or 500),
            opcua_values=opcua_values,
        )
        result = run_query(query_request)
        label_map = {column["name"]: column["label"] for column in normalize_columns(item.get("columns", []))}
        result_columns = [
            {"name": c["name"], "label": label_map.get(c["name"], c["label"])} for c in result["columns"]
        ]
        query_outputs[item["id"]] = {
            "columns": result_columns,
            "rows": result["rows"],
            "sql": result["sql"],
            "row_count": result["row_count"],
        }
        rows_by_source[item["id"]] = result["rows"]
        if not first_query_rows:
            first_query_rows = result["rows"]

    # Build the ordered output table list (mirrors template order).
    out_tables: list[dict[str, Any]] = []
    legacy_custom: list[dict[str, Any]] = []
    for item in body_items:
        if item["kind"] == "query":
            q = query_outputs.get(item["id"], {"columns": [], "rows": [], "sql": "", "row_count": 0})
            out_tables.append(
                {
                    "id": item["id"],
                    "kind": "query",
                    "title": item.get("title", ""),
                    "table": item.get("table", ""),
                    "columns": q["columns"],
                    "rows": q["rows"],
                    "sql": q["sql"],
                    "row_count": q["row_count"],
                }
            )
        else:
            rendered = render_region(item, opcua_values, first_query_rows, rows_by_source)
            entry = {
                "id": item["id"],
                "kind": "custom",
                "title": item.get("title", ""),
                "rows": rendered["rows"],
            }
            out_tables.append(entry)
            legacy_custom.append({"title": entry["title"], "rows": entry["rows"]})

    # Legacy fields: first query result populates body.columns/rows/sql/row_count.
    first_query_output = next((t for t in out_tables if t["kind"] == "query"), None)
    legacy_columns = first_query_output["columns"] if first_query_output else []
    legacy_rows = first_query_output["rows"] if first_query_output else []
    legacy_sql = first_query_output["sql"] if first_query_output else ""
    legacy_row_count = first_query_output["row_count"] if first_query_output else 0

    report = {
        "template_id": template.get("id"),
        "name": template.get("name", "Untitled Report"),
        "generated_at": now_iso(),
        "page": template.get("page", {}),
        "opcua_values": opcua_values,
        "header": render_region(template.get("header", {}), opcua_values, first_query_rows, rows_by_source),
        "body": {
            "tables": out_tables,
            "columns": legacy_columns,
            "rows": legacy_rows,
            "sql": legacy_sql,
            "row_count": legacy_row_count,
            "custom_tables": legacy_custom,
        },
        "footer": render_region(template.get("footer", {}), opcua_values, first_query_rows, rows_by_source),
    }
    return make_jsonable(report)
