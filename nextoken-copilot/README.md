# NexToken Copilot

A **multi-agent AI assistant** for the [NexToken](https://github.com/HOHANJASON/tokenshit)
API-reseller platform. Clients, support agents and admins ask questions in
natural language ("how much did I spend this month?", "what's our gross
margin?") and a team of agents answers them over the platform's own data —
**with role-based access control enforced in code, not by the prompt.**

Built to run **fully offline** on a deterministic *sandbox* model (no API key),
then switch to a real model (the NexToken gateway, OpenAI, Anthropic, Bedrock)
with a single env var.

```
                          ┌──────────────────────────────────────────────┐
   POST /assistant/chat   │                ORCHESTRATOR                  │
   (JWT -> Principal) ───► │   plans the question into 1–3 sub-tasks      │
                          └───────────────────┬──────────────────────────┘
                                              ▼
                          ┌──────────────────────────────────────────────┐
                          │                 SUPERVISOR                    │
                          │   routes each sub-task to one worker (by role)│
                          └───────┬───────────┬───────────┬──────────────┘
                                  ▼           ▼           ▼
                            ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
                            │ usage   │ │ billing │ │ catalog │ │ finance │  ◄─ ReAct agents
                            └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘     (role-scoped)
                                 └───────────┴─────┬─────┴───────────┘
                                                   ▼
                                     ┌───────────────────────────┐
                                     │   MCP server (stdio)       │  ◄─ secure boundary
                                     │   role-scoped tool surface │     principal injected
                                     └─────────────┬─────────────┘     via env, not the model
                                                   ▼
                                     ┌───────────────────────────┐
                                     │   RBAC data-access layer   │  ◄─ AccessDenied on any
                                     │   (NexToken schema)        │     out-of-role query
                                     └───────────────────────────┘
                                                   ▼
                                              AGGREGATOR ─► final answer
```

## The security model (three independent layers)

1. **Role-scoped MCP surface.** The MCP server is spawned per request with the
   principal's role baked into its environment, and registers *only* that role's
   tools. A client's agent literally cannot see `get_platform_revenue` — the
   strongest defence against prompt injection ("token sandboxing").
2. **Identity is injected, never modelled.** The principal (role + customer_id)
   comes from the validated JWT and is passed to the MCP server via env vars.
   Self-scoped tools always use *that* `customer_id`; nothing the LLM emits can
   change whose data is read.
3. **Defence in depth in the data layer.** Every data-access function re-checks
   the role and raises `AccessDenied`, and money internals (`upstream_cost`,
   margin, profit) exist only in ADMIN code paths.

### Roles & what they may see

| Data | Client | Support | Admin |
|---|:---:|:---:|:---:|
| Own usage, spend, balance, API keys | ✅ | ✅ (any customer) | ✅ |
| Other customers' usage/balance | ❌ | ✅ | ✅ |
| Upstream cost / margin / profit | ❌ | ❌ | ✅ |
| Provider secrets | ❌ | ❌ | ❌ |

## Quickstart

```bash
make install        # venv + dependencies
make seed           # build the sample SQLite DB (3 customers, 30 days of usage)
make demo           # ask a question as admin
make eval           # offline scorecard (functional + RBAC red-team)
make test           # pytest
make serve          # FastAPI at http://127.0.0.1:8088
```

Ask as any role from the CLI:

```bash
python -m scripts.ask --role client  --customer 1 "how much did I spend and on which models?"
python -m scripts.ask --role support             "show the usage summary for customer 2"
python -m scripts.ask --role admin               "what is our gross margin and margin by model?"
```

Or over HTTP:

```bash
curl -s localhost:8088/assistant/chat -H 'X-Role: client' -H 'X-Customer-Id: 1' \
     -H 'content-type: application/json' -d '{"question":"what is my balance?"}'
```

## Switching off the sandbox model

The agents run on whatever `COPILOT_LLM_MODE` selects — the agent code is
identical for all of them:

| `COPILOT_LLM_MODE` | backend | extra to install |
|---|---|---|
| `sandbox` (default) | deterministic, offline, no key | — |
| `gateway` | NexToken's own `/v1` (dogfood) | `langchain-openai` |
| `openai` | OpenAI | `langchain-openai` |
| `anthropic` | Anthropic | `langchain-anthropic` |
| `bedrock` | Amazon Bedrock | `langchain-aws` |

```bash
export COPILOT_LLM_MODE=gateway
export COPILOT_LLM_BASE_URL=http://127.0.0.1:3100/v1
export COPILOT_LLM_API_KEY=nxt_live_xxx
export COPILOT_LLM_MODEL=nxt-gpt-4o
```

## Remote mode: the live NexToken backend

The backend now ships its own secure assistant surface (`GET /api/assistant/tools`,
audited `POST /api/assistant/tools/execute`, per-role allowlists in system
settings, `assistant_audit_logs`). In remote mode the copilot's agents consume
**that** surface instead of the local reference data layer — the caller's JWT
flows through, and the backend re-enforces RBAC and audits every call
server-side:

```bash
# backend running on :3100 (see ~/Downloads/nextoken-backend)
python -m scripts.ask --remote --token-file /tmp/nxt_customer_token.txt \
    --role client "what is my balance and list my api keys"
```

Or set `COPILOT_TOOLS_MODE=remote` for the API server

- **Offline suite** (`make eval`) — runs now on the sandbox model:
  functional success + an RBAC **red-team** (a client trying to extract admin
  financials / other customers' data). Current: **functional 7/7, red-team
  6/6 — zero leaks.**
- **Public benchmark — τ-bench** (`eval/tau_bench/`) — the same tool-calling
  core evaluated on Sierra's [τ-bench](https://github.com/sierra-research/tau-bench)
  retail/airline tasks. Needs a real model + key; see
  [eval/tau_bench/README.md](eval/tau_bench/README.md).

## Layout

```
nextoken_copilot/
  config.py          env-driven settings (data source, LLM mode)
  principal.py       Role + Principal + ROLE_TOOLS (the permission map)
  db.py              SQLAlchemy mirror of the NexToken schema
  seed.py            sample data generator
  data_access.py     ← the RBAC security boundary (reference impl)
  tools.py           tool registry + role scoping
  mcp_server.py      role-scoped MCP server (principal from env)
  models/
    sandbox.py       deterministic offline chat model
    factory.py       pluggable model selector
  agents/
    mcp_loader.py    spawn MCP server, load tools for a principal
    graph.py         orchestrator → supervisor → workers → aggregator
  auth.py            JWT (NexToken-compatible) → Principal
  api.py             POST /assistant/chat
eval/                offline suite + τ-bench adapter
tests/               pytest (RBAC, tools, MCP surface, graph, API)
```

## How this maps to the NexToken team

This is the **AI-engineer** half. The `data_access.py` layer is a faithful
reference against the NexToken schema; in production the **backend developer**
owns the hardened version (real DB user with row scoping, audit log) and the JWT
issuer — `auth.py` decodes the same HS256 `role`/`sub` token NexToken already
mints. The contract: *the backend exposes role-scoped functions where identity
is server-side; the agents only call them and never decide whose data they see.*

## Status / not yet done

- Read-only (no write actions like top-ups) — by design for v1.
- τ-bench is wired but not run here (needs a key); offline suite is the gate.
- `data_access.py` is a reference impl, to be replaced by the backend's own.
