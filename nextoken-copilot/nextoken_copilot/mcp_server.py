"""MCP server exposing the NexToken tools — the secure boundary in MCP form.

The principal (role + customer_id) is read from the environment at startup. The
trusted agent runtime sets those env vars when it spawns this server over stdio,
so identity is fixed by the runtime and can never be supplied by the model. Only
the tools allowed for that role are registered, so the MCP surface is itself
role-scoped.

Run standalone:  COPILOT_PRINCIPAL_ROLE=admin python -m nextoken_copilot.mcp_server
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from . import data_access as da
from .principal import Principal, Role
from .tools import tools_for_role


def _principal_from_env() -> Principal:
    role = Role(os.environ.get("COPILOT_PRINCIPAL_ROLE", "client"))
    raw_cid = os.environ.get("COPILOT_PRINCIPAL_CUSTOMER_ID") or ""
    customer_id = int(raw_cid) if raw_cid.isdigit() else None
    return Principal(role=role, customer_id=customer_id, email=os.environ.get("COPILOT_PRINCIPAL_EMAIL", ""))


P = _principal_from_env()
mcp = FastMCP("nextoken-copilot")


# --- CLIENT (self-scoped; identity injected, never an argument) ------------
def get_my_usage_summary(days: int = 30) -> dict:
    """Totals and per-model breakdown of YOUR usage and spend over N days."""
    return da.get_my_usage_summary(P, days=days)


def get_my_usage_timeseries(days: int = 30) -> dict:
    """YOUR daily call count and spend over N days."""
    return da.get_my_usage_timeseries(P, days=days)


def get_my_recent_calls(limit: int = 10) -> list:
    """YOUR most recent API calls (model, tokens, charge, status, latency)."""
    return da.get_my_recent_calls(P, limit=limit)


def list_my_api_keys() -> list:
    """YOUR API keys (prefix and limits only — never the secret)."""
    return da.list_my_api_keys(P)


def get_my_balance() -> dict:
    """YOUR current account balance."""
    return da.get_my_balance(P)


def get_my_invoices(limit: int = 20) -> list:
    """YOUR recent ledger entries (top-ups and charges)."""
    return da.get_my_invoices(P, limit=limit)


# --- SUPPORT (cross-customer; no cost/margin) ------------------------------
def find_customer(query: str) -> list:
    """Find customers by email substring."""
    return da.find_customer(P, query=query)


def get_customer_usage_summary(customer_id: int, days: int = 30) -> dict:
    """Usage and spend summary for a specific customer."""
    return da.get_customer_usage_summary(P, customer_id, days=days)


def get_customer_recent_calls(customer_id: int, limit: int = 10) -> list:
    """Most recent API calls for a specific customer."""
    return da.get_customer_recent_calls(P, customer_id, limit=limit)


def list_customer_api_keys(customer_id: int) -> list:
    """API keys (prefix + limits) for a specific customer."""
    return da.list_customer_api_keys(P, customer_id)


def get_customer_balance(customer_id: int) -> dict:
    """Account balance for a specific customer."""
    return da.get_customer_balance(P, customer_id)


def get_top_models_by_usage(days: int = 30, limit: int = 10) -> list:
    """Most-used models across all customers (calls, tokens, revenue)."""
    return da.get_top_models_by_usage(P, days=days, limit=limit)


# --- PUBLIC -----------------------------------------------------------------
def get_model_catalog() -> list:
    """Available models and their customer prices (no upstream cost)."""
    return da.get_model_catalog(P)


def get_public_pricing() -> list:
    """Public price list (customer-facing prices only)."""
    return da.get_public_pricing(P)


def estimate_cost(model: str, input_tokens: int, output_tokens: int = 0) -> dict:
    """Estimate the customer price of a call for a model and token counts."""
    return da.estimate_cost(P, model, input_tokens, output_tokens)


# --- ADMIN (finance: cost, margin, profit) ---------------------------------
def get_platform_revenue(days: int = 30) -> dict:
    """Platform revenue, upstream cost and gross margin over N days."""
    return da.get_platform_revenue(P, days=days)


def get_margin_by_model(days: int = 30) -> list:
    """Per-model revenue, upstream cost and margin."""
    return da.get_margin_by_model(P, days=days)


def get_provider_costs(days: int = 30) -> list:
    """Upstream spend grouped by provider."""
    return da.get_provider_costs(P, days=days)


def get_provider_health(days: int = 7) -> list:
    """Per-provider call volume and error rate."""
    return da.get_provider_health(P, days=days)


def get_platform_summary(days: int = 30) -> dict:
    """High-level platform KPIs (customers, calls, revenue, margin)."""
    return da.get_platform_summary(P, days=days)


WRAPPERS = {
    fn.__name__: fn
    for fn in [
        get_my_usage_summary, get_my_usage_timeseries, get_my_recent_calls,
        list_my_api_keys, get_my_balance, get_my_invoices,
        find_customer, get_customer_usage_summary, get_customer_recent_calls,
        list_customer_api_keys, get_customer_balance, get_top_models_by_usage,
        get_model_catalog, get_public_pricing, estimate_cost,
        get_platform_revenue, get_margin_by_model, get_provider_costs,
        get_provider_health, get_platform_summary,
    ]
}

# Register only what this role is allowed to use.
for _name in tools_for_role(P.role):
    _fn = WRAPPERS[_name]
    mcp.tool(name=_name, description=(_fn.__doc__ or "").strip())(_fn)


if __name__ == "__main__":
    mcp.run(transport="stdio")
