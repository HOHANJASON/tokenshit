# NexToken Copilot — backend integration guide (for Jason)

This describes how the **AI-engineering half** (the multi-agent copilot, José's
part) plugs into the **platform** (your FastAPI backend + frontend). It is the
target we should agree on before wiring it into the real `customer.html`.

Nothing here changes how your gateway, billing, or existing playground chat work.
The copilot is **additive** and talks to your platform only through the
`/api/assistant/*` surface you already ship.

---

## 1. The shape of it

```
   Customer's browser (your customer.html)
        │  ① widget: POST /assistant/chat   (Authorization: Bearer <nex_customer_token>)
        ▼
   Copilot service  (LangGraph: orchestrator → supervisor → workers → aggregator)
        │  ② for each tool the agent needs:
        │     GET  /api/assistant/tools            (Bearer <same customer token>)
        │     POST /api/assistant/tools/execute    (Bearer <same customer token>)
        ▼
   Your backend  → require_assistant_tool(principal, ...) enforces RBAC + writes
                   assistant_audit_logs, then returns role-scoped data.
```

Two boxes, one contract. The agent never sees a database; it only calls the
tools **you** authorize, with the **customer's own token**. RBAC and audit stay
server-side in your code — the security guarantee doesn't move.

- **①** is the only new frontend piece: the drop-in widget
  (`nextoken-copilot-widget.html` in this folder), pasted into `customer.html`.
- **②** already exists in your `app/main.py`
  (`/api/assistant/tools`, `/api/assistant/tools/execute`, guarded by
  `get_principal` + `require_assistant_tool`). No change needed there.

---

## 2. The one thing you own: the auth seam

The copilot authenticates `/assistant/chat` from the **customer's real session
JWT** — the same `localStorage['nex_customer_token']` the console already uses.
The widget sends it as `Authorization: Bearer …`. Identity always rides the
token; it is **never** a role in the prompt.

For that token to be accepted by the copilot, we reconcile a small claim
mismatch (this is the seam — 10 lines, José's side, but it needs your input on
which option you prefer):

| Claim        | Your customer token today | Copilot expects        |
|--------------|---------------------------|------------------------|
| role         | `"customer"`              | `"client"`             |
| customer id  | `sub` (= id, as string)   | `cid` (int)            |
| secret       | your `APP_SECRET`         | `COPILOT_APP_SECRET`   |

**Option A (recommended, least work for you):** the copilot shares your
`APP_SECRET` and maps `customer→client`, `sub→cid` when it decodes the token.
You change nothing; José adds the mapping. The copilot then forwards your
*unchanged* token to `/api/assistant/tools*`, which your `get_principal`
validates exactly as it does today.

**Option B:** your backend also issues a copilot-scoped token (adds `cid`,
`role:"client"`) at login. More explicit, but touches your login path.

Either way, **turn off dev auth in production** (`COPILOT_DEV_AUTH=0`) so the
`X-Role`/`X-Customer-Id` header fallback we used for the local demo is disabled
and only a valid JWT is accepted.

---

## 3. Where the copilot runs (hosting) + CORS

The copilot is a small FastAPI service. It needs an LLM behind it — in the demo
that's a local `qwen2.5:3b` via your own gateway (`model: gateway`), so the
copilot's traffic is billed through NexToken like any other customer call. In
production you'd point it at whatever model you host.

Two deployment shapes — your call:

- **Same-origin (cleanest UX):** mount the copilot's `/assistant/chat` router
  inside your app so the browser calls it relative. Set the widget's
  `COPILOT_BASE = ""`. No CORS, no second hostname.
- **Separate service:** run the copilot on its own host
  (e.g. `copilot.nextoken.ai`). Set `COPILOT_BASE` to that URL and add your
  console's origin to the copilot's `COPILOT_CORS_ORIGINS` (it defaults to `*`
  for dev — lock it down in prod).

---

## 4. Frontend: the drop-in

`nextoken-copilot-widget.html` — paste the whole block into `customer.html` just
before `</body>`. It is framework-free (matches your stack), themed to the gold
palette, and additive (leaves the existing playground chat untouched). It only
renders for a signed-in customer (guards on `nex_customer_token`).

Set the two consts at the top of its `<script>`: `COPILOT_BASE` (§3) and
`TOKEN_KEY` (already `nex_customer_token`).

---

## 5. Production checklist

