from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
import time

from redis.exceptions import RedisError

from .cache import REDIS_REQUIRED, redis_client


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    requests_used: int
    tokens_used: int
    retry_after: int


_memory_lock = Lock()
_memory_buckets: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])


def consume(key_id: int, rpm_limit: int, tpm_limit: int, estimated_tokens: int) -> RateLimitResult:
    minute = int(time.time() // 60)
    retry_after = 60 - int(time.time() % 60)
    used_redis = False
    if redis_client is not None:
        try:
            request_key = f"nextoken:limit:{key_id}:{minute}:requests"
            token_key = f"nextoken:limit:{key_id}:{minute}:tokens"
            pipe = redis_client.pipeline(transaction=True)
            pipe.incr(request_key)
            pipe.expire(request_key, 120)
            pipe.incrby(token_key, max(estimated_tokens, 0))
            pipe.expire(token_key, 120)
            requests_used, _, tokens_used, _ = pipe.execute()
            used_redis = True
        except RedisError:
            if REDIS_REQUIRED:
                raise
    if not used_redis:
        with _memory_lock:
            requests_used, tokens_used = _memory_buckets[(key_id, minute)]
            requests_used += 1
            tokens_used += max(estimated_tokens, 0)
            _memory_buckets[(key_id, minute)] = [requests_used, tokens_used]
            if len(_memory_buckets) > 10_000:
                stale = [key for key in _memory_buckets if key[1] < minute - 1]
                for key in stale:
                    _memory_buckets.pop(key, None)
    allowed = (rpm_limit <= 0 or requests_used <= rpm_limit) and (tpm_limit <= 0 or tokens_used <= tpm_limit)
    return RateLimitResult(allowed, int(requests_used), int(tokens_used), retry_after)
