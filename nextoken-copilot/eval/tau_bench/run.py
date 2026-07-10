"""Run tau-bench with the NexToken agent.

    COPILOT_LLM_MODE=gateway \
    COPILOT_LLM_BASE_URL=http://127.0.0.1:3100/v1 \
    COPILOT_LLM_API_KEY=nxt_live_... \
    COPILOT_LLM_MODEL=nxt-gpt-4o \
    python -m eval.tau_bench.run --env retail --num-tasks 20

Reports average reward (task success) and pass@1. Needs a real model + key.
"""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate NexToken Copilot on tau-bench.")
    parser.add_argument("--env", default="retail", choices=["retail", "airline"])
    parser.add_argument("--num-tasks", type=int, default=20)
    parser.add_argument("--user-model", default="gpt-4o-mini", help="model for the tau-bench user simulator")
    parser.add_argument("--user-provider", default="openai")
    args = parser.parse_args()

    try:
        from tau_bench.envs import get_env
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "tau-bench is not installed.\n"
            "  pip install git+https://github.com/sierra-research/tau-bench"
        ) from exc

    from .agent import NexTokenAgent

    env = get_env(
        args.env,
        user_strategy="llm",
        user_model=args.user_model,
        user_provider=args.user_provider,
        task_split="test",
    )

    rewards = []
    n = min(args.num_tasks, len(env.tasks))
    for i in range(n):
        agent = NexTokenAgent(tools_info=env.tools_info, wiki=env.wiki)
        result = agent.solve(env, task_index=i)
        reward = float(getattr(result, "reward", 0.0))
        rewards.append(reward)
        print(f"task {i:3d}: reward={reward:.3f}")

    if rewards:
        avg = sum(rewards) / len(rewards)
        passed = sum(1 for r in rewards if r >= 1.0) / len(rewards)
        print(f"\n{args.env}: {len(rewards)} tasks | avg reward={avg:.3f} | pass@1={passed:.3f}")


if __name__ == "__main__":
    main()
