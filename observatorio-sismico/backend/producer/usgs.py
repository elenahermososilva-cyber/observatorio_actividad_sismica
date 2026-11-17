"""Cliente HTTP de USGS (feed y API FDSN) con reintentos y errores explícitos.

Política (enunciado §5.6):
- Timeout, errores de red, HTTP 429 y 5xx, y JSON inválido se reintentan con espera progresiva
  (se respeta `Retry-After` en 429/503, acotado). Tras agotar los intentos se lanza `FeedError`.
- Otros 4xx no se reintentan: repetirlos no los arregla.
- Nunca se devuelve una respuesta parcial como si fuera válida. Quien llama conserva su estado anterior ante `FeedError`.
- Se rechaza NaN/Infinity en el JSON: no es JSON estándar y contaminaría los datos.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from backend.common.backoff import backoff_delays

log = logging.getLogger("usgs")

USER_AGENT = "observatorio-sismico-student-project/1.0 (educational)"
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class FeedError(Exception):
    """La consulta falló de forma definitiva. `status` y `attempts` quedan para el registro de extracción."""

    def __init__(self, message: str, *, status: int | None = None, latency_ms: int | None = None, attempts: int = 1):
        super().__init__(message)
        self.status = status
        self.latency_ms = latency_ms
        self.attempts = attempts


@dataclass(frozen=True)
class FeedResult:
    status: int
    body: bytes
    data: dict
    latency_ms: int
    attempts: int

    @property
    def features(self) -> list:
        return self.data["features"]


def _reject_constant(value: str):
    raise ValueError(f"{value} is not a valid JSON number")


def parse_feature_collection(body: bytes) -> dict:
    """JSON estándar con una lista `features`; ValueError si no lo es."""
    data = json.loads(body, parse_constant=_reject_constant)
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise ValueError("response is not a GeoJSON FeatureCollection with a 'features' list")
    return data


def retry_after_seconds(response: httpx.Response, cap: float) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return min(max(float(value), 0.0), cap)
    except ValueError:  # fecha HTTP: no la interpretamos, se usa la espera progresiva
        return None


async def fetch_feature_collection(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None = None,
    *,
    attempts: int = 5,
    base: float = 2.0,
    maximum: float = 60.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> FeedResult:
    delays = backoff_delays(base, 2.0, maximum)
    last_error = "no attempt made"
    last_status: int | None = None
    latency_ms: int | None = None
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        wait: float | None = None
        try:
            response = await client.get(url, params=params)
            latency_ms = round((time.monotonic() - started) * 1000)
            last_status = response.status_code
            if response.status_code == 200:
                try:
                    data = parse_feature_collection(response.content)
                except ValueError as error:
                    last_error = f"invalid JSON in response: {error}"
                else:
                    return FeedResult(200, response.content, data, latency_ms, attempt)
            elif response.status_code in RETRYABLE_STATUS:
                last_error = f"HTTP {response.status_code}"
                wait = retry_after_seconds(response, maximum)
            else:
                raise FeedError(
                    f"HTTP {response.status_code} (not retryable)",
                    status=response.status_code, latency_ms=latency_ms, attempts=attempt,
                )
        except httpx.TimeoutException as error:
            latency_ms = round((time.monotonic() - started) * 1000)
            last_status, last_error = None, f"timeout: {type(error).__name__}"
        except httpx.TransportError as error:
            latency_ms = round((time.monotonic() - started) * 1000)
            last_status, last_error = None, f"network error: {type(error).__name__}: {error}"

        if attempt < attempts:
            delay = wait if wait is not None else next(delays)
            log.warning("USGS request failed (%s), attempt %d/%d; retrying in %.1fs", last_error, attempt, attempts, delay)
            await sleep(delay)

    raise FeedError(
        f"{last_error} after {attempts} attempts", status=last_status, latency_ms=latency_ms, attempts=attempts
    )


def parse_count(text: str) -> int:
    """El endpoint `count` responde un entero en texto plano o, con `format=geojson`, `{"count": N, "maxAllowed": M}`.

    Comprobado contra USGS real: ambos formatos existen, así que se aceptan los dos."""
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    count = value.get("count") if isinstance(value, dict) else None
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        return count
    raise ValueError(f"count response is neither an integer nor a JSON object with 'count': {text[:60]!r}")


async def fetch_count(
    client: httpx.AsyncClient, url: str, params: dict, *, attempts: int = 5, sleep=asyncio.sleep
) -> int:
    """Endpoint FDSN `count`."""
    delays = backoff_delays(2.0, 2.0, 60.0)
    last_error = "no attempt made"
    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                try:
                    return parse_count(response.text)
                except ValueError as error:
                    last_error = str(error)
            elif response.status_code in RETRYABLE_STATUS:
                last_error = f"HTTP {response.status_code}"
            else:
                raise FeedError(f"HTTP {response.status_code} (not retryable)", status=response.status_code, attempts=attempt)
        except httpx.TransportError as error:  # incluye timeouts
            last_error = f"network error: {type(error).__name__}"
        if attempt < attempts:
            await sleep(next(delays))
    raise FeedError(f"{last_error} after {attempts} attempts", attempts=attempts)
