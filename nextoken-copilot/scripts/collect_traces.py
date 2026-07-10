"""Collect router traces over a question battery.

Runs a broad set of role-tagged questions through the multi-agent graph and
appends one JSONL trace per request (question -> plan, routes, tools, latency).
Those traces are the training data for the fine-tuned router.

    # bootstrap labels (offline, deterministic sandbox heuristics)
    python -m scripts.collect_traces data/traces.jsonl

    # teacher labels (strong model) — set your key first:
    COPILOT_LLM_MODE=openai COPILOT_LLM_MODEL=gpt-4o COPILOT_LLM_API_KEY=sk-... \
        python -m scripts.collect_traces data/traces_teacher.jsonl

Collection always uses local tools mode so the full 20-tool surface (all four
workers) is exercised, giving the router complete routing coverage.
"""
from __future__ import annotations

import os
import sys

# Full-coverage routing set; traces are what we learn from.
BATTERY: list[tuple[str, int | None, str]] = [
    # ---- client (customer_id = 1) ----
    ("client", 1, "how much have I spent this month and on which models"),
    ("client", 1, "what is my balance"),
    ("client", 1, "list my api keys and their rate limits"),
    ("client", 1, "show my last 10 api calls"),
    ("client", 1, "what is my daily spend trend over the last 2 weeks"),
    ("client", 1, "how much would 100000 input tokens on nxt-gpt-4o cost me"),
    ("client", 1, "what models are available and their prices"),
    ("client", 1, "show my invoices and recent charges"),
    ("client", 1, "what is my balance and show my recent calls"),
    ("client", 1, "how much did I spend on nxt-o3"),
    ("client", 1, "what is my usage summary and am I near my rate limit"),
    ("client", 1, "give me the price list"),
    # ---- support ----
    ("support", None, "show the usage summary for customer 2"),
    ("support", None, "what is customer 3's balance"),
    ("support", None, "list the api keys for customer 2"),
    ("support", None, "find the customer with email bob"),
    ("support", None, "what are the top models by usage this month"),
    ("support", None, "show recent calls for customer 2"),
    ("support", None, "look up customer 2 and show their usage summary"),
    ("support", None, "which models are the most used across all customers"),
    ("support", None, "what is the balance and recent usage for customer 3"),
    # ---- admin ----
    ("admin", None, "what is our revenue and gross margin this month"),
    ("admin", None, "show the margin by model"),
    ("admin", None, "how healthy are the providers"),
    ("admin", None, "what is our upstream cost by provider"),
    ("admin", None, "give me the platform summary"),
    ("admin", None, "revenue, margin by model, and provider health"),
    ("admin", None, "what is the busiest model and our margin on it"),
    ("admin", None, "show platform revenue and the provider costs"),
    ("admin", None, "what are our total earnings and error rates by provider"),
    ("admin", None, "show usage for customer 1 and our overall margin"),
]


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "data/traces.jsonl"
    os.environ["COPILOT_TOOLS_MODE"] = "local"
    os.environ["COPILOT_TRACE_FILE"] = out
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "w").close()  # fresh file

    from nextoken_copilot.agents import ask
    from nextoken_copilot.principal import Principal, Role

    ok = 0
    for role, customer_id, question in BATTERY:
        try:
            ask(Principal(role=Role(role), customer_id=customer_id, email="collect@local"), question)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  skip [{role}] {question[:40]!r}: {exc}")
    print(f"collected {ok}/{len(BATTERY)} traces -> {out}  (mode={os.getenv('COPILOT_LLM_MODE', 'sandbox')})")


if __name__ == "__main__":
    main()
