"""Remote tool adapter against a mocked NexToken backend (fully offline)."""
import asyncio
import json

import httpx

from nextoken_copilot.remote_tools import _execute, load_remote_tools

SCHEMA = {
    "role": "customer",
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "secure_get_customer_balance",
                "description": "Return a customer's wallet balance.",
                "parameters": {
                    "type": "object",
                    "properties": {"customer_id": {"type": "integer", "description": "staff only"}},
                    "additionalProperties": False,
                },
            },
        }
    ],
}


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/assistant/tools":
        assert request.headers["Authorization"] == "Bearer test-jwt"
        return httpx.Response(200, json=SCHEMA)
    if request.url.path == "/api/assistant/tools/execute":
        body = json.loads(request.content)
        if body["tool_name"] == "secure_list_customers":
            return httpx.Response(403, json={"detail": "Assistant tool is disabled for role"})
        assert "customer_id" not in body["arguments"]  # None args must be stripped
        return httpx.Response(200, json={"tool": body["tool_name"], "data": {"balance": {"customer_id": 1, "balance": 42.5}}})
    return httpx.Response(404)


TRANSPORT = httpx.MockTransport(_handler)


def test_loads_role_scoped_tools_and_executes():
    tools = asyncio.run(load_remote_tools(token="test-jwt", base_url="http://backend", transport=TRANSPORT))
    assert [t.name for t in tools] == ["secure_get_customer_balance"]
    out = asyncio.run(tools[0].ainvoke({"customer_id": None}))
    assert json.loads(out)["balance"]["balance"] == 42.5


def test_forbidden_tool_degrades_gracefully():
    out = asyncio.run(_execute("secure_list_customers", "test-jwt", "http://backend", {}, transport=TRANSPORT))
    payload = json.loads(out)
    assert payload["status"] == 403 and "disabled" in payload["error"]
