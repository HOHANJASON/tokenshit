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
"""
from __future__ import annotations

import json
import sys

SYS_PLAN = "You are an orchestrator. Break the user's question into 1-3 short, independent sub-tasks, one per line."
SYS_ROUTE = "You are a supervisor. Choose exactly one worker for the sub-task. Reply with only the worker name."
SYS_TOOLS = "You are a worker. Name the tool(s) needed for the sub-task, comma-separated."


def _pair(system: str, user: str, output: str) -> dict:
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": output},
    ]}


def build(trace_path: str, out_path: str) -> None:
    rows, seen = [], set()
    workers = ["usage", "billing", "catalog", "finance"]
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
                    rows.append(_pair(SYS_ROUTE, f"options={','.join(workers)} :: task={sub}", routes[i]))
            if tools:
                rows.append(_pair(SYS_TOOLS, plan[0], ", ".join(dict.fromkeys(tools))))

    with open(out_path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} training pairs from {len(seen)} unique traces -> {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m scripts.build_ft_dataset <traces.jsonl> <out.jsonl>")
    build(sys.argv[1], sys.argv[2])
