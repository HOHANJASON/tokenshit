"""The multi-agent graph: orchestrator -> supervisor -> workers -> aggregator.

    START
      v
   orchestrator      plan the question into 1-3 sub-tasks
      v
   supervisor  <-----------------+   route each sub-task to one worker (by role)
      v  (conditional)           |
   worker  ---------------------- +   a role-scoped ReAct agent runs MCP tools
      v  (when all steps done)
   aggregator        compose one final answer from the findings
      v
     END

Worker agents are built *per request* with only the MCP tools the principal's
role exposes, so the set of reachable tools is the role's permission boundary.
"""
from __future__ import annotations

import json
import re
import time
import warnings
from datetime import datetime, timezone
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

with warnings.catch_warnings():  # create_react_agent moved in langgraph v1; the prebuilt still works
    warnings.simplefilter("ignore")
    from langgraph.prebuilt import create_react_agent

from ..config import settings
from ..guard import enforce
from ..models.factory import get_chat_model
from ..principal import Principal
from .mcp_loader import load_tools

# Which tools each worker may use (intersected at runtime with the role's tools).
# Ordered: the first usable tool is the worker's safe default (no required args).
WORKER_TOOLS: dict[str, list[str]] = {
    "usage": [
        "get_my_usage_summary", "get_my_usage_timeseries", "get_my_recent_calls",
        "get_top_models_by_usage", "get_customer_usage_summary", "get_customer_recent_calls",
        "secure_get_usage",  # remote (NexToken backend)
    ],
    "billing": [
        "get_my_balance", "get_my_invoices", "list_my_api_keys",
        "get_customer_balance", "list_customer_api_keys", "find_customer", "estimate_cost",
        "secure_get_customer_balance", "secure_get_api_keys", "secure_list_customers",  # remote
    ],
    "catalog": ["get_model_catalog", "get_public_pricing", "estimate_cost"],
    "finance": [
        "get_platform_revenue", "get_margin_by_model", "get_provider_costs",
        "get_provider_health", "get_platform_summary",
    ],
}


class State(TypedDict):
    question: str
    plan: list[str]
    step: int
    route: str
    results: list[dict]
    answer: str


def _flatten(content) -> str:
    """MCP tool results arrive as content blocks; collapse them to text."""
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        ).strip()
    return str(content)


