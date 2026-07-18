"""Reliability scorecard: pass@k and pass^k over the demo-beat battery.

    python -m eval.reliability -n 10            # 10 trials per case
    make reliability N=10

pass@k  — P(at least one of k attempts succeeds): capability; rises with k.
pass^k  — P(ALL k attempts succeed): τ-bench's consistency metric; falls
          with k and is the honest number for a customer-support agent.

Runs against whatever stack the COPILOT_* env selects (sandbox = offline
smoke; gateway+remote = the real measurement). Trials at temperature 0 are
correlated rather than i.i.d., so treat live numbers as slightly optimistic.
"""
from __future__ import annotations

import argparse

from .suite import pass_at_k, pass_hat_k, run_reliability


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("-n", "--trials", type=int, default=5)
    p.add_argument("--ks", default="1,4,8", help="comma-separated k values")
    args = p.parse_args()
    ks = [int(k) for k in args.ks.split(",") if int(k) <= args.trials]

    rows = run_reliability(args.trials)

    head = f"{'case':28s} {'c/n':>6s}" + "".join(f"  pass^{k:<2d}" for k in ks) \
        + "".join(f"  pass@{k:<2d}" for k in ks if k > 1) + "   avg s"
    print("\n" + head)
    print("-" * len(head))
    for r in rows:
        n, c = r["n"], r["c"]
        line = f"{r['label']:28s} {c:>3d}/{n:<2d}"
        line += "".join(f"  {pass_hat_k(n, c, k):6.2f}" for k in ks)
        line += "".join(f"  {pass_at_k(n, c, k):6.2f}" for k in ks if k > 1)
        line += f"  {r['mean_latency_s']:6.1f}"
        print(line)

    n = rows[0]["n"]
    macro = {k: sum(pass_hat_k(r["n"], r["c"], k) for r in rows) / len(rows) for k in ks}
    print("-" * len(head))
    print("macro pass^k: " + "  ".join(f"k={k}: {v:.2f}" for k, v in macro.items())
          + f"   ({len(rows)} cases × {n} trials)")


if __name__ == "__main__":
    main()
