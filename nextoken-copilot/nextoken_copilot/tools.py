"""Registry of all tools and the role -> tools mapping.

The MCP server uses :func:`tools_for_role` to expose *only* the tools a given
role may call, so the MCP surface itself is role-scoped (the model can't see a
tool it isn't allowed to use).
"""
from __future__ import annotations

from . import data_access as da
from .principal import ROLE_TOOLS, Role

# Canonical ordered list of every tool -> its data-access function.
ALL_TOOLS = {
    # client (self-scoped)
    "get_my_usage_summary": da.get_my_usage_summary,
    "get_my_usage_timeseries": da.get_my_usage_timeseries,
    "get_my_recent_calls": da.get_my_recent_calls,
    "list_my_api_keys": da.list_my_api_keys,
    "get_my_balance": da.get_my_balance,
    "get_my_invoices": da.get_my_invoices,
    # support (cross-customer, no money/margin)
    "find_customer": da.find_customer,
    "get_customer_usage_summary": da.get_customer_usage_summary,
    "get_customer_recent_calls": da.get_customer_recent_calls,
    "list_customer_api_keys": da.list_customer_api_keys,
    "get_customer_balance": da.get_customer_balance,
    "get_top_models_by_usage": da.get_top_models_by_usage,
    # public
    "get_model_catalog": da.get_model_catalog,
    "get_public_pricing": da.get_public_pricing,
    "estimate_cost": da.estimate_cost,
    # admin (finance)
    "get_platform_revenue": da.get_platform_revenue,
    "get_margin_by_model": da.get_margin_by_model,
    "get_provider_costs": da.get_provider_costs,
    "get_provider_health": da.get_provider_health,
    "get_platform_summary": da.get_platform_summary,
}


def tools_for_role(role: Role) -> list[str]:
    allowed = ROLE_TOOLS[role]
    if "*" in allowed:
        return list(ALL_TOOLS)
    return [name for name in ALL_TOOLS if name in allowed]