def _clean_plan_line(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()


def _build_workers(principal: Principal, model, tools):
    """Create one ReAct agent per worker that has at least one allowed tool."""
    by_name = {t.name: t for t in tools}
    agents = {}
    for worker, names in WORKER_TOOLS.items():
        subset = [by_name[n] for n in names if n in by_name]
        if subset:
            agents[worker] = create_react_agent(model, subset)
    return agents


async def answer(principal: Principal, question: str, token: str | None = None, context: str = "") -> dict:
    """Run the full multi-agent pipeline for one authenticated request.

    ``token`` is the caller's backend JWT, used only in remote tools mode —
    it flows through to the NexToken backend, which enforces RBAC and audits
    every tool call server-side. ``context`` is prior conversation turns
    (Context layer) used by the planner and aggregator for follow-up questions.
    """
    started = time.perf_counter()
    ctx = f"\n\nRecent conversation (context for follow-ups, don't repeat it):\n{context}" if context else ""
    # Model tiering: a cheap/small (optionally fine-tuned) router handles
    # planning, routing and tool-selection; a stronger model writes the answer.
    router_model = get_chat_model("router")
    answer_model = get_chat_model("answer")
    if settings.tools_mode == "remote":
        from ..remote_tools import load_remote_tools

        tools = await load_remote_tools(token=token)
    else:
        tools = await load_tools(principal)
    worker_agents = _build_workers(principal, router_model, tools)
    worker_names = list(worker_agents)

    def orchestrator(state: State) -> dict:
        prompt = [
            SystemMessage(content="You are an orchestrator. Break the user's question into 1-3 "
                                  "short, independent sub-tasks, one per line." + ctx),
            HumanMessage(content=f"PLAN:: question={state['question']}"),
        ]
        resp = router_model.invoke(prompt)
        plan = [_clean_plan_line(l) for l in resp.content.splitlines() if l.strip()]
        return {"plan": plan or [state["question"]], "step": 0, "results": []}

    def supervisor(state: State) -> dict:
        if state["step"] >= len(state["plan"]):
            return {"route": "__done__"}
        subtask = state["plan"][state["step"]]
        prompt = [
            SystemMessage(content="You are a supervisor. Choose exactly one worker to handle the "
                                  "sub-task. Reply with only the worker name."),
            HumanMessage(content=f"ROUTE:: options={','.join(worker_names)} :: task={subtask}"),
        ]
        choice = (router_model.invoke(prompt).content or "").strip().split()[:1]
        route = choice[0] if choice and choice[0] in worker_agents else (worker_names[0] if worker_names else "__done__")
        return {"route": route}

    async def worker(state: State) -> dict:
        subtask = state["plan"][state["step"]]
        agent = worker_agents[state["route"]]
        out = await agent.ainvoke({"messages": [HumanMessage(content=subtask)]})
        output = _flatten(out["messages"][-1].content)
        tool_names = [
            call["name"]
            for m in out["messages"]
            if getattr(m, "tool_calls", None)
            for call in m.tool_calls
        ]
        result = {"step": state["step"], "worker": state["route"], "subtask": subtask,
                  "output": output, "tools": tool_names}
        return {"results": state["results"] + [result], "step": state["step"] + 1}

    def aggregator(state: State) -> dict:
        prompt = [
            SystemMessage(content="You are a helpful analyst. Using only the findings, write a "
                                  "concise, direct answer for the user. Never invent data." + ctx),
            HumanMessage(content="SUMMARIZE:: " + json.dumps(state["results"])),
        ]
        return {"answer": answer_model.invoke(prompt).content}

    graph = StateGraph(State)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("supervisor", supervisor)
    graph.add_node("worker", worker)
    graph.add_node("aggregator", aggregator)
    graph.add_edge(START, "orchestrator")
    graph.add_edge("orchestrator", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        lambda s: "aggregate" if s["route"] == "__done__" else "work",
        {"work": "worker", "aggregate": "aggregator"},
    )
    graph.add_edge("worker", "supervisor")
    graph.add_edge("aggregator", END)
    app = graph.compile()

    if not worker_agents:  # role with no usable tools — should not happen
        return {"answer": "No tools are available for this role.", "plan": [], "results": []}

    final = await app.ainvoke({"question": question, "plan": [], "step": 0, "route": "", "results": [], "answer": ""})
    metrics = {
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "steps": len(final["results"]),
        "workers": [r["worker"] for r in final["results"]],
        "tools_called": [t for r in final["results"] for t in r.get("tools", [])],
        "tools_mode": settings.tools_mode,
        "llm_mode": settings.llm_mode,
    }
    safe_answer, findings = enforce(principal, final["answer"])
    result = {"answer": safe_answer, "plan": final["plan"], "results": final["results"],
              "workers_available": worker_names, "metrics": metrics,
              "guardrail": {"triggered": bool(findings), "findings": findings}}
    _trace(principal, question, result)
    return result


def _trace(principal: Principal, question: str, result: dict) -> None:
    """Feedback loop: append a JSONL trace per request (off unless configured).

    These traces are the raw dataset for router fine-tuning: (question ->
    plan, routes, tools) tuples plus latency for the optimization work.
    """
    if not settings.trace_file:
        return
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "role": principal.role.value,
            "question": question,
            "plan": result["plan"],
            "routes": [r["worker"] for r in result["results"]],
            "tools": result["metrics"]["tools_called"],
            "latency_ms": result["metrics"]["latency_ms"],
            "tools_mode": result["metrics"]["tools_mode"],
        }
        with open(settings.trace_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # tracing must never break a request
