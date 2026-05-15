from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any
import re

from fastapi import HTTPException

from .config import APP_DB, DATA_DIR, DEMO_DB
from .schemas import DatabaseConnection, QueryPreviewRequest
from .utils import make_jsonable, now_iso, resolve_path

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ALLOWED_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "LIKE"}


@contextmanager
def sqlite_connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def mysql_connect(connection: DatabaseConnection, include_database: bool = True):
    try:
        import pymysql
    except Exception as exc:  # pragma: no cover - dependency safety
        raise HTTPException(status_code=500, detail=f"PyMySQL is not available: {exc}") from exc

    kwargs = {
        "host": connection.host,
        "port": connection.port,
        "user": connection.username,
        "password": connection.password,
        "charset": connection.charset,
        "connect_timeout": 8,
        "read_timeout": 20,
        "write_timeout": 20,
        "cursorclass": pymysql.cursors.DictCursor,
    }
    if include_database and connection.database:
        kwargs["database"] = connection.database
    return pymysql.connect(**kwargs)


def validate_identifier(value: str, label: str = "identifier") -> str:
    if not IDENTIFIER_RE.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {label}: {value}")
    return value


def quote_identifier(value: str, database_type: str) -> str:
    validate_identifier(value)
    quote = "`" if database_type == "mysql" else '"'
    return f"{quote}{value}{quote}"


def normalize_columns(columns: list[Any]) -> list[dict[str, str]]:
    normalized = []
    for item in columns:
        if isinstance(item, str):
            normalized.append({"name": item, "label": item})
        else:
            name = str(item.get("name", ""))
            normalized.append({"name": name, "label": str(item.get("label") or name)})
    if not normalized:
        normalized = [{"name": "*", "label": "*"}]
    return normalized


def build_select_query(request: QueryPreviewRequest) -> tuple[str, list[Any], list[dict[str, str]]]:
    database_type = request.connection.type
    placeholder = "%s" if database_type == "mysql" else "?"
    table = validate_identifier(request.table, "table")
    columns = normalize_columns(request.columns)
    sql_columns: list[str] = []
    for column in columns:
        name = column["name"]
        if name == "*":
            sql_columns.append("*")
        else:
            sql_columns.append(quote_identifier(name, database_type))

    params: list[Any] = []
    where_parts: list[str] = []
    for filter_item in request.filters:
        column = validate_identifier(str(filter_item.get("column", "")), "filter column")
        operator = str(filter_item.get("operator", "=")).upper()
        if operator not in ALLOWED_OPERATORS:
            raise HTTPException(status_code=400, detail=f"Unsupported operator: {operator}")
        source = filter_item.get("source") or {"type": "literal", "value": filter_item.get("value")}
        if source.get("type") == "opcua":
            value = request.opcua_values.get(str(source.get("node_id", "")))
        else:
            value = source.get("value")
        where_parts.append(f"{quote_identifier(column, database_type)} {operator} {placeholder}")
        params.append(value)

    order_parts: list[str] = []
    for order_item in request.order_by:
        column = validate_identifier(str(order_item.get("column", "")), "order column")
        direction = str(order_item.get("direction", "ASC")).upper()
        if direction not in {"ASC", "DESC"}:
            raise HTTPException(status_code=400, detail=f"Unsupported order direction: {direction}")
        order_parts.append(f"{quote_identifier(column, database_type)} {direction}")

    if database_type == "mysql" and request.connection.database:
        table_ref = f"{quote_identifier(request.connection.database, database_type)}.{quote_identifier(table, database_type)}"
    else:
        table_ref = quote_identifier(table, database_type)

    limit = max(1, min(int(request.limit), 1000))
    sql = f"SELECT {', '.join(sql_columns)} FROM {table_ref}"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if order_parts:
        sql += " ORDER BY " + ", ".join(order_parts)
    sql += f" LIMIT {limit}"
    return sql, params, columns


