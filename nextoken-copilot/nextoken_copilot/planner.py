"""Usage-plan layer for the ``planner`` worker.

The security thesis, extended to numbers: **figures come from code, prose
comes from the model.** ``build_usage_plan`` computes a grounded API-usage
plan — spend so far, daily burn, horizon projection, runway against the real
balance, budget fit, per-model efficiency, cheaper-model candidates — entirely
in Python from the customer's own data. The LLM only narrates the JSON it
gets back, so a hallucinated dollar figure is structurally impossible.

Data sources per tools mode:
  * local  — the reference data layer (same RBAC: client-scoped, AccessDenied
             otherwise).
  * remote — the backend's audited assistant surface (``secure_get_usage``,
             ``secure_get_customer_balance``) with the caller's JWT, plus the
             public ``/api/pricing`` ratios. Every fetch lands in
             ``assistant_audit_logs`` like any other tool call.
"""
from __future__ import annotations

import json
from datetime import datetime

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .config import settings
from .principal import Principal, Role

# --------------------------------------------------------------------------- #
# Pure computation (offline-testable, no I/O)
# --------------------------------------------------------------------------- #


def _parse_ts(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def compute_plan(rows: list[dict], balance: float | None = None,
                 pricing: list[dict] | None = None, horizon_days: int = 30,
                 monthly_budget: float | None = None) -> dict:
    """Deterministic usage plan from raw usage-log rows.

    Each row needs: model, charge, input_tokens, output_tokens, and a
    created_at (remote) or time (local) timestamp.
    """
    rows = [r for r in rows if r.get("model")]
    if not rows:
        return {"note": "No API usage found in the window — nothing to plan from yet. "
                        "Suggest starting with the cheapest chat model and revisiting "
                        "after a few days of traffic."}

    stamps = [ts for r in rows if (ts := _parse_ts(r.get("created_at") or r.get("time")))]
    span_days = 1.0
    if len(stamps) >= 2:
        span_days = max((max(stamps) - min(stamps)).total_seconds() / 86400, 1.0)

    per_model: dict[str, dict] = {}
    for r in rows:
        m = per_model.setdefault(r["model"], {"calls": 0, "spend": 0.0, "tokens": 0})
        m["calls"] += 1
        m["spend"] += float(r.get("charge") or 0)
        m["tokens"] += int(r.get("input_tokens") or 0) + int(r.get("output_tokens") or 0)
    for m in per_model.values():
        m["spend"] = round(m["spend"], 6)
        m["eff_cost_per_1k_tokens"] = round(m["spend"] / (m["tokens"] / 1000), 6) if m["tokens"] else None

    total_spend = round(sum(m["spend"] for m in per_model.values()), 6)
    daily_burn = round(total_spend / span_days, 6)
    projected = round(daily_burn * horizon_days, 4)

    plan: dict = {
        "window_days_observed": round(span_days, 1),
        "calls": len(rows),
        "total_spend_usd": total_spend,
        "daily_burn_usd": daily_burn,
        "horizon_days": horizon_days,
        "projected_spend_usd": projected,
        "per_model": per_model,
    }

    recommendations: list[str] = []
    top_model = max(per_model, key=lambda k: per_model[k]["spend"])
    share = per_model[top_model]["spend"] / total_spend if total_spend else 0
    if share > 0.8 and len(per_model) == 1:
        recommendations.append(f"All spend is on {top_model}; fine for now, but route "
                               "latency-tolerant batch work to a cheaper model when volume grows.")

    if balance is not None:
        plan["balance_usd"] = round(balance, 6)
        if daily_burn > 0:
            runway = round(balance / daily_burn, 1)
            plan["runway_days_at_current_burn"] = runway
            if runway < horizon_days:
                recommendations.append(f"Balance covers ~{runway} days at the current burn — "
                                       f"top up about ${max(projected - balance, 0):.2f} to cover "
                                       f"the next {horizon_days} days.")
            else:
                recommendations.append(f"Balance covers ~{runway} days at the current burn — "
                                       "no top-up needed this horizon.")

    if monthly_budget is not None:
        plan["monthly_budget_usd"] = monthly_budget
        scaled = projected * (30 / horizon_days)
        plan["projected_monthly_vs_budget_pct"] = round(100 * scaled / monthly_budget, 1) if monthly_budget else None
        if scaled > monthly_budget:
            recommendations.append(f"Projected monthly spend ${scaled:.2f} EXCEEDS the "
                                   f"${monthly_budget:.2f} budget — move volume to a cheaper "
                                   "model or set per-key RPM/TPM limits.")
        else:
            recommendations.append(f"Projected monthly spend ${scaled:.2f} fits the "
                                   f"${monthly_budget:.2f} budget "
                                   f"({100 * scaled / monthly_budget:.0f}% used).")

    if pricing:
        ratios = {p["model_name"]: p.get("model_ratio") for p in pricing
                  if p.get("endpoint_type") == "chat" and p.get("model_ratio") is not None}
        top_ratio = ratios.get(top_model)
        if top_ratio:
            cheaper = sorted(
                ((name, r) for name, r in ratios.items() if r < top_ratio and name != top_model),
                key=lambda t: t[1])
            if cheaper:
                name, r = cheaper[0]
                plan["cheapest_alternative"] = {
                    "model": name,
                    "approx_savings_pct": round(100 * (1 - r / top_ratio)),
                }
                recommendations.append(f"{name} is ~{plan['cheapest_alternative']['approx_savings_pct']}% "
                                       f"cheaper per token than {top_model} (price-ratio basis) — "
                                       "worth an A/B on quality-tolerant traffic.")

    plan["recommendations"] = recommendations
    return plan


# --------------------------------------------------------------------------- #
# Data fetchers (mode-specific)
# --------------------------------------------------------------------------- #


async def _remote_tool(token: str, name: str, arguments: dict | None = None,
                       base_url: str | None = None, transport=None) -> dict:
    async with httpx.AsyncClient(base_url=base_url or settings.backend_url,
                                 timeout=30, transport=transport) as client:
        resp = await client.post("/api/assistant/tools/execute",
                                 headers={"Authorization": f"Bearer {token}"},
                                 json={"tool_name": name, "arguments": arguments or {}})
        resp.raise_for_status()
        return resp.json().get("data", {})


async def _public_pricing(base_url: str | None = None, transport=None) -> list[dict]:
    try:
        async with httpx.AsyncClient(base_url=base_url or settings.backend_url,
                                     timeout=10, transport=transport) as client:
            resp = await client.get("/api/pricing")
            resp.raise_for_status()
            return resp.json().get("data", []) or []
    except Exception:  # noqa: BLE001 — pricing is optional garnish, never fatal
        return []


async def _gather_remote(token: str, horizon_days: int, monthly_budget: float | None,
                         base_url: str | None = None, transport=None) -> dict:
    usage = await _remote_tool(token, "secure_get_usage", base_url=base_url, transport=transport)
    bal = await _remote_tool(token, "secure_get_customer_balance", base_url=base_url, transport=transport)
    pricing = await _public_pricing(base_url=base_url, transport=transport)
    balance = (bal.get("balance") or {}).get("balance") if isinstance(bal.get("balance"), dict) else bal.get("balance")
    return compute_plan(usage.get("usage", []), balance=balance, pricing=pricing,
                        horizon_days=horizon_days, monthly_budget=monthly_budget)


def _gather_local(principal: Principal, horizon_days: int, monthly_budget: float | None) -> dict:
    from . import data_access

    rows = data_access.get_my_recent_calls(principal, limit=500)
    balance = data_access.get_my_balance(principal).get("balance")
    # Local catalog rows -> the ratio shape compute_plan expects (price stands in
    # for the ratio; only relative order matters for the cheaper-model hint).
    pricing = [{"model_name": p["model"], "endpoint_type": "chat",
                "model_ratio": p.get("input_price_per_1k")}
               for p in data_access.get_public_pricing(principal)]
    return compute_plan(rows, balance=balance, pricing=pricing,
                        horizon_days=horizon_days, monthly_budget=monthly_budget)


# --------------------------------------------------------------------------- #
# The tool
# --------------------------------------------------------------------------- #


class _PlanArgs(BaseModel):
    horizon_days: int = Field(30, ge=1, le=365, description="Planning horizon in days (default 30).")
    monthly_budget: float | None = Field(None, ge=0,
                                         description="The customer's monthly budget in USD, if they stated one.")


def load_planner_tools(principal: Principal, token: str | None = None,
                       base_url: str | None = None, transport=None) -> list[StructuredTool]:
    """The planner worker's tool surface. Customer-facing: client role only."""
    if principal.role != Role.CLIENT:
        return []

    async def build_usage_plan(horizon_days: int = 30, monthly_budget: float | None = None) -> str:
        if settings.tools_mode == "remote":
            tok = token or settings.backend_token
            if not tok:
                return json.dumps({"error": "no backend token for the plan data"})
            plan = await _gather_remote(tok, horizon_days, monthly_budget,
                                        base_url=base_url, transport=transport)
        else:
            plan = _gather_local(principal, horizon_days, monthly_budget)
        return json.dumps(plan, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(
            coroutine=build_usage_plan,
            name="build_usage_plan",
            description="ALWAYS call this for any usage-plan, budget, forecast or "
                        "cost-optimization question — it computes the real numbers from the "
                        "customer's own usage data: spend so far, daily burn rate, projected "
                        "spend, runway against the balance, budget fit, per-model cost "
                        "efficiency and cheaper-model suggestions. Every argument is optional: "
                        "call it with no arguments if unsure; pass monthly_budget only when "
                        "the customer stated one.",
            args_schema=_PlanArgs,
        )
    ]
