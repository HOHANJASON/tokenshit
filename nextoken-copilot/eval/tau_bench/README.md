# Evaluating on τ-bench (public benchmark)

[τ-bench](https://github.com/sierra-research/tau-bench) ("A Benchmark for
Tool-Agent-User Interaction in Real-World Domains", Sierra, 2024) measures
whether an agent can **use tools correctly and follow a domain policy** while a
simulated user talks to it. It is the general-competence analogue of our RBAC
red-team: there the rule is "never leak admin data"; here the rule is "obey the
retail/airline policy."

We evaluate the **same ReAct / tool-calling core that powers our worker agents**
([`agent.py`](agent.py)) on τ-bench's tasks, driven by our pluggable model
factory — so the number reflects our agent strategy on a recognized benchmark.

## Why it isn't run in the offline suite

τ-bench needs a real LLM for **both** the agent and the user simulator, so it
costs API tokens and cannot run on the deterministic sandbox model. Point the
agent at the NexToken gateway (or any provider) and run it yourself.

## Run it

```bash
# 1. install the benchmark
pip install git+https://github.com/sierra-research/tau-bench

# 2. choose the model the AGENT runs on (here: the NexToken gateway)
export COPILOT_LLM_MODE=gateway
export COPILOT_LLM_BASE_URL=http://127.0.0.1:3100/v1
export COPILOT_LLM_API_KEY=nxt_live_xxx
export COPILOT_LLM_MODEL=nxt-gpt-4o
pip install langchain-openai           # backend for gateway/openai mode

# 3. run (retail domain, first 20 tasks)
python -m eval.tau_bench.run --env retail --num-tasks 20
```

Output reports **avg reward** (fraction of tasks solved) and **pass@1**.

## Notes

- `--user-model` / `--user-provider` configure the user simulator (defaults to
  `gpt-4o-mini` via OpenAI; set your `OPENAI_API_KEY`).
- τ-bench's Python API has changed across releases; if `get_env` / `Agent` /
  `SolveResult` signatures differ in your install, adjust [`agent.py`](agent.py)
  and [`run.py`](run.py) accordingly (both isolate those calls).
- Cost control: start with `--num-tasks 10–20`. A full split is 100s of tasks.
