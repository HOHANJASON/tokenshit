"""Identity and the role model.

The :class:`Principal` is the *only* source of identity in the system. The
backend builds it from a validated JWT — never from anything the LLM produces.
Every data-access call takes a Principal and scopes its results to what that
role is allowed to see.

``ROLE_TOOLS`` drives *tool sandboxing*: each role's agent is constructed with
only its allowed tools bound, so an out-of-scope tool is not even reachable by
the model (the strongest defence against prompt injection).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    CLIENT = "client"
    SUPPORT = "support"
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    role: Role
    customer_id: int | None = None  # required for CLIENT; None for staff roles
    email: str = ""

    def __post_init__(self) -> None:
        if self.role == Role.CLIENT and self.customer_id is None:
            raise ValueError("CLIENT principals must carry a customer_id")


# Tools available to each role. The CLIENT set is intentionally narrow and
# self-scoped; SUPPORT can read across customers but sees no money/margins;
# ADMIN gets everything (denoted by the wildcard, expanded in tools.py).
ROLE_TOOLS: dict[Role, set[str]] = {
    Role.CLIENT: {
        "get_my_usage_summary",
        "get_my_usage_timeseries",
        "get_my_recent_calls",
        "list_my_api_keys",
        "get_my_balance",
        "get_my_invoices",
        "estimate_cost",
        "get_model_catalog",
        "get_public_pricing",
    },
    Role.SUPPORT: {
        "find_customer",
        "get_customer_usage_summary",
        "get_customer_recent_calls",
        "list_customer_api_keys",
        "get_customer_balance",
        "get_top_models_by_usage",
        "get_model_catalog",
        "get_public_pricing",
        "estimate_cost",
    },
    Role.ADMIN: {"*"},
}
