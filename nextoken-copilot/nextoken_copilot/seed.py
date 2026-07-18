"""Create a sample SQLite database with realistic NexToken data.

    python -m nextoken_copilot.seed

Produces three customers, three resold models (each with an upstream cost and a
higher customer price, i.e. a margin), 30 days of usage logs and a matching
ledger. Used by the demo, the tests and the RBAC red-team eval.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal

from .config import DATA_DIR, settings
from .db import (
    ApiKey,
    Base,
    Customer,
    Ledger,
    ModelConfig,
    Provider,
    SessionLocal,
    UsageLog,
    engine,
)

random.seed(7)

CUSTOMERS = [
    ("alice@acme.io", Decimal("42.50")),
    ("bob@globex.com", Decimal("8.10")),
    ("carol@initech.dev", Decimal("125.00")),
]

PROVIDERS = [
    ("openai-main", "https://api.openai.com/v1"),
    ("azure-backup", "https://example-azure.openai.azure.com/v1"),
]

# public_name, upstream, provider_idx, input_cost, output_cost, input_price, output_price
# Costs/prices are per 1K tokens. price > cost => margin (ADMIN-only).
MODELS = [
    ("nxt-gpt-4o", "gpt-4o", 0, Decimal("0.0025"), Decimal("0.010"), Decimal("0.005"), Decimal("0.020")),
    ("nxt-gpt-4o-mini", "gpt-4o-mini", 0, Decimal("0.00015"), Decimal("0.0006"), Decimal("0.0004"), Decimal("0.0016")),
    ("nxt-o3", "o3", 1, Decimal("0.010"), Decimal("0.040"), Decimal("0.020"), Decimal("0.080")),
]


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"))


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()

    providers = [Provider(name=n, base_url=u, active=True) for n, u in PROVIDERS]
    db.add_all(providers)
    db.flush()

    models = [
        ModelConfig(
            public_name=name,
            upstream_model=up,
            provider_id=providers[pidx].id,
            input_cost=ic,
            output_cost=oc,
            input_price=ip,
            output_price=op,
            active=True,
        )
        for name, up, pidx, ic, oc, ip, op in MODELS
    ]
    db.add_all(models)
    db.flush()

    now = datetime.utcnow()
    for email, balance in CUSTOMERS:
        cust = Customer(email=email, balance=balance, active=True, created_at=now - timedelta(days=40))
        db.add(cust)
        db.flush()

        key = ApiKey(
            customer_id=cust.id,
            name="Default",
            key_prefix="nxt_live_" + email[:3],
            active=True,
            created_at=now - timedelta(days=38),
            last_used_at=now - timedelta(hours=3),
        )
        db.add(key)
        db.flush()

        db.add(Ledger(
            customer_id=cust.id,
            amount=balance + Decimal("50"),
            kind="topup",
            note="Initial credit",
            created_at=now - timedelta(days=38),
        ))

        for days_ago in range(30):
            day = now - timedelta(days=days_ago, hours=random.randint(0, 12))
            for _ in range(random.randint(0, 6)):
                m = random.choice(models)
                itok = random.randint(200, 4000)
                otok = random.randint(50, 1500)
                upstream = _q((m.input_cost * itok + m.output_cost * otok) / Decimal(1000))
                charge = _q((m.input_price * itok + m.output_price * otok) / Decimal(1000))
                status = 200 if random.random() > 0.05 else 500
                db.add(UsageLog(
                    customer_id=cust.id,
                    api_key_id=key.id,
                    model=m.public_name,
                    input_tokens=itok,
                    output_tokens=otok,
                    upstream_cost=upstream,
                    charge=charge if status == 200 else Decimal("0"),
                    status=status,
                    latency_ms=random.randint(300, 5000),
                    created_at=day,
                ))
                if status == 200:
                    db.add(Ledger(
                        customer_id=cust.id,
                        amount=-charge,
                        kind="debit",
                        note=f"{m.public_name} call",
                        created_at=day,
                    ))

    db.commit()
    rows = db.query(UsageLog).count()
    print(f"Seeded {len(CUSTOMERS)} customers, {len(models)} models, {rows} usage rows -> {settings.database_url}")
    db.close()


if __name__ == "__main__":
    main()
