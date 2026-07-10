# Router fine-tuning (QLoRA on Kaggle 2×T4)

Distils the copilot's three router decisions — **plan**, **route**, and
**tool-select** — into a small model, so those frequent calls stop hitting a
frontier model. The strong model is kept only for the final answer via
`COPILOT_ANSWER_MODEL`; the fine-tuned router goes in `COPILOT_ROUTER_MODEL`.

## Files

| File | What |
|---|---|
| `ft_router.jsonl` | training set (chat format) — generated locally, committed here |
| `qlora_router.py` | 4-bit QLoRA trainer (TRL + PEFT) |
| `requirements-kaggle.txt` | pinned deps for a reproducible T4 run |

## 0. (Recommended) regenerate with teacher labels

The committed `ft_router.jsonl` was bootstrapped from the deterministic sandbox
router, so training it teaches a small model to imitate the rules. For a real
quality gain, relabel with a strong teacher model, then re-upload:

```bash
# in the copilot repo, with your key set
COPILOT_LLM_MODE=openai COPILOT_LLM_MODEL=gpt-4o COPILOT_LLM_API_KEY=sk-... \
    python -m scripts.collect_traces data/traces_teacher.jsonl
python -m scripts.build_ft_dataset data/traces_teacher.jsonl train/ft_router.jsonl
```

(Or `COPILOT_LLM_MODE=gateway` against the NexToken gateway once a provider is
configured.) Grow the battery in `scripts/collect_traces.py` for more data.

## 1. Train (Kaggle notebook, GPU = T4 ×2)

Upload `qlora_router.py`, `ft_router.jsonl`, `requirements-kaggle.txt` as a
dataset, then in a cell:

```bash
!pip install -q -r /kaggle/input/<your-dataset>/requirements-kaggle.txt
!python /kaggle/input/<your-dataset>/qlora_router.py \
    --data /kaggle/input/<your-dataset>/ft_router.jsonl \
    --base Qwen/Qwen2.5-1.5B-Instruct \
    --out /kaggle/working/router-lora
```

1.5 B in 4-bit fits on a single T4; the second GPU is spare headroom (or bump to
`Qwen2.5-3B-Instruct` / `meta-llama/Llama-3.2-1B-Instruct`). Trains in minutes on
this dataset size. The script prints a sanity generation for plan + route at the
end.

## 2. Serve + wire it back

Merge is optional; vLLM can serve the base + adapter. Simplest (OpenAI-compatible):

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-1.5B-Instruct \
    --enable-lora --lora-modules router=./router-lora \
    --port 8000
```

Point the copilot's router tier at it, keep the answer tier on the strong model:

```bash
export COPILOT_LLM_MODE=openai
export COPILOT_LLM_BASE_URL=http://127.0.0.1:8000/v1
export COPILOT_ROUTER_MODEL=router          # the fine-tuned adapter
export COPILOT_ANSWER_MODEL=gpt-4o           # (or the gateway) for prose
```

## 3. Gate before shipping

The fine-tuned router only ships if it keeps the eval green:

```bash
make eval      # must stay functional 7/7, red-team 6/6
make test
```

## Notes / next

- Full-text SFT is used for simplicity; masking the prompt (completion-only
  loss) is a small, optional upgrade.
- Measure latency/cost/routing-accuracy across {sandbox, FT-router, frontier}
  using the per-response `metrics` block and the JSONL traces (see
  [../OPTIMIZATION.md](../OPTIMIZATION.md)).
