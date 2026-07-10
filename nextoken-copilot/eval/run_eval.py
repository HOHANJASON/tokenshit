"""Run the offline evaluation suite and print a scorecard.

    python -m eval.run_eval

Exits non-zero if any red-team case leaks (so it can gate CI).
"""
from __future__ import annotations

import sys

from .suite import run_functional, run_redteam


def _print(title: str, rows: list[dict], leak_key: str | None = None) -> int:
    passed = sum(r["passed"] for r in rows)
    print(f"\n== {title}: {passed}/{len(rows)} ==")
    for r in rows:
        mark = "PASS" if r["passed"] else "FAIL"
        extra = ""
        if not r["passed"]:
            extra = f"   <- leaked {r['leaked']}" if leak_key == "leaked" else f"   <- missing {r['missing']}"
        print(f"  [{mark}] ({r['role']}) {r['question'][:60]}{extra}")
    return passed


def main() -> None:
    func = run_functional()
    red = run_redteam()
    f_pass = _print("Functional success", func)
    r_pass = _print("RBAC red-team (no leak)", red, leak_key="leaked")

    print("\n" + "-" * 60)
    print(f"Functional: {f_pass}/{len(func)}  ({100*f_pass//len(func)}%)")
    print(f"Red-team:   {r_pass}/{len(red)}  ({100*r_pass//len(red)}%)")
    leaked = len(red) - r_pass
    print("RESULT:", "ALL CLEAN ✅" if leaked == 0 else f"{leaked} LEAK(S) ❌")
    sys.exit(0 if leaked == 0 and f_pass == len(func) else 1)


if __name__ == "__main__":
    main()
