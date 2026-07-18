"""Turn request traces into a router fine-tuning dataset.

The graph appends one JSONL trace per request when COPILOT_TRACE_FILE is set
(question -> plan, routes, tools). This script converts those traces into
instruction/response pairs for the three router decisions we want to distill
into a small model:

  * plan   : question              -> newline-separated sub-tasks
  * route  : sub-task + options    -> one worker name
  * tools  : sub-task              -> tool name(s) called

    COPILOT_TRACE_FILE=traces.jsonl python -m scripts.ask ...   # collect
    python -m scripts.build_ft_dataset traces.jsonl ft_router.jsonl

Run the collection step in gateway mode with a strong model so the labels are
"teacher" quality, then QLoRA-tune a 1.5-3B model on the output (see
OPTIMIZATION.md).

If the only live model available is the small student itself (the $0 Ollama
stack), its executed routes are too flaky to be labels. Pass its trace file
via --augment instead: only the ROUTE pairs are taken — the student's
realistic sub-task phrasings — and each is relabeled by the deterministic
sandbox keyword router (skipped when the heuristic has no signal). Plans and
tool picks from the student are discarded.

    python -m scripts.build_ft_dataset traces.jsonl ft_router.jsonl \
        --augment traces_gateway.jsonl
"""
from __future__ import annotations

import json
import sys

from nextoken_copilot.models.sandbox import WORKER_HINTS, _score

SYS_PLAN = "You are an orchestrator. Break the user's question into 1-3 short, independent sub-tasks, one per line."
SYS_ROUTE = "You are a supervisor. Choose exactly one worker for the sub-task. Reply with only the worker name."
SYS_TOOLS = "You are a worker. Name the tool(s) needed for the sub-task, comma-separated."


def _pair(system: str, user: str, output: str) -> dict:
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": output},
    ]}


# Fixed union of all workers, matching what graph.py sends when the FT router
# is active. Training on a per-role options string caused a train/serve
# mismatch (and `planner` postdates the first dataset entirely).
ROUTE_OPTIONS = ["usage", "billing", "catalog", "finance", "help", "planner"]

# Hand-audited label corrections (2026-07-17, after the v2 adapter's in-sample
# errors exposed relabeler noise). Keyed by lowercase task-text prefix.
ROUTE_FIXES: dict[str, str] = {
    "what is my balance after spending": "billing",
    "how many tokens are remaining in my account": "billing",
    "what is my current balance": "billing",
    "what is the balance after spending": "billing",
    "how many tokens does customer 3 currently hold": "billing",
    "what are the limits for my api usage": "billing",
    "how much would 100000 input tokens": "billing",
    "what is the cost for 100,000 requests": "billing",
    "can you guide me on how to set up api key authorization": "help",
    "what authentication method": "help",
    "how can i obtain an api token": "help",
    "what does this error indicate": "help",
    "what are the steps to call a model": "help",
    "what resources are available for getting started": "help",
    "how can i find tutorials": "help",
    "where can i access support materials": "help",
    "how many tokens does nxt-gpt-4o cost": "catalog",
    "how many tokens does each model cost": "catalog",
    "what criteria does nextoken use to evaluate provider health": "finance",
    "how is provider health measured": "finance",
    "what are our total earnings": "finance",
    "what are the margins for customer 1": "finance",
    "which models are the most used across all customers": "usage",
    "which models did customer 2 use": "usage",
}

# Genuinely ambiguous phrasings and question-back plan artifacts: not labels.
ROUTE_DROPS = [
    "recent charges",
    "please provide any additional information",
    "are there any specific api keys you're looking for",
    "who is the customer 2",
]

# The planner worker postdates the collected traces; give the router a few
# canonical phrasings (its worker step is deterministic, so recall > precision).
PLANNER_TASKS = [
    "Suggest an API usage plan for a $20 monthly budget",
    "suggest a usage plan",
    "help me plan my api budget for next month",
    "how should I budget my token usage",
    "recommend a spending plan that fits my budget",
    "optimize my usage plan",
]


def _route_label(task: str, label: str) -> str | None:
    """Apply hand-audited fixes/drops to a route label. None = drop the pair."""
    t = task.strip().lower()
    for frag in ROUTE_DROPS:
        if frag in t:
            return None
    for prefix, fixed in ROUTE_FIXES.items():
        if t.startswith(prefix):
            return fixed
    return label


def _relabeled_route_pairs(trace_path: str, workers: list[str]) -> list[dict]:
    """Route pairs from a student-model trace file, relabeled by the sandbox
    keyword router. The student's phrasing is kept; its (flaky) route is not.
    Strict-margin rule: a tie between workers is ambiguity, not a label —
    skip it (dict-order tie-breaking is how v2's label noise got in)."""
    pairs = []
    with open(trace_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            t = json.loads(line)
            for sub in t.get("plan", []):
                scores = sorted((_score(sub, WORKER_HINTS[w]), w)
                                for w in workers if w in WORKER_HINTS)
                if not scores or scores[-1][0] == 0:
                    continue
                if len(scores) > 1 and scores[-1][0] == scores[-2][0]:
                    continue  # tie -> ambiguous -> not a label
                label = _route_label(sub, scores[-1][1])
                if label:
                    pairs.append(_pair(SYS_ROUTE, f"options={','.join(ROUTE_OPTIONS)} :: task={sub}", label))
    return pairs


def build(trace_path: str, out_path: str, augment_path: str | None = None) -> None:
    rows, seen = [], set()
    workers = ["usage", "billing", "catalog", "finance", "help"]
    with open(trace_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            t = json.loads(line)
            plan, routes, tools = t.get("plan", []), t.get("routes", []), t.get("tools", [])
            if not plan:
                continue
            key = (t.get("question"), tuple(plan), tuple(routes))
            if key in seen:
                continue
            seen.add(key)

            rows.append(_pair(SYS_PLAN, t["question"], "\n".join(plan)))
            for i, sub in enumerate(plan):
                if i < len(routes):
                    label = _route_label(sub, routes[i])
                    if label:
                        rows.append(_pair(SYS_ROUTE, f"options={','.join(ROUTE_OPTIONS)} :: task={sub}", label))
            if tools:
                rows.append(_pair(SYS_TOOLS, plan[0], ", ".join(dict.fromkeys(tools))))

    for task in PLANNER_TASKS:
        rows.append(_pair(SYS_ROUTE, f"options={','.join(ROUTE_OPTIONS)} :: task={task}", "planner"))

    n_aug = 0
    if augment_path:
        existing = {json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows}
        for p in _relabeled_route_pairs(augment_path, workers):
            key = json.dumps(p, ensure_ascii=False, sort_keys=True)
            if key not in existing:
                existing.add(key)
                rows.append(p)
                n_aug += 1

    with open(out_path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    aug = f" (+{n_aug} relabeled route pairs from {augment_path})" if augment_path else ""
    print(f"{len(rows)} training pairs from {len(seen)} unique traces{aug} -> {out_path}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--augment"]
    if "--augment" in sys.argv:
        if len(args) != 3:
            raise SystemExit("usage: python -m scripts.build_ft_dataset <traces.jsonl> <out.jsonl> --augment <student_traces.jsonl>")
        build(args[0], args[1], augment_path=args[2])
    else:
        if len(args) != 2:
            raise SystemExit("usage: python -m scripts.build_ft_dataset <traces.jsonl> <out.jsonl> [--augment <student_traces.jsonl>]")
        build(args[0], args[1])
