"""Output guardrail — a final safety net on the aggregated answer.

Input-side tool scoping is the primary defence (a role's agent can't call a tool
it isn't allowed). This is defence in depth for the day a *real* model writes the
prose: it scans the finished answer for field names a role must never receive and,
if any slipped through, replaces the answer with a safe refusal. It never weakens
tool-level RBAC — it only catches leaks that reached the text.

The forbidden tokens are stable internal field names that appear only in
admin-finance tool results, so this does not false-positive on ordinary prose.
"""
from __future__ import annotations

from .principal import Principal, Role

_FORBIDDEN: dict[Role, list[str]] = {
    Role.CLIENT: ["upstream_cost", "gross_margin", "margin_pct", "api_key_encrypted"],
    Role.SUPPORT: ["upstream_cost", "gross_margin", "margin_pct", "api_key_encrypted"],
    Role.ADMIN: ["api_key_encrypted"],
}

_REFUSAL = (
    "I can only share data your role is allowed to see, so I can't include that. "
    "Ask about the information available to your account and I'll help."
)


def scan(role: Role, text: str) -> list[str]:
    low = (text or "").lower()
    return [tok for tok in _FORBIDDEN.get(role, []) if tok.lower() in low]


def enforce(principal: Principal, answer: str) -> tuple[str, list[str]]:
    """Return (safe_answer, findings). If findings is non-empty the answer was refused."""
    findings = scan(principal.role, answer)
    return (_REFUSAL if findings else answer), findings
