"""Columnas desnormalizadas de `event_current` derivadas del payload original (sin dependencias externas)."""

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EventColumns:
    time_ms: int
    mag: float | None
    mag_type: str | None
    depth_km: float | None
    lon: float
    lat: float
    place: str | None
    event_type: str
    ingested_at: datetime


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def extract_columns(payload: dict, ingested_at: datetime) -> EventColumns:
    """Supone un payload ya validado por EventMessage (Point finito y en rango, time entero)."""
    properties = payload["properties"]
    coordinates = payload["geometry"]["coordinates"]
    return EventColumns(
        time_ms=properties["time"],
        mag=_finite(properties.get("mag")),  # None = magnitud no disponible; nunca se rellena con 0
        mag_type=_text(properties.get("magType")),
        depth_km=_finite(coordinates[2]) if len(coordinates) > 2 else None,
        lon=float(coordinates[0]),
        lat=float(coordinates[1]),
        place=_text(properties.get("place")),
        event_type=properties["type"],
        ingested_at=ingested_at,
    )
