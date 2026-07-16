# Fine-tuning & inference optimization

This is the "Optimization" box of the harness. The multi-agent design makes
**many small, structured LLM calls** per request — one plan, one route per
sub-task, one tool-selection per worker step, and one final answer. That shape
is ideal for optimization: distill the cheap-but-frequent decisions into a small
fine-tuned model, and reserve a strong model only for the final prose.

Constraints (from the existing setup): training runs on Kaggle **2×T4** (the
M2 8 GB Mac can't train); Mac inference via MLX/Ollama; serving/benchmarking ties
into the existing vLLM + Grafana lab.

---

## 1. Fine-tuning — router distillation

**Goal:** replace the hand-written sandbox heuristics (and expensive large-model
routing) with one small **fine-tuned router** that does plan + route +
tool-selection.

**Why it works:** these decisions have tiny output spaces (1–3 sub-tasks; one of
4 worker names; a tool name from a short list). A 1.5–3 B model learns them fast
and runs ~10–50× cheaper/faster than a frontier model.

**Pipeline (already wired):**
1. **Collect** — run in gateway mode with a strong *teacher* model and
   `COPILOT_TRACE_FILE=traces.jsonl`. Every request logs `question → plan →
   routes → tools`. Drive it with a broad question battery per role.
2. **Build dataset** — `python -m scripts.build_ft_dataset traces.jsonl ft_router.jsonl`
   emits instruction pairs for the three tasks (plan / route / tools). Target
   ~1–3 k pairs; balance across roles and multi-part questions.
3. **Train (Kaggle 2×T4)** — QLoRA (4-bit) LoRA adapters on a small base
   (Qwen2.5-1.5B/3B-Instruct or Llama-3.2-1B/3B-Instruct), 2–3 epochs. Fits a T4
   comfortably in 4-bit.
4. **Serve** — merge/keep the adapter; run it via vLLM (OpenAI-compatible) or MLX
   on Mac. Point `COPILOT_ROUTER_MODEL` at it, keep `COPILOT_ANSWER_MODEL` on the
   strong model.
5. **Gate** — the FT router must keep `make eval` green (functional 7/7, red-team
   6/6) and match teacher routing on a held-out split before it ships.

**Payoff:** most tokens per request move from a frontier model to a small local
one; routing becomes offline-capable; the sandbox heuristics become a learned
model with the same interface.

### Run log — v1 (2026-07-16, Kaggle 2×T4, Qwen2.5-1.5B NF4)

Trained on the 212-pair dataset (126 sandbox-labeled + 86 relabeled live-student
phrasings), **full-text loss, 3 epochs**. Merged → GGUF q8_0 → Ollama
(`nxt-router-ft`) → gateway model `nxt-router` (wired by
`train/wire_router.sh`). Probed the two distilled tasks separately:

| Task | Result |
|---|---|
| **plan** | learned cleanly — compound questions → exact sub-tasks, one-thing questions stay whole (the live 3B's over-splitting is gone in the adapter) |
| **route** | collapsed — answers `billing` for every input, despite `usage` being the majority label (58 vs 31 of 138) |

**Diagnosis:** full-text loss. Plan answers are 10–20 supervised tokens; route
answers are **one token** at the end of a ~60-token prompt, so across ~40
optimizer steps the route mapping got almost no gradient. Not class imbalance —
a loss-masking problem.

**v2 recipe (committed, not yet run):** completion-only loss (prompt labels
`-100`, `DataCollatorForSeq2Seq`), 8 epochs. Expect in-sample route accuracy
>90% (the notebook's accuracy cell gates the 1.5 GB download). Until v2 is
trained, `COPILOT_ROUTER_MODEL` stays **unset** — the v1 adapter would degrade
routing. The dormant `nxt-router` gateway registration is harmless.

**Toolchain notes (hard-won):** Kaggle 2026 image needs version *floors* not
2024 pins (peft import-crashes); TRL dropped entirely — its chunked-CE forward
patch breaks on accelerate's `functools.partial` wrapping of quantized
`device_map` models, and plain `transformers.Trainer` + `peft` does everything
this job needs; uninstall the image's stale `torchao` before
`PeftModel.from_pretrained`; GGUF export via `convert_hf_to_gguf.py --outtype
q8_0` (no llama-quantize build needed).

---

## 2. Inference optimization

Ordered by impact-to-effort:

1. **Model tiering (done).** Router model for plan/route/tools, answer model for
   the final response — `COPILOT_ROUTER_MODEL` / `COPILOT_ANSWER_MODEL` in
   `factory.py` + `graph.py`. This alone removes most frontier-model calls.
2. **Caching (use their Redis).** Read-only queries repeat ("what's my
   balance"). Cache (a) plan by normalized `(role, question)`, and (b) tool
   results with a short TTL. The backend already runs Redis — reuse it.
3. **Parallel sub-tasks.** Independent plan steps run sequentially today. Fan
   them out with `asyncio.gather` (LangGraph parallel branches) — big win on
   multi-part questions; the `metrics.latency_ms` we log makes the gain visible.
4. **Token budgets & prompt slimming.** Cap tool-result rows (`max_rows`),
   summarize/truncate large tool outputs before the aggregator, keep system
   prompts terse. Fewer tokens = less cost and latency.
5. **Constrained decoding for the router.** Restrict routing output to the valid
   worker names and tool names (vLLM guided decoding / Outlines). Removes invalid
   routes and lets a smaller model route reliably — pairs perfectly with §1.
6. **Quantized serving + measurement.** Serve the router with vLLM (4/8-bit) or
   MLX; measure TTFT, tokens/sec, p50/p95 latency, and cost/query across
   {sandbox, FT-router, frontier} and before/after cache. Surface it in Grafana
   (the existing lab). The `metrics` block on every response is the data source.
7. **Streaming.** Stream the aggregator's answer to the chat UI for perceived
   latency.

---

## What's already in place for this

- `metrics` on every response (latency, steps, tools_called) — the measurement hook.
- `COPILOT_TRACE_FILE` JSONL traces — the training-data source.
- `scripts/build_ft_dataset.py` — traces → router dataset.
- Model tiering (`router`/`answer`) — the deployment slot for the FT model.

## Suggested order

1. Collect traces in gateway mode (teacher) → build dataset.
2. QLoRA the router on Kaggle T4 → serve via vLLM → set `COPILOT_ROUTER_MODEL`.
3. Add Redis plan/tool cache + parallel sub-tasks.
4. Wire latency/cost metrics into Grafana; add constrained decoding + streaming.
