from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import DEMO_DB, FIELD_OPCUA


class OpcUaTestRequest(BaseModel):
    server_url: str = "mock://local"
    timeout_seconds: float = 5
    node_values: dict[str, Any] = Field(default_factory=dict)


class OpcUaReadRequest(OpcUaTestRequest):
    nodes: list[str] = Field(default_factory=list)


class OpcUaBrowseRequest(OpcUaTestRequest):
    root_node: str = "ns=6;i=1000"
    max_depth: int = 2
    limit: int = 120
    include_values: bool = True


class OpcUaPointPayload(BaseModel):
    alias: str
    node_id: str
    display_name: str | None = None
    browse_name: str | None = None
    server_url: str = FIELD_OPCUA["server_url"]
    root_node: str = FIELD_OPCUA["root_node"]
    data_type: str | None = None
    refresh_seconds: int = 5


class DatabaseConnection(BaseModel):
    type: Literal["sqlite", "mysql"] = "sqlite"
    path: str = str(DEMO_DB)
    name: str | None = None
    host: str = "127.0.0.1"
    port: int = 3306
    username: str = "root"
    password: str = ""
    database: str | None = None
    charset: str = "utf8mb4"


class QueryPreviewRequest(BaseModel):
    connection: DatabaseConnection = Field(default_factory=DatabaseConnection)
    table: str
    columns: list[Any] = Field(default_factory=list)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    order_by: list[dict[str, Any]] = Field(default_factory=list)
    limit: int = 50
    opcua_values: dict[str, Any] = Field(default_factory=dict)


class TemplatePayload(BaseModel):
    name: str
    config: dict[str, Any]


class GenerateReportRequest(BaseModel):
    template_id: int | None = None
    template: dict[str, Any] | None = None
    persist_run: bool = True


class TemplateCell(BaseModel):
    type: str = "static"
    value: Any = ""
    node_id: str | None = None
    column: str | None = None
    aggregate: str | None = None
    source_id: str | None = None


class BodyTable(BaseModel):
    id: str
    kind: Literal["query", "custom"] = "query"
    title: str = ""
    table: str = ""
    columns: list[Any] = Field(default_factory=list)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    order_by: list[dict[str, Any]] = Field(default_factory=list)
    limit: int = 500
    rows: list[list[Any]] = Field(default_factory=list)


def normalize_template(template: dict[str, Any]) -> dict[str, Any]:
    from .reports import normalize_body_tables

    normalized = dict(template or {})
    body = dict(normalized.get("body") or {})
    body["tables"] = normalize_body_tables(body)
    normalized["body"] = body
    return normalized
