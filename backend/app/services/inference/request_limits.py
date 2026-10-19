"""User-shared request admission. In-flight state requires one worker process."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
import logging
import math
import threading

from app.core import config
from app.db import session
from app.repositories import request_limits as repository

logger = logging.getLogger(__name__)
_inflight: dict[str, int] = {}
_inflight_lock = threading.Lock()


class RateLimitError(Exception):
    def __init__(self, status_code: int, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after = retry_after


class _WindowChanged(Exception):
    """Rollback and retry if waiting for the row lock crossed a UTC minute."""


def _reserve_rpm(user_id: str, rpm: int) -> None:
    # Commit releases cleanup range/gap locks before inserting a current window.
    # Keeping DELETE in the quota transaction can deadlock concurrent first requests.
    with session.unit_of_work() as db:
        repository.cleanup(db)
    for _ in range(3):
        try:
            with session.unit_of_work() as db:
                now = repository.now(db)
                window = now.replace(second=0, microsecond=0)
                repository.ensure_window(db, user_id, window)
                count = repository.lock_count(db, user_id, window)
                now = repository.now(db)
                if now.replace(second=0, microsecond=0) != window:
                    raise _WindowChanged()
                if count >= rpm:
                    retry = max(1, math.ceil((window + timedelta(minutes=1) - now).total_seconds()))
                    raise RateLimitError(429, 'rate_limit_exceeded', '请求次数超过当前分钟限额', retry)
                repository.increment(db, user_id, window)
            return
        except _WindowChanged:
            continue
    raise RuntimeError('Request admission window changed repeatedly')


@contextmanager
def admit(user_id: str) -> Iterator[None]:
    limits = config.request_limits_config()
    acquired = False
    if limits.max_inflight:
        with _inflight_lock:
            count = _inflight.get(user_id, 0)
            if count >= limits.max_inflight:
                raise RateLimitError(429, 'concurrency_limit_exceeded', '在途请求超过限额', 1)
            _inflight[user_id] = count + 1
            acquired = True
    try:
        if limits.rpm:
            try:
                _reserve_rpm(user_id, limits.rpm)
            except RateLimitError:
                raise
            except Exception:
                # Do not log driver messages: they can contain configuration or SQL values.
                logger.error('Request rate admission storage failed')
                raise RateLimitError(503, 'rate_limit_unavailable', '请求限流服务暂不可用') from None
        yield
    finally:
        if acquired:
            with _inflight_lock:
                remaining = _inflight[user_id] - 1
                if remaining:
                    _inflight[user_id] = remaining
                else:
                    del _inflight[user_id]
