"""Adapter to evaluate NexToken Copilot's tool-calling core on tau-bench.

tau-bench (https://github.com/sierra-research/tau-bench) is a public benchmark
for tool-agent-user interaction in real-world domains (retail, airline). We plug
in the SAME ReAct / tool-calling building block that powers our worker agents,
driven by our pluggable model factory (set ``COPILOT_LLM_MODE=gateway`` to run
it on the NexToken gateway). It measures whether the agent uses tools correctly
and obeys the domain policy — the general-competence analogue of our RBAC
red-team.

Requires a real model (sandbox cannot solve open-domain tasks) and:
    pip install git+https://github.com/sierra-research/tau-bench

NOTE: tau-bench's Python API has shifted across versions; this targets the
``Agent.solve(env, task_index)`` interface. Verify against your install.
"""
from __future__ import annotations

from typing import Any, Optional

from nextoken_copilot.models.factory import get_chat_model

try:  # keep the module importable even when tau-bench is absent
    from tau_bench.agents.base import Agent
    from tau_bench.types import RESPOND_ACTION_NAME, Action, SolveResult
    HAS_TAU_BENCH = True
except Exception:  # pragma: no cover - exercised only without tau-bench
    Agent = object  # type: ignore[assignment,misc]
    RESPOND_ACTION_NAME = "respond"
    HAS_TAU_BENCH = False

SYSTEM = (
    "You are a careful customer-service agent. Use the provided tools to satisfy "
    "the user's request and follow the domain policy exactly. When you have the "
    "final answer for the user, reply in plain text without calling a tool."
)


class NexTokenAgent(Agent):
    """A single tool-calling loop (the same core our workers use) for tau-bench."""

    def __init__(self, tools_info: list[dict], wiki: str, **kwargs: Any) -> None:
        self.tools_info = tools_info
        self.wiki = wiki or ""
        self.model = get_chat_model()

    def solve(self, env, task_index: Optional[int] = None, max_num_steps: int = 30):
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        reset = env.reset(task_index=task_index)
        model = self.model.bind_tools(self.tools_info)
        messages = [
            SystemMessage(content=f"{SYSTEM}\n\n# Domain policy\n{self.wiki}"),
            HumanMessage(content=reset.observation),
        ]
        reward, info, resp = 0.0, {}, None

        for _ in range(max_num_steps):
            ai: AIMessage = model.invoke(messages)
            messages.append(ai)

            if not ai.tool_calls:  # final natural-language reply to the user
                resp = env.step(Action(name=RESPOND_ACTION_NAME, kwargs={"content": ai.content}))
                messages.append(HumanMessage(content=resp.observation))
                reward, info = resp.reward, resp.info
                if resp.done:
                    break
                continue

            for call in ai.tool_calls:
                resp = env.step(Action(name=call["name"], kwargs=call["args"]))
                messages.append(ToolMessage(content=str(resp.observation), tool_call_id=call["id"]))
                reward, info = resp.reward, resp.info
                if resp.done:
                    break
            if resp is not None and resp.done:
                break

        serialized = [m.model_dump() if hasattr(m, "model_dump") else str(m) for m in messages]
        return SolveResult(reward=reward, info=info, messages=serialized, total_cost=0.0)
