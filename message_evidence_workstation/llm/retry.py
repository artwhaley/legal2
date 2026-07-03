"""Router retry policy."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_BASE_DELAY_SECONDS = 1.0


def call_with_retry(
    operation: Callable[[], T],
    *,
    is_retryable: Callable[[Exception], bool],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> T:
    """Execute ``operation`` with retry logic.

    ``on_retry`` is called before each retry with (attempt_index, exception, delay_seconds).
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return operation()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts - 1 or not is_retryable(exc):
                raise
            delay = base_delay_seconds * (2**attempt)
            jitter = random.uniform(0.0, delay * 0.25)
            if on_retry is not None:
                on_retry(attempt, exc, delay + jitter)
            time.sleep(delay + jitter)
    assert last_exc is not None
    raise last_exc