def run_query(request: QueryPreviewRequest) -> dict[str, Any]:
    sql, params, columns = build_select_query(request)
    if request.connection.type == "sqlite":
        path = resolve_path(request.connection.path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Database not found: {path}")
        try:
            with sqlite_connect(path) as conn:
                rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        except sqlite3.Error as exc:
            raise HTTPException(status_code=400, detail=f"Database query failed: {exc}") from exc
    elif request.connection.type == "mysql":
        try:
            conn = mysql_connect(request.connection)
            try:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    rows = list(cursor.fetchall())
            finally:
                conn.close()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"MySQL query failed: {exc}") from exc
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported database type: {request.connection.type}")

    rows = make_jsonable(rows)
    if columns and columns[0]["name"] == "*" and rows:
        columns = [{"name": key, "label": key} for key in rows[0].keys()]
    return {"sql": sql, "params": params, "columns": columns, "rows": rows, "row_count": len(rows)}


def inspect_database_schema(connection: DatabaseConnection, table_limit: int = 50) -> dict[str, Any]:
    if connection.type == "sqlite":
        path = resolve_path(connection.path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Database not found: {path}")
        with sqlite_connect(path) as conn:
            tables = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name LIMIT ?", (table_limit,)).fetchall()]
            result_tables = []
            for table in tables:
                columns = [dict(row) for row in conn.execute(f"PRAGMA table_info({quote_identifier(table, 'sqlite')})").fetchall()]
                result_tables.append({"database": None, "table": table, "columns": columns})
        return {"type": "sqlite", "tables": result_tables}

    conn = mysql_connect(connection, include_database=False)
    try:
        with conn.cursor() as cursor:
            if connection.database:
                databases = [connection.database]
            else:
                cursor.execute("SHOW DATABASES")
                databases = [
                    row["Database"]
                    for row in cursor.fetchall()
                    if row["Database"] not in {"information_schema", "mysql", "performance_schema", "sys"}
                ]
            result_tables = []
            for database in databases:
                validate_identifier(database, "database")
                cursor.execute(f"SHOW FULL TABLES FROM `{database}` WHERE Table_type = 'BASE TABLE'")
                table_rows = cursor.fetchall()
                for table_row in table_rows[:table_limit]:
                    table = next(value for key, value in table_row.items() if key.startswith("Tables_in_"))
                    cursor.execute(f"SHOW COLUMNS FROM `{database}`.`{table}`")
                    result_tables.append({"database": database, "table": table, "columns": make_jsonable(cursor.fetchall())})
    finally:
        conn.close()
    return {"type": "mysql", "tables": result_tables}


def init_app_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite_connect(APP_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS data_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                config_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS report_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS report_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER,
                status TEXT NOT NULL,
                message TEXT,
                rendered_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )


def init_demo_db() -> None:
    with sqlite_connect(DEMO_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS production_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_no TEXT NOT NULL,
                record_time TEXT NOT NULL,
                line_name TEXT NOT NULL,
                product_code TEXT NOT NULL,
                temperature REAL NOT NULL,
                pressure REAL NOT NULL,
                quantity INTEGER NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) AS value FROM production_records").fetchone()["value"]
        if count == 0:
            rows = [
                ("B20260514", "2026-05-14 08:00", "Line-1", "P-1001", 71.2, 0.83, 120, "OK"),
                ("B20260514", "2026-05-14 09:00", "Line-1", "P-1001", 72.1, 0.84, 118, "OK"),
                ("B20260514", "2026-05-14 10:00", "Line-1", "P-1001", 73.0, 0.86, 121, "OK"),
                ("B20260513", "2026-05-13 08:00", "Line-2", "P-1002", 69.8, 0.80, 110, "OK"),
            ]
            conn.executemany(
                """
                INSERT INTO production_records
                (batch_no, record_time, line_name, product_code, temperature, pressure, quantity, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
