"""Spawn the role-scoped MCP server and load its tools for one principal.

The principal is injected into the server process via environment variables when
the stdio server is spawned — the trusted runtime sets them, never the model.
Each tool call opens a fresh session, so identity can't leak between requests.
"""
from __future__ import annotations

import os
import sys

from langchain_mcp_adapters.client import MultiServerMCPClient

from ..config import BASE_DIR, settings
from ..principal import Principal


def connection(principal: Principal) -> dict:
    env = {
        **os.environ,
        "COPILOT_PRINCIPAL_ROLE": principal.role.value,
        "COPILOT_PRINCIPAL_EMAIL": principal.email or "",
        "COPILOT_DATABASE_URL": settings.database_url,
    }
    if principal.customer_id is not None:
        env["COPILOT_PRINCIPAL_CUSTOMER_ID"] = str(principal.customer_id)
    return {
        "nextoken": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "nextoken_copilot.mcp_server"],
            "cwd": str(BASE_DIR),
            "env": env,
        }
    }


async def load_tools(principal: Principal):
    client = MultiServerMCPClient(connection(principal))
    return await client.get_tools()
