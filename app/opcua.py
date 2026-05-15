from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .schemas import OpcUaBrowseRequest, OpcUaTestRequest
from .utils import make_jsonable


async def read_opcua_values(config: dict[str, Any], nodes: list[str]) -> dict[str, Any]:
    server_url = config.get("server_url", "mock://local")
    node_values = config.get("node_values") or {}
    if server_url.startswith("mock://"):
        return {node: node_values.get(node, f"mock:{node}") for node in nodes}

    try:
        from asyncua import Client
    except Exception as exc:  # pragma: no cover - dependency safety
        raise HTTPException(status_code=500, detail=f"asyncua is not available: {exc}") from exc

    result: dict[str, Any] = {}
    try:
        async with Client(url=server_url) as client:
            for node in nodes:
                value = await client.get_node(node).read_value()
                result[node] = make_jsonable(value)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OPC UA read failed: {exc}") from exc
    return result


async def browse_opcua_nodes(request: OpcUaBrowseRequest) -> dict[str, Any]:
    if request.server_url.startswith("mock://"):
        nodes = [
            {"node_id": "batch_no", "display_name": "batch_no", "browse_name": "batch_no", "depth": 0, "value": "B20260514"},
            {"node_id": "shift", "display_name": "shift", "browse_name": "shift", "depth": 0, "value": "A"},
        ]
        return {"ok": True, "mode": "mock", "nodes": nodes}

    try:
        from asyncua import Client
    except Exception as exc:  # pragma: no cover - dependency safety
        raise HTTPException(status_code=500, detail=f"asyncua is not available: {exc}") from exc

    direct_children_only = request.max_depth == 0
    max_depth = max(0, min(request.max_depth, 6))
    limit = max(1, min(request.limit, 500))
    results: list[dict[str, Any]] = []
    try:
        async with Client(url=request.server_url) as client:
            root_node = client.get_node(request.root_node)
            queue = []
            if direct_children_only:
                for child in await root_node.get_children():
                    queue.append((child, 0))
                if not queue:
                    queue = [(root_node, 0)]
            else:
                queue = [(root_node, 0)]
            seen: set[str] = set()
            while queue and len(results) < limit:
                node, depth = queue.pop(0)
                node_id = node.nodeid.to_string()
                if node_id in seen:
                    continue
                seen.add(node_id)
                display = await node.read_display_name()
                browse = await node.read_browse_name()
                item = {
                    "node_id": node_id,
                    "display_name": display.Text,
                    "browse_name": browse.Name,
                    "depth": depth,
                }
                try:
                    children = await node.get_children()
                    item["has_children"] = len(children) > 0
                except Exception:
                    children = []
                    item["has_children"] = False
                if request.include_values:
                    try:
                        item["value"] = make_jsonable(await node.read_value())
                    except Exception:
                        item["value"] = None
                if not (direct_children_only and node_id == request.root_node and results):
                    results.append(item)
                if not direct_children_only and depth < max_depth:
                    for child in children:
                        queue.append((child, depth + 1))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OPC UA browse failed: {exc}") from exc
    return {"ok": True, "mode": "real", "nodes": results}


async def test_opcua_connection(request: OpcUaTestRequest) -> dict[str, Any]:
    if request.server_url.startswith("mock://"):
        return {"ok": True, "mode": "mock", "message": "Mock OPC UA connection is available."}
    await read_opcua_values(request.model_dump(), [])
    return {"ok": True, "mode": "real", "message": "OPC UA connection succeeded."}
