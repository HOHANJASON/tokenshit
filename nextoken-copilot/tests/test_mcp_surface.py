"""The MCP surface itself is role-scoped (spawns the real stdio server)."""
import asyncio

from nextoken_copilot.agents.mcp_loader import load_tools
from nextoken_copilot.principal import Principal, Role


def _names(principal):
    return sorted(t.name for t in asyncio.run(load_tools(principal)))


def test_mcp_client_surface_has_no_finance():
    names = _names(Principal(role=Role.CLIENT, customer_id=1))
    assert "get_my_usage_summary" in names
    assert "get_platform_revenue" not in names
    assert "get_customer_balance" not in names


def test_mcp_admin_surface_has_finance():
    names = _names(Principal(role=Role.ADMIN))
    assert {"get_platform_revenue", "get_margin_by_model", "get_provider_health"} <= set(names)
