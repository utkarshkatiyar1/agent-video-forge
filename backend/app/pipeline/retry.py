import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

log = logging.getLogger("forge.retry")
T = TypeVar("T")


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    base_delay: float = 1.0,
    on_failure: Callable[[int, Exception], None] | None = None,
    label: str = "op",
) -> T:
    """Call fn up to `attempts` times with exponential backoff; re-raise the last error."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except Exception as exc:  # provider errors are heterogeneous
            last = exc
            log.warning("%s failed (attempt %d/%d): %s", label, attempt, attempts, exc)
            if on_failure:
                on_failure(attempt, exc)
            if attempt < attempts:
                await asyncio.sleep(base_delay * 2 ** (attempt - 1))
    assert last is not None
    raise last
