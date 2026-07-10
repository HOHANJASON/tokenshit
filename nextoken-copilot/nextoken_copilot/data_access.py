"""The secure RBAC data-access layer — the security boundary of the system.

Every function takes a :class:`Principal` and scopes its result to exactly what
that role may see. Two rules are enforced here and never delegated to the LLM:

1. **Identity is fixed by the Principal.** Self-scoped (``*_my_*``) functions
   always use ``principal.customer_id``; any id the model might invent is
   ignored.
2. **Money is layered.** Clients/support never receive ``upstream_cost`` or
   margin. Only ADMIN functions expose platform cost, margin and profit.

``AccessDenied`` is raised if a role calls a function it is not entitled to,
so the rules hold even if tool-binding upstream were bypassed (defence in
depth). This module would be owned/hardened by the backend developer; here it
is a faithful reference implementation against the NexToken schema.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import case, func, select

from .config import settings
from .db import ApiKey, Customer, Ledger, ModelConfig, Provider, SessionLocal, UsageLog
from .principal import Principal, Role


class AccessDenied(PermissionError):
    """Raised when a principal calls a function outside its role."""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _require(principal: Principal, *roles: Role) -> None:
    if principal.role not in roles:
        raise AccessDenied(f"Role '{principal.role.value}' may not perform this action")


def _f(value) -> float:
    return round(float(value or 0), 6)


def _since(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=max(1, min(int(days), 365)))


def _cap(limit: int) -> int:
    return max(1, min(int(limit), settings.max_rows))


def _customer_or_raise(db, customer_id: int) -> Customer:
    cust = db.get(Customer, int(customer_id))
    if cust is None:
        raise ValueError(f"No customer with id {customer_id}")
    return cust


# --------------------------------------------------------------------------- #
# shared, customer-scoped implementations (money = customer-facing only)
# --------------------------------------------------------------------------- #
def _usage_summary(db, customer_id: int, days: int) -> dict:
    since = _since(days)
    where = (UsageLog.customer_id == customer_id, UsageLog.created_at >= since)
    calls, itok, otok, spend, errors = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(UsageLog.input_tokens), 0),
            func.coalesce(func.sum(UsageLog.output_tokens), 0),
            func.coalesce(func.sum(UsageLog.charge), 0),
            func.coalesce(func.sum(case((UsageLog.status >= 400, 1), else_=0)), 0),
        ).where(*where)
    ).one()
    by_model = db.execute(
        select(UsageLog.model, func.count(), func.coalesce(func.sum(UsageLog.charge), 0))
        .where(*where)
        .group_by(UsageLog.model)
        .order_by(func.coalesce(func.sum(UsageLog.charge), 0).desc())
    ).all()
    return {
        "customer_id": customer_id,
        "window_days": int(days),
        "calls": int(calls),
        "errors": int(errors),
        "input_tokens": int(itok),
        "output_tokens": int(otok),
        "total_spend": _f(spend),
        "by_model": [{"model": m, "calls": int(c), "spend": _f(s)} for m, c, s in by_model],
    }


def _usage_timeseries(db, customer_id: int, days: int) -> dict:
    since = _since(days)
    day = func.date(UsageLog.created_at)
    rows = db.execute(
        select(day, func.count(), func.coalesce(func.sum(UsageLog.charge), 0))
        .where(UsageLog.customer_id == customer_id, UsageLog.created_at >= since)
        .group_by(day)
        .order_by(day)
    ).all()
    return {
        "customer_id": customer_id,
        "window_days": int(days),
        "series": [{"date": str(d), "calls": int(c), "spend": _f(s)} for d, c, s in rows],
    }


def _recent_calls(db, customer_id: int, limit: int) -> list[dict]:
    rows = db.execute(
        select(UsageLog)
        .where(UsageLog.customer_id == customer_id)
        .order_by(UsageLog.created_at.desc())
        .limit(_cap(limit))
    ).scalars().all()
    return [
        {
            "time": r.created_at.isoformat(),
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "charge": _f(r.charge),
            "status": r.status,
            "latency_ms": r.latency_ms,
        }
        for r in rows
    ]


def _api_keys(db, customer_id: int) -> list[dict]:
    rows = db.execute(select(ApiKey).where(ApiKey.customer_id == customer_id)).scalars().all()
    # NOTE: only the prefix is ever returned — never a key or hash.
    return [
        {
            "name": k.name,
            "key_prefix": k.key_prefix,
            "active": k.active,
            "rpm_limit": k.rpm_limit,
            "tpm_limit": k.tpm_limit,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        }
        for k in rows
    ]


def _balance(db, cust: Customer) -> dict:
    return {"customer_id": cust.id, "email": cust.email, "balance": _f(cust.balance), "active": cust.active}


def _invoices(db, customer_id: int, limit: int) -> list[dict]:
    rows = db.execute(
        select(Ledger)
        .where(Ledger.customer_id == customer_id)
        .order_by(Ledger.created_at.desc())
        .limit(_cap(limit))
    ).scalars().all()
    return [
        {"time": r.created_at.isoformat(), "kind": r.kind, "amount": _f(r.amount), "note": r.note}
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# CLIENT tools (self-scoped — identity comes from the principal)
# --------------------------------------------------------------------------- #
def get_my_usage_summary(principal: Principal, days: int = 30) -> dict:
    """Totals and per-model breakdown of *your own* usage and spend."""
    _require(principal, Role.CLIENT)
    with SessionLocal() as db:
        return _usage_summary(db, principal.customer_id, days)


def get_my_usage_timeseries(principal: Principal, days: int = 30) -> dict:
    """Your daily call count and spend over the window."""
    _require(principal, Role.CLIENT)
    with SessionLocal() as db:
        return _usage_timeseries(db, principal.customer_id, days)


def get_my_recent_calls(principal: Principal, limit: int = 10) -> list[dict]:
    """Your most recent API calls (model, tokens, charge, status, latency)."""
    _require(principal, Role.CLIENT)
    with SessionLocal() as db:
        return _recent_calls(db, principal.customer_id, limit)


def list_my_api_keys(principal: Principal) -> list[dict]:
    """Your API keys (prefix and limits only — never the secret)."""
    _require(principal, Role.CLIENT)
    with SessionLocal() as db:
        return _api_keys(db, principal.customer_id)


def get_my_balance(principal: Principal) -> dict:
    """Your current account balance."""
    _require(principal, Role.CLIENT)
    with SessionLocal() as db:
        return _balance(db, _customer_or_raise(db, principal.customer_id))


def get_my_invoices(principal: Principal, limit: int = 20) -> list[dict]:
    """Your recent ledger entries (top-ups and charges)."""
    _require(principal, Role.CLIENT)
    with SessionLocal() as db:
        return _invoices(db, principal.customer_id, limit)


# --------------------------------------------------------------------------- #
# SUPPORT tools (cross-customer, but no platform cost / margin)
# --------------------------------------------------------------------------- #
def find_customer(principal: Principal, query: str) -> list[dict]:
    """Find customers by email substring."""
    _require(principal, Role.SUPPORT, Role.ADMIN)
    with SessionLocal() as db:
        rows = db.execute(
            select(Customer.id, Customer.email, Customer.active)
            .where(Customer.email.ilike(f"%{query}%"))
            .limit(_cap(50))
        ).all()
        return [{"customer_id": i, "email": e, "active": a} for i, e, a in rows]


def get_customer_usage_summary(principal: Principal, customer_id: int, days: int = 30) -> dict:
    """Usage and spend summary for a specific customer."""
    _require(principal, Role.SUPPORT, Role.ADMIN)
    with SessionLocal() as db:
        _customer_or_raise(db, customer_id)
        return _usage_summary(db, int(customer_id), days)


def get_customer_recent_calls(principal: Principal, customer_id: int, limit: int = 10) -> list[dict]:
    """Most recent API calls for a specific customer."""
    _require(principal, Role.SUPPORT, Role.ADMIN)
    with SessionLocal() as db:
        _customer_or_raise(db, customer_id)
        return _recent_calls(db, int(customer_id), limit)


def list_customer_api_keys(principal: Principal, customer_id: int) -> list[dict]:
    """API keys (prefix + limits) for a specific customer."""
    _require(principal, Role.SUPPORT, Role.ADMIN)
    with SessionLocal() as db:
        _customer_or_raise(db, customer_id)
        return _api_keys(db, int(customer_id))


def get_customer_balance(principal: Principal, customer_id: int) -> dict:
    """Account balance for a specific customer."""
    _require(principal, Role.SUPPORT, Role.ADMIN)
    with SessionLocal() as db:
        return _balance(db, _customer_or_raise(db, customer_id))


def get_top_models_by_usage(principal: Principal, days: int = 30, limit: int = 10) -> list[dict]:
    """Most-used models across all customers (calls, tokens, revenue) — no cost."""
    _require(principal, Role.SUPPORT, Role.ADMIN)
    with SessionLocal() as db:
        since = _since(days)
        rows = db.execute(
            select(
                UsageLog.model,
                func.count(),
                func.coalesce(func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0),
                func.coalesce(func.sum(UsageLog.charge), 0),
            )
            .where(UsageLog.created_at >= since)
            .group_by(UsageLog.model)
            .order_by(func.count().desc())
            .limit(_cap(limit))
        ).all()
        return [
            {"model": m, "calls": int(c), "tokens": int(t), "revenue": _f(s)}
            for m, c, t, s in rows
        ]


# --------------------------------------------------------------------------- #
# PUBLIC tools (any authenticated role)
# --------------------------------------------------------------------------- #
def get_model_catalog(principal: Principal) -> list[dict]:
    """Available models and their customer prices (no upstream cost)."""
    with SessionLocal() as db:
        rows = db.execute(select(ModelConfig).where(ModelConfig.active.is_(True))).scalars().all()
        return [
            {
                "model": m.public_name,
                "input_price_per_1k": _f(m.input_price),
                "output_price_per_1k": _f(m.output_price),
            }
            for m in rows
        ]


def get_public_pricing(principal: Principal) -> list[dict]:
    """Public price list (alias of the catalog, customer-facing prices only)."""
    return get_model_catalog(principal)


def estimate_cost(principal: Principal, model: str, input_tokens: int, output_tokens: int = 0) -> dict:
    """Estimate the customer price of a call for a model and token counts."""
    with SessionLocal() as db:
        m = db.execute(select(ModelConfig).where(ModelConfig.public_name == model)).scalar_one_or_none()
        if m is None:
            raise ValueError(f"Unknown model '{model}'")
        price = (m.input_price * int(input_tokens) + m.output_price * int(output_tokens)) / 1000
        return {
            "model": model,
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "estimated_price": _f(price),
        }


# --------------------------------------------------------------------------- #
# ADMIN tools (finance: cost, margin, profit, provider economics)
# --------------------------------------------------------------------------- #
def get_platform_revenue(principal: Principal, days: int = 30) -> dict:
    """Platform revenue, upstream cost and gross margin over the window."""
    _require(principal, Role.ADMIN)
    with SessionLocal() as db:
        since = _since(days)
        revenue, cost, calls = db.execute(
            select(
                func.coalesce(func.sum(UsageLog.charge), 0),
                func.coalesce(func.sum(UsageLog.upstream_cost), 0),
                func.count(),
            ).where(UsageLog.created_at >= since)
        ).one()
        margin = _f(revenue) - _f(cost)
        return {
            "window_days": int(days),
            "calls": int(calls),
            "revenue": _f(revenue),
            "upstream_cost": _f(cost),
            "gross_margin": round(margin, 6),
            "margin_pct": round(margin / _f(revenue) * 100, 2) if revenue else 0.0,
        }


def get_margin_by_model(principal: Principal, days: int = 30) -> list[dict]:
    """Per-model revenue, upstream cost and margin (ADMIN-only)."""
    _require(principal, Role.ADMIN)
    with SessionLocal() as db:
        since = _since(days)
        rows = db.execute(
            select(
                UsageLog.model,
                func.coalesce(func.sum(UsageLog.charge), 0),
                func.coalesce(func.sum(UsageLog.upstream_cost), 0),
            )
            .where(UsageLog.created_at >= since)
            .group_by(UsageLog.model)
            .order_by(func.coalesce(func.sum(UsageLog.charge - UsageLog.upstream_cost), 0).desc())
        ).all()
        out = []
        for model, rev, cost in rows:
            margin = _f(rev) - _f(cost)
            out.append({
                "model": model,
                "revenue": _f(rev),
                "upstream_cost": _f(cost),
                "margin": round(margin, 6),
                "margin_pct": round(margin / _f(rev) * 100, 2) if rev else 0.0,
            })
        return out


def get_provider_costs(principal: Principal, days: int = 30) -> list[dict]:
    """Upstream spend grouped by provider (ADMIN-only)."""
    _require(principal, Role.ADMIN)
    with SessionLocal() as db:
        since = _since(days)
        rows = db.execute(
            select(Provider.name, func.coalesce(func.sum(UsageLog.upstream_cost), 0), func.count())
            .select_from(UsageLog)
            .join(ModelConfig, ModelConfig.public_name == UsageLog.model)
            .join(Provider, Provider.id == ModelConfig.provider_id)
            .where(UsageLog.created_at >= since)
            .group_by(Provider.name)
            .order_by(func.coalesce(func.sum(UsageLog.upstream_cost), 0).desc())
        ).all()
        return [{"provider": p, "upstream_cost": _f(c), "calls": int(n)} for p, c, n in rows]


def get_provider_health(principal: Principal, days: int = 7) -> list[dict]:
    """Per-provider call volume and error rate (ADMIN-only)."""
    _require(principal, Role.ADMIN)
    with SessionLocal() as db:
        since = _since(days)
        rows = db.execute(
            select(
                Provider.name,
                Provider.active,
                func.count(),
                func.coalesce(func.sum(case((UsageLog.status >= 400, 1), else_=0)), 0),
            )
            .select_from(UsageLog)
            .join(ModelConfig, ModelConfig.public_name == UsageLog.model)
            .join(Provider, Provider.id == ModelConfig.provider_id)
            .where(UsageLog.created_at >= since)
            .group_by(Provider.name, Provider.active)
        ).all()
        return [
            {
                "provider": p,
                "active": bool(active),
                "calls": int(n),
                "errors": int(err),
                "error_rate_pct": round(int(err) / int(n) * 100, 2) if n else 0.0,
            }
            for p, active, n, err in rows
        ]


def get_platform_summary(principal: Principal, days: int = 30) -> dict:
    """High-level platform KPIs (ADMIN-only)."""
    _require(principal, Role.ADMIN)
    with SessionLocal() as db:
        since = _since(days)
        customers = db.execute(select(func.count()).select_from(Customer)).scalar()
        active_keys = db.execute(select(func.count()).where(ApiKey.active.is_(True))).scalar()
        calls, revenue, cost, errors = db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(UsageLog.charge), 0),
                func.coalesce(func.sum(UsageLog.upstream_cost), 0),
                func.coalesce(func.sum(case((UsageLog.status >= 400, 1), else_=0)), 0),
            ).where(UsageLog.created_at >= since)
        ).one()
        margin = _f(revenue) - _f(cost)
        return {
            "window_days": int(days),
            "customers": int(customers),
            "active_api_keys": int(active_keys),
            "calls": int(calls),
            "errors": int(errors),
            "error_rate_pct": round(int(errors) / int(calls) * 100, 2) if calls else 0.0,
            "revenue": _f(revenue),
            "upstream_cost": _f(cost),
            "gross_margin": round(margin, 6),
        }
