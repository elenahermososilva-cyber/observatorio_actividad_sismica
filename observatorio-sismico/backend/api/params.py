"""Parámetros de consulta de la API: parseo y validación, sin dependencias externas.

Los filtros de /api/eventos y de /api/estadisticas son LOS MISMOS (CONTRATO-API.md: «los filtros de estadísticas
deben equivaler a los del mapa»), así que ambos endpoints pasan por `build_filters`.
"""

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.api.exceptions import InvalidParameter

DEFAULT_WINDOW_MS = 24 * 3600 * 1000
# Valor de `country_id` para «Sin país asignado» (epicentros fuera de todo polígono). No es un código ADM0_A3.
NO_COUNTRY = "none"
MIN_MAG_BOUNDS = (-10.0, 10.0)  # solo filtra entradas absurdas; no es un juicio sobre la sismología
_COUNTRY = re.compile(r"^[A-Z0-9]{2,5}$")


@dataclass(frozen=True)
class EventFilters:
    start_ms: int
    end_ms: int | None  # exclusivo
    min_mag: float | None
    country_id: str | None  # ADM0_A3, NO_COUNTRY, o None = sin filtro de país

    def describe(self) -> dict:
        return {"min_mag": self.min_mag, "country_id": self.country_id}


def parse_instant(name: str, value: str) -> int:
    """ISO8601 → ms Unix UTC. Sin zona horaria se interpreta como UTC."""
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as error:
        raise InvalidParameter(f"{name} must be an ISO8601 date or datetime, got {value!r}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def parse_min_mag(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        number = float(value)
    except ValueError as error:
        raise InvalidParameter(f"min_mag must be a number, got {value!r}") from error
    if not math.isfinite(number):  # float("nan") y float("inf") son válidos para Python, no para este contrato
        raise InvalidParameter(f"min_mag must be a finite number, got {value!r}")
    if not MIN_MAG_BOUNDS[0] <= number <= MIN_MAG_BOUNDS[1]:
        raise InvalidParameter(f"min_mag must be between {MIN_MAG_BOUNDS[0]:g} and {MIN_MAG_BOUNDS[1]:g}, got {value!r}")
    return number


def parse_country_id(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    cleaned = value.strip()
    if cleaned.lower() == NO_COUNTRY:
        return NO_COUNTRY
    cleaned = cleaned.upper()
    if not _COUNTRY.match(cleaned):
        raise InvalidParameter(
            f"country_id must be an ADM0_A3 code (e.g. ESP) or '{NO_COUNTRY}' for events without a country, got {value!r}"
        )
    return cleaned


def build_filters(
    start: str | None, end: str | None, min_mag: str | None, country_id: str | None, now_ms: int
) -> EventFilters:
    start_ms = parse_instant("start", start) if start else now_ms - DEFAULT_WINDOW_MS
    end_ms = parse_instant("end", end) if end else None
    if end_ms is not None and start_ms >= end_ms:
        raise InvalidParameter("start must be earlier than end")
    return EventFilters(start_ms, end_ms, parse_min_mag(min_mag), parse_country_id(country_id))


def parse_page(limit: str | None, offset: str | None, max_limit: int) -> tuple[int, int]:
    def integer(name: str, value: str | None, default: int, minimum: int) -> int:
        if value is None or value.strip() == "":
            return default
        try:
            number = int(value)
        except ValueError as error:
            raise InvalidParameter(f"{name} must be an integer, got {value!r}") from error
        if number < minimum:
            raise InvalidParameter(f"{name} must be >= {minimum}, got {number}")
        return number

    parsed_limit = integer("limit", limit, max_limit, 1)
    if parsed_limit > max_limit:
        raise InvalidParameter(f"limit must be <= {max_limit} (maximum points per response), got {parsed_limit}")
    return parsed_limit, integer("offset", offset, 0, 0)