- [ ] Pick auth Option A or B (§2); share `APP_SECRET` or issue copilot claims.
- [ ] `COPILOT_DEV_AUTH=0` — no header-based identity in prod.
- [ ] Decide hosting (§3): mount vs separate service; set `COPILOT_BASE` + CORS.
- [ ] Keep `/api/assistant/tools*` stable — that's the whole contract.
- [ ] Real LLM host for the answer tier (the demo's 3B model is fine for routing/
      tools but paraphrases loosely; a stronger answer model removes that wobble).
- [ ] (Later) an audited **write** tool, e.g. `create_support_ticket`, so the
      copilot can escalate to a human — same RBAC + audit path as the read tools.

---

## 6. Security — settings + rules for new tools (READ BEFORE ADDING A TOOL)

**Threat model.** RBAC in the tool layer is the primary defence: an agent can only
call the tools its JWT role allows, and your backend re-checks + audits every call.
On top of that the copilot runs an **output guard** (`nextoken_copilot/guard.py`,
runs on every answer) and **ingress sanitisation**. What each threat maps to:

| Risk | Status today | Why |
|------|--------------|-----|
| Remote code / arbitrary tool execution | **Not possible** | The agent surface is 4 **read-only** tools (`secure_get_*`, `secure_list_customers`), whitelisted by `ASSISTANT_TOOL_NAMES` + `require_assistant_tool`. No shell/eval/HTTP tool exists. |
| Sending malicious emails to clients | **Not possible** | No send/notify tool is exposed to the assistant. Your `EmailOutbox` exists but the agent can't reach it. |
| Prompt injection (text or **image**) | **Contained** | RBAC blocks data exfil (red-team 8/8, incl. image-borne). Fencing + input sanitisation reduce steering. Not *prevented* — an injection can still yield a wrong answer within the customer's own scope. |
| Passive phishing (planted link) | **Blocked** | Output link-guard strips any URL whose host isn't allowlisted; obfuscated forms (`hxxp://x[.]co`, full-width, zero-width) are caught via canonicalisation. |
| Internal-data leak (provider/infra/margins) | **Guarded** | RBAC + a forbidden-token scan (Unicode-normalised) refuse answers containing internal identifiers; the aggregator is told never to reveal prompts/tools/providers/infra. |
| Malicious code generation | **Low risk** | Narrow, tool-grounded support agent (not a code assistant); no explicit filter. |

**Config to set in production (copilot service):**
```
COPILOT_DEV_AUTH=0                      # no header identity; real JWT only
COPILOT_CORS_ORIGINS=https://app.nextoken.ai   # not "*"
COPILOT_LINK_ALLOWLIST=nextoken.ai,nextoken.io # hosts the bot may ever link to
COPILOT_FORBIDDEN_TOKENS=openai-main,azure-backup,<your real provider/infra ids>
```
`COPILOT_FORBIDDEN_TOKENS` is **yours to fill** — put every internal identifier a
customer must never see (real provider names, upstream model ids, internal
hostnames, secret prefixes). The guard matches them even if the model outputs
them full-width/zero-width/homoglyphed.

**Rules for ANY new tool you add to `/api/assistant/tools` (this is the real
frontier — every tool is a new capability an injected prompt can try to invoke):**
1. **Read-only by default.** A write/action tool (ticket, top-up, email) needs its
   own review — it is where "malicious email / destructive action" risk enters.
2. **Never let the model choose a destination or recipient.** An email/notify tool
   must fix the recipient **server-side to the authenticated customer**; never send
   to a model-supplied address. Prefer **templated** content; if content is
   model-authored, run it through the copilot output guard first.
3. **No free-form execution.** Never expose a tool that runs shell, SQL, code, or
   arbitrary HTTP with model-controlled parameters.
4. **Scope by role + audit.** Add it to `assistant_tools_*` per role, enforce via
   `require_assistant_tool`, and keep the `assistant_audit_logs` row. Rate-limit
   side-effectful tools.

---

## 7. Who owns what

- **José (AI):** the agent graph, workers, the docs/`help` worker, prompts,
  the widget, the output guard + sanitisation, the auth mapping in the copilot.
- **Jason (platform):** the `/api/assistant/*` tool surface + RBAC + audit (done),
  the auth seam decision, hosting/CORS, the model the gateway routes to, and the
  `COPILOT_FORBIDDEN_TOKENS` list (your internal identifiers).

The demo (copilot answering a customer's balance from inside the real console,
via `secure_get_customer_balance` on the gateway, audited) already proves the
end-to-end path on a $0 local stack. This doc is what makes it production.
