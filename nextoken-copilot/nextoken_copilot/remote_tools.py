"""Remote tool source: the real NexToken backend's assistant surface.

Instead of our local reference data layer, fetch the caller's allowed tools
from ``GET /api/assistant/tools`` (the backend returns only what that role may
use) and wrap each one as an agent tool that POSTs
``/api/assistant/tools/execute`` with the caller's JWT.

Security properties this preserves:
  * RBAC is enforced *server-side* on every call (``require_assistant_tool``),
    and each call is written to ``assistant_audit_logs`` — the agent cannot
    bypass either.
  * Identity is the JWT, never a model argument; customers are self-scoped by
    the backend regardless of what the model sends.
  * A 403 comes back to the agent as a plain "disabled for role" message, so
    the answer degrades gracefully instead of crashing.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from langchain_core.tools import StructuredTool
from pydantic import Field, create_model

from .config import settings

_TYPE_MAP = {"integer": int, "number": float, "string": str, "boolean": bool}


def _args_model(tool_name: str, parameters: dict | None):
    props = (parameters or {}).get("properties", {}) or {}
    required = set((parameters or {}).get("required", []) or [])
    fields: dict[str, Any] = {}
    for key, spec in props.items():
        py = _TYPE_MAP.get(spec.get("type"), str)
        desc = spec.get("description", "")
        if key in required:
            fields[key] = (py, Field(..., description=desc))
        else:
            fields[key] = (py | None, Field(spec.get("default", None), description=desc))
    return create_model(f"{tool_name}_args", **fields)


async def _execute(tool_name: str, token: str, base_url: str, arguments: dict, transport=None) -> str:
    body = {"tool_name": tool_name, "arguments": {k: v for k, v in arguments.items() if v is not None}}
    async with httpx.AsyncClient(base_url=base_url, timeout=30, transport=transport) as client:
        resp = await client.post(
            "/api/assistant/tools/execute",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:  # noqa: BLE001
            detail = resp.text
        return json.dumps({"error": str(detail), "status": resp.status_code}, ensure_ascii=False)
    data = resp.json().get("data", {})
    return json.dumps(data, ensure_ascii=False, default=str)


async def load_remote_tools(token: str | None = None, base_url: str | None = None, transport=None) -> list[StructuredTool]:
    """Fetch the role's tool schemas and wrap them as agent tools."""
    token = token or settings.backend_token
    base_url = base_url or settings.backend_url
    if not token:
        raise ValueError("Remote tools mode needs a backend JWT (COPILOT_BACKEND_TOKEN or per-request token)")

    async with httpx.AsyncClient(base_url=base_url, timeout=15, transport=transport) as client:
        resp = await client.get("/api/assistant/tools", headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        payload = resp.json()

    tools: list[StructuredTool] = []
    for item in payload.get("tools", []):
        fn = item.get("function", {}) or {}
        name = fn.get("name")
        if not name:
            continue

        async def runner(_name=name, _token=token, _base=base_url, _transport=transport, **kwargs):
            return await _execute(_name, _token, _base, kwargs, transport=_transport)

        tools.append(
            StructuredTool.from_function(
                coroutine=runner,
                name=name,
                description=fn.get("description", ""),
                args_schema=_args_model(name, fn.get("parameters")),
            )
        )
    return tools
