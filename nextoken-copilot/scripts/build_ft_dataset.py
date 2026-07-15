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


def _relabeled_route_pairs(trace_path: str, workers: list[str]) -> list[dict]:
    """Route pairs from a student-model trace file, relabeled by the sandbox
    keyword router. The student's phrasing is kept; its (flaky) route is not."""
    pairs = []
    with open(trace_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            t = json.loads(line)
            for sub in t.get("plan", []):
                scores = {w: _score(sub, WORKER_HINTS[w]) for w in workers if w in WORKER_HINTS}
                best = max(scores, key=scores.get)
                if scores[best] > 0:
                    pairs.append(_pair(SYS_ROUTE, f"options={','.join(workers)} :: task={sub}", best))
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
                    rows.append(_pair(SYS_ROUTE, f"options={','.join(workers)} :: task={sub}", routes[i]))
            if tools:
                rows.append(_pair(SYS_TOOLS, plan[0], ", ".join(dict.fromkeys(tools))))

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
