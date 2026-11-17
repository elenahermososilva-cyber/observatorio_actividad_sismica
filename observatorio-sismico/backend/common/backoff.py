"""Espera progresiva (backoff exponencial con jitter) para reintentos."""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable, Iterator
from typing import TypeVar

T = TypeVar("T")
log = logging.getLogger(__name__)


def backoff_delays(
    base: float = 1.0,
    factor: float = 2.0,
    maximum: float = 60.0,
    jitter: float = 0.1,
    rng: Callable[[], float] = random.random,
) -> Iterator[float]:
    """Genera esperas infinitas: base, base*factor, ... acotadas por `maximum`.

    `jitter` es la fracción máxima (0..1) que se resta aleatoriamente para
    evitar que varios servicios reintenten sincronizados. Nunca supera `maximum`.
    """
    if base <= 0 or factor < 1 or maximum < base or not 0 <= jitter < 1:
        raise ValueError("invalid backoff parameters")
    delay = base
    while True:
        yield min(delay, maximum) * (1 - jitter * rng())
        delay = min(delay * factor, maximum)


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    attempts: int | None = None,
    base: float = 1.0,
    factor: float = 2.0,
    maximum: float = 30.0,
    description: str = "operation",
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Reintenta `operation` con espera progresiva. `attempts=None` reintenta sin límite."""
    delays = backoff_delays(base, factor, maximum)
    attempt = 0
    while True:
        attempt += 1
        try:
            return await operation()
        except retry_on as error:
            if attempts is not None and attempt >= attempts:
                raise
            delay = next(delays)
            log.warning("%s failed (attempt %d): %s; retrying in %.1fs", description, attempt, error, delay)
            await sleep(delay)


def retry_sync(
    operation: Callable[[], T],
    *,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    attempts: int | None = None,
    base: float = 1.0,
    factor: float = 2.0,
    maximum: float = 30.0,
    description: str = "operation",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    delays = backoff_delays(base, factor, maximum)
    attempt = 0
    while True:
        attempt += 1
        try:
            return operation()
        except retry_on as error:
            if attempts is not None and attempt >= attempts:
                raise
            delay = next(delays)
            log.warning("%s failed (attempt %d): %s; retrying in %.1fs", description, attempt, error, delay)
            sleep(delay)
