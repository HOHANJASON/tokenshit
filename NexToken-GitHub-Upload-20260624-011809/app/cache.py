import os

from redis import Redis
from redis.exceptions import RedisError


REDIS_URL = os.getenv("REDIS_URL", "").strip()
REDIS_REQUIRED = os.getenv("REDIS_REQUIRED", "false").lower() in {"1", "true", "yes", "on"}
redis_client = (
    Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
    if REDIS_URL
    else None
)


def check_redis() -> bool:
    if redis_client is None:
        return False
    try:
        return bool(redis_client.ping())
    except RedisError:
        if REDIS_REQUIRED:
            raise
        return False
