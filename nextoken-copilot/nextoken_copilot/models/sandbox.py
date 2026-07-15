"""Deterministic, offline 'sandbox' chat model.

It lets the whole multi-agent system run with no API key and no network, so the
tests, the demo and the RBAC red-team are fully reproducible. It is NOT an LLM —
it makes choices by keyword matching. Swap in a real model by setting
``COPILOT_LLM_MODE`` (see :mod:`nextoken_copilot.models.factory`); the agent code is
identical either way.

It answers four kinds of prompt:
  * worker agents (tools bound) -> emit a tool call, then a final answer
  * orchestrator  ('PLAN::')    -> split a question into sub-tasks
  * supervisor    ('ROUTE::')   -> pick one worker for a sub-task
  * aggregator    ('SUMMARIZE::')-> compose a final answer from the findings
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

# A name fragment found in a tool name -> phrases that should select it.
FRAGMENT_HINTS: dict[str, list[str]] = {
    "usage_timeseries": ["daily", "day by day", "over time", "trend", "timeseries", "per day", "history", "chart"],
    "usage_summary": ["spend", "spent", "usage", "summary", "how much", "consumption", "total", "breakdown", "tokens"],
    "recent_calls": ["recent", "last", "latest", "calls", "requests", "activity"],
    "top_models_by_usage": ["top models", "most used", "popular", "busiest", "ranking"],
    "api_keys": ["api key", "keys", "key", "rpm", "tpm", "limit"],
    "balance": ["balance", "credit", "funds", "left"],
    "invoices": ["invoice", "invoices", "bill", "ledger", "transactions", "payment", "topup", "top-up"],
    "estimate_cost": ["estimate", "quote", "how much would", "price of", "cost of"],
    "model_catalog": ["catalog", "models", "available"],
    "public_pricing": ["pricing", "price list", "prices"],
    "find_customer": ["find", "search", "look up", "lookup", "named", "email"],
    "platform_revenue": ["revenue", "gross margin", "profit", "earnings", "total margin"],
    "platform_summary": ["overview", "kpi", "dashboard", "platform summary", "business health"],
    "margin_by_model": ["margin by model", "margin per model", "profit by model", "margin"],
    "provider_costs": ["provider cost", "upstream cost", "cost by provider", "provider spend"],
    "provider_health": ["provider health", "error rate", "provider status", "failover", "providers"],
    # Remote (NexToken backend) tool names — kept last so local names match first.
    "get_usage": ["usage", "spend", "spent", "calls", "recent", "last", "logs", "consumption", "tokens"],
    "list_customers": ["customers", "all customers", "list customers", "find", "search", "lookup"],
    "search_docs": ["how do", "how to", "integrate", "docs", "documentation", "authenticate",
                    "401", "402", "429", "error", "sdk", "endpoint", "streaming", "guide"],
}

# Worker name -> phrases that route a sub-task to it.
WORKER_HINTS: dict[str, list[str]] = {
    "usage": ["usage", "spend", "spent", "token", "tokens", "calls", "requests", "consumption",
              "activity", "errors", "latency", "traffic", "volume", "most used", "top model",
              "trend", "daily", "history"],
    "billing": ["balance", "invoice", "bill", "ledger", "credit", "payment", "topup", "api key",
                "key", "keys", "limit", "estimate", "quote", "owe", "customer", "customers"],
    "catalog": ["catalog", "pricing", "price list", "price", "available"],
    "finance": ["revenue", "margin", "profit", "upstream", "provider", "economics", "kpi",
                "dashboard", "financial", "overview", "summary", "cost"],
    "help": ["how do", "how to", "integrate", "docs", "documentation", "authenticate",
             "401", "402", "429", "error", "sdk", "endpoint", "streaming", "guide"],
}


def _score(text: str, hints: list[str]) -> int:
    t = text.lower()
    return sum(1 for h in hints if h in t)


def _ai(content: str, tool_calls: list[dict] | None = None) -> ChatResult:
    msg = AIMessage(content=content, tool_calls=tool_calls or [])
    return ChatResult(generations=[ChatGeneration(message=msg)])


def _content_text(content) -> str:
    """Collapse MCP content blocks (or anything) to plain text."""
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        ).strip()
    return str(content)


def _last_user(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            return m.content
    for m in messages:
        if isinstance(m.content, str):
            return m.content
    return ""


def _extract_args(query: str, accepted: set[str]) -> dict[str, Any]:
    """Pull only the args a tool actually accepts out of the natural-language query."""
    args: dict[str, Any] = {}
    q = query.lower()
    if "days" in accepted:
        if m := re.search(r"(\d+)\s*(day|days)\b", q):
            args["days"] = int(m.group(1))
        elif m := re.search(r"(\d+)\s*(week|weeks)\b", q):
            args["days"] = int(m.group(1)) * 7
        elif m := re.search(r"(\d+)\s*(month|months)\b", q):
            args["days"] = int(m.group(1)) * 30
        elif "today" in q:
            args["days"] = 1
        elif "week" in q:
            args["days"] = 7
        elif "month" in q:
            args["days"] = 30
    if "limit" in accepted:
        if m := re.search(r"(?:last|top|recent)\s+(\d+)", q):
            args["limit"] = int(m.group(1))
    if "customer_id" in accepted:
        if m := re.search(r"(?:customer|client|account|id|#)\s*#?\s*(\d+)", q):
            args["customer_id"] = int(m.group(1))
    if "query" in accepted:
        m = re.search(r"[\w.+-]+@[\w.-]+", query)
        args["query"] = m.group(0) if m else query.split()[-1]
    if "model" in accepted:
        if m := re.search(r"(nxt-[\w.-]+)", q):
            args["model"] = m.group(1)
    if "input_tokens" in accepted:
        m = re.search(r"(\d+)\s*input", q)
        args["input_tokens"] = int(m.group(1)) if m else 1000
    if "output_tokens" in accepted:
        if m := re.search(r"(\d+)\s*output", q):
            args["output_tokens"] = int(m.group(1))
    return args


class SandboxChatModel(BaseChatModel):
    """A reproducible, rule-based stand-in for a tool-calling chat model."""

    tool_specs: list = []  # [{"name": str, "args": [str, ...]}]

    @property
    def _llm_type(self) -> str:
        return "nextoken-sandbox"

    def bind_tools(self, tools, **kwargs):
        specs = []
        for t in tools:
            try:
                arg_keys = sorted((t.args or {}).keys())
            except Exception:
                arg_keys = []
            specs.append({"name": t.name, "args": arg_keys})
        return self.model_copy(update={"tool_specs": specs})

    def _pick_tool(self, query: str) -> dict:
        best, best_score = self.tool_specs[0], -1
        for spec in self.tool_specs:
            frag = next((k for k in FRAGMENT_HINTS if k in spec["name"]), None)
            score = _score(query, FRAGMENT_HINTS[frag]) if frag else 0
            if score > best_score:
                best, best_score = spec, score
        return best

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        # (1) worker mode — tools are bound to this model
        if self.tool_specs:
            tool_results = [m for m in messages if isinstance(m, ToolMessage)]
            if tool_results:  # a tool already ran -> finalize
                last = tool_results[-1]
                label = getattr(last, "name", None) or "result"
                return _ai(f"{label}: {_content_text(last.content)}")
            query = _last_user(messages)
            spec = self._pick_tool(query)
            if spec["name"] == "search_docs":  # docs search wants the whole question
                args = {"query": query}
            else:
                args = _extract_args(query, set(spec["args"]))
            call = {"name": spec["name"], "args": args, "id": "call_" + uuid.uuid4().hex[:8], "type": "tool_call"}
            return _ai("", tool_calls=[call])

        user = _last_user(messages)

        # (2) supervisor routing
        if "ROUTE::" in user:
            opts = re.search(r"options=([\w,]+)", user)
            options = [o for o in (opts.group(1).split(",") if opts else []) if o]
            task = re.search(r"task=(.*)", user, re.S)
            task_text = task.group(1) if task else user
            if options:
                return _ai(max(options, key=lambda w: _score(task_text, WORKER_HINTS.get(w, [w]))))
            return _ai("usage")

        # (3) orchestrator planning
        if "PLAN::" in user:
            q = re.search(r"question=(.*)", user, re.S)
            question = (q.group(1) if q else user).strip()
            parts = re.split(r"\s+and also\s+|\s*;\s*|\s+then\s+|\s+and\s+", question)
            parts = [p.strip() for p in parts if len(p.strip()) > 2][:3]
            return _ai("\n".join(parts) if parts else question)

        # (4) aggregator
        if "SUMMARIZE::" in user or "FINDINGS::" in user:
            marker = "SUMMARIZE::" if "SUMMARIZE::" in user else "FINDINGS::"
            payload = user.split(marker, 1)[1].strip()
            try:
                results = json.loads(payload)
                lines = [f"- {r.get('output', '')}" for r in results]
                return _ai("Here is what I found:\n" + "\n".join(lines))
            except Exception:
                return _ai(payload)

        return _ai(user or "OK")
