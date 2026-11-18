"""Construcción de GeoJSON conforme a CONTRATO-API.md (sin dependencias externas).

Reglas: `null` (nunca NaN/Infinity) para magnitud, profundidad o país desconocidos;
coordenadas en orden longitud, latitud, profundidad (km); fechas en ms Unix UTC.
"""

import math
from dataclasses import dataclass


def finite_or_none(value: object) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def build_feature(event_id: str, payload: dict) -> dict | None:
    """Feature del evento actual. Devuelve None si la geometría no es válida (nunca se inventa un punto)."""
    geometry = payload.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    lon, lat = finite_or_none(coordinates[0]), finite_or_none(coordinates[1])
    if lon is None or lat is None:
        return None
    depth = finite_or_none(coordinates[2]) if len(coordinates) > 2 else None

    properties = payload.get("properties") or {}
    return {
        "type": "Feature",
        "id": event_id,
        "geometry": {"type": "Point", "coordinates": [lon, lat, depth]},
        "properties": {
            "mag": finite_or_none(properties.get("mag")),
            "magType": properties.get("magType") if isinstance(properties.get("magType"), str) else None,
            "place": properties.get("place") if isinstance(properties.get("place"), str) else None,
            "time": properties.get("time"),
            "updated": properties.get("updated"),
            # La asignación por punto-en-polígono llega en la Fase 8: hasta entonces, país desconocido.
            "country_id": None,
            "country_name": None,
        },
    }


def build_feature_from_row(
    event_id: str,
    lon: float,
    lat: float,
    depth_km: float | None,
    mag: float | None,
    mag_type: str | None,
    place: str | None,
    time_ms: int,
    updated_ms: int,
    country_id: str | None,
    country_name: str | None,
) -> dict | None:
    """Feature desde las columnas de `event_current`. None si lon/lat no son finitas (no se inventa un punto)."""
    lon, lat = finite_or_none(lon), finite_or_none(lat)
    if lon is None or lat is None:
        return None
    return {
        "type": "Feature",
        "id": event_id,
        "geometry": {"type": "Point", "coordinates": [lon, lat, finite_or_none(depth_km)]},
        "properties": {
            "mag": finite_or_none(mag),
            "magType": mag_type,
            "place": place,
            "time": time_ms,
            "updated": updated_ms,
            # null = país desconocido o aún sin atribuir; nunca se deduce de `place`.
            "country_id": country_id,
            "country_name": country_name,
        },
    }


@dataclass(frozen=True)
class CollectionMeta:
    generated: int
    last_ingestion: int | None
    mode: str
    truncated: bool  # quedan eventos que cumplen los filtros más allá de esta página
    start: int | None
    end: int | None
    total: int  # eventos que cumplen los filtros (todas las páginas)
    limit: int | None = None
    offset: int = 0
    null_mag_count: int = 0  # con magnitud nula DENTRO del conjunto filtrado (se muestran como ND)
    null_mag_excluded: int = 0  # con min_mag: eventos de magnitud nula que quedan fuera por no poder cumplirlo
    filters: dict | None = None


def build_collection(features: list[dict], meta: CollectionMeta) -> dict:
    next_offset = meta.offset + len(features) if meta.truncated else None
    metadata = {
        "generated": meta.generated,
        "last_ingestion": meta.last_ingestion,
        "mode": meta.mode,
        "count": len(features),
        "truncated": meta.truncated,
        "total": meta.total,
        "start": meta.start,
        "end": meta.end,
        "limit": meta.limit,
        "offset": meta.offset,
        "next_offset": next_offset,
        "null_mag_count": meta.null_mag_count,
        "null_mag_excluded": meta.null_mag_excluded,
        "filters": meta.filters if meta.filters is not None else {"min_mag": None, "country_id": None},
    }
    return {"type": "FeatureCollection", "metadata": metadata, "features": features}
