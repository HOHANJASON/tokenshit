"""Role -> tool scoping (drives the MCP server's exposed surface)."""
from nextoken_copilot.principal import Role
from nextoken_copilot.tools import ALL_TOOLS, tools_for_role


def test_client_surface_excludes_finance_and_cross_customer():
    t = set(tools_for_role(Role.CLIENT))
    assert "get_my_usage_summary" in t
    assert "get_platform_revenue" not in t
    assert "get_customer_balance" not in t


def test_support_cross_customer_but_no_finance():
    t = set(tools_for_role(Role.SUPPORT))
    assert "get_customer_usage_summary" in t
    assert "get_platform_revenue" not in t


def test_admin_surface_is_everything():
    assert set(tools_for_role(Role.ADMIN)) == set(ALL_TOOLS)
