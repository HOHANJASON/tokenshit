"""Ask the NexToken Copilot from the command line as a given role.

Local (offline reference data):
    python -m scripts.ask --role client --customer 1 "what did I spend this month?"
    python -m scripts.ask --role admin "what is our gross margin and margin by model?"

Remote (live NexToken backend on :3100 — the backend enforces RBAC + audits):
    python -m scripts.ask --remote --token-file /tmp/nxt_customer_token.txt \
        --role client "what is my balance and list my api keys"
"""
from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the NexToken Copilot.")
    parser.add_argument("--role", default="client", choices=["client", "support", "admin"])
    parser.add_argument("--customer", type=int, default=None, help="customer_id (required for client)")
    parser.add_argument("--remote", action="store_true", help="use the live NexToken backend tool surface")
    parser.add_argument("--backend-url", default=None, help="backend base url (default http://127.0.0.1:3100)")
    parser.add_argument("--token", default=None, help="backend JWT for --remote")
    parser.add_argument("--token-file", default=None, help="file containing the backend JWT")
    parser.add_argument("question", nargs="+")
    args = parser.parse_args()

    # Configure BEFORE importing the package (settings are read at import time).
    if args.remote:
        os.environ["COPILOT_TOOLS_MODE"] = "remote"
        if args.backend_url:
            os.environ["COPILOT_BACKEND_URL"] = args.backend_url
        token = args.token or (open(args.token_file).read().strip() if args.token_file else "")
        if token:
            os.environ["COPILOT_BACKEND_TOKEN"] = token

    from nextoken_copilot.agents import ask
    from nextoken_copilot.principal import Principal, Role

    customer_id = args.customer if args.customer is not None else (1 if args.role == "client" else None)
    principal = Principal(role=Role(args.role), customer_id=customer_id, email="cli@local")

    result = ask(principal, " ".join(args.question))
    print("PLAN:   ", result["plan"])
    print("WORKERS:", result["workers_available"])
    print("ROUTES: ", [(r["worker"], r["subtask"]) for r in result["results"]])
    print("METRICS:", result["metrics"])
    print("\nANSWER:\n" + result["answer"])


if __name__ == "__main__":
    main()
