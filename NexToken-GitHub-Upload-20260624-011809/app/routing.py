from collections import defaultdict
from datetime import datetime, timedelta
import os
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ModelConfig, ModelRoute, Provider


FAILURE_THRESHOLD = int(os.getenv("ROUTE_FAILURE_THRESHOLD", "3"))
COOLDOWN_SECONDS = int(os.getenv("ROUTE_COOLDOWN_SECONDS", "60"))


def _weighted_order(routes: list[ModelRoute]) -> list[ModelRoute]:
    pool = list(routes)
    result: list[ModelRoute] = []
    while pool:
        weights = [max(route.weight, 1) for route in pool]
        selected = random.choices(pool, weights=weights, k=1)[0]
        result.append(selected)
        pool.remove(selected)
    return result


def available_routes(db: Session, public_model: str) -> list[ModelRoute]:
    now = datetime.utcnow()
    rows = db.scalars(
        select(ModelRoute)
        .join(ModelConfig, ModelRoute.model_config_id == ModelConfig.id)
        .join(Provider, ModelRoute.provider_id == Provider.id)
        .where(
            ModelConfig.public_name == public_model,
            ModelConfig.active.is_(True),
            ModelRoute.active.is_(True),
            Provider.active.is_(True),
        )
        .order_by(ModelRoute.priority, Provider.priority, ModelRoute.id)
    ).all()
    eligible = [route for route in rows if route.disabled_until is None or route.disabled_until <= now]
    grouped: dict[tuple[int, int], list[ModelRoute]] = defaultdict(list)
    for route in eligible:
        grouped[(route.priority, route.provider.priority)].append(route)
    ordered: list[ModelRoute] = []
    for priority in sorted(grouped):
        ordered.extend(_weighted_order(grouped[priority]))
    return ordered


def mark_success(db: Session, route: ModelRoute) -> None:
    route.failure_count = 0
    route.disabled_until = None
    route.last_error = None
    db.commit()


def mark_failure(db: Session, route: ModelRoute, error: str) -> None:
    route.failure_count += 1
    route.last_error = error[:2000]
    if route.failure_count >= FAILURE_THRESHOLD:
        route.disabled_until = datetime.utcnow() + timedelta(seconds=COOLDOWN_SECONDS)
    db.commit()
