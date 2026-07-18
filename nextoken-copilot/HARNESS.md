# How NexToken Copilot maps to the agentic-systems harness

The system is built as a proper AI harness, not a single LLM call. This maps
each box of the reference diagram to where it lives in the code, and marks what
is done vs. what is the optimization work (see [OPTIMIZATION.md](OPTIMIZATION.md)).

## Inputs

| Box | Where |
|---|---|
| Data sources | NexToken DB (`usage_logs`, `ledger`, `customers`, …) via the backend |
| APIs & tools | MCP server (local mode) / backend `GET /api/assistant/tools` (remote mode) |
| User input | `POST /assistant/chat` question |
| Business rules | `ROLE_TOOLS` permission map + RBAC data layer + backend `assistant_tools_for_role` |

## AI system (harness)

| Box | Where | Status |
|---|---|---|
| Guardrails & safety | input side: role-scoped tool surface, `AccessDenied`, identity-from-JWT, backend rate-limit + `assistant_audit_logs`. output side: `guard.py` scans the answer for role-forbidden fields | ✅ done, verified live (UI red-team) |
| Evaluation & testing | `eval/suite.py` (functional 7/7 + RBAC red-team 6/6), τ-bench adapter, 23 pytest | ✅ done |
| Orchestration | `agents/graph.py` — orchestrator → supervisor → workers → aggregator | ✅ done |
| LLM(s) | `models/factory.py` — sandbox / gateway / openai / anthropic / bedrock, **router vs answer tiering** | ✅ done |
| Monitoring | per-request `metrics` (latency, steps, tools) surfaced in the UI trace + backend audit log + `/api/monitoring/summary` | ✅ done |
| Optimization | model tiering, fine-tuned router, caching, parallel sub-tasks, token budgets | ◑ tiering done; rest in OPTIMIZATION.md |
| Context layer | tool results feeding the aggregator; conversation memory threaded into planner/aggregator (`api.py` store; `context` in `graph.answer`) | ✅ per-request + short-term memory; long-term (`customer_chat_conversations`) next |

## Web panel

`GET /app` (served by the copilot API) is a role-aware chat panel: role switcher,
the **agent trace** (plan → worker → tools) shown per answer, latency metrics, a
guardrail badge, and graceful 401/403/429 handling. `make serve` then open
`http://127.0.0.1:8088/app`. Same-origin to the copilot; CORS is open in dev so
it can also be embedded in the NexToken console. **Remaining UI gap: token
streaming** (answers currently arrive in one lump).

## Outcomes

- **Reliable** — deterministic sandbox for CI; graceful degradation on tool 403; backend failover/cooldown.
- **Scalable** — stateless per request; each tool call is an independent audited API call; Postgres/Redis ready.
- **Secure** — three-layer RBAC (role-scoped surface + injected identity + `AccessDenied`), enforced *and audited* server-side. Proven with a live red-team.
- **Measurable** — `metrics` on every response, JSONL request traces, backend audit CSV export, and the eval scorecard.

## Feedback loop (measure → learn → improve)

`COPILOT_TRACE_FILE` appends a JSONL trace per request (question → plan →
routes → tools → latency). Those traces are:
- **Measure** — latency/routing/tool telemetry.
- **Learn** — `scripts/build_ft_dataset.py` turns them into a router training set.
- **Improve** — QLoRA-tune a small router model, point `COPILOT_ROUTER_MODEL` at
  it, re-run the eval gate. Loop closes.
