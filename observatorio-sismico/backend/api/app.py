import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Protocol

import psycopg
from fastapi import FastAPI, HTTPException

from db.repository import PostgresRepository

logger = logging.getLogger(__name__)
_DAY_MS = 24 * 60 * 60 * 1000


class EventRepository(Protocol):
    def get_current_events(
        self, since_ms: int
    ) -> tuple[list[dict[str, Any]], datetime | None]: ...

    def check_connection(self) -> None: ...


def _to_unix_ms(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("database timestamps must be timezone-aware")
    return int(value.astimezone(timezone.utc).timestamp() * 1000)


def _feature_from_row(row: dict[str, Any]) -> dict[str, Any]:
    envelope = row["payload"]
    if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
        raise ValueError("stored event payload is not a valid event envelope")

    feature = envelope["payload"]
    geometry = feature.get("geometry")
    properties = feature.get("properties")
    if feature.get("type") != "Feature" or not isinstance(geometry, dict):
        raise ValueError("stored event is not a GeoJSON Feature")
    if geometry.get("type") != "Point" or not isinstance(geometry.get("coordinates"), list):
        raise ValueError("stored event geometry is not a GeoJSON Point")
    if not isinstance(properties, dict):
        raise ValueError("stored event properties are invalid")

    coordinates = geometry["coordinates"]
    if len(coordinates) not in (2, 3) or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in coordinates
    ):
        raise ValueError("stored event coordinates are invalid")
    longitude, latitude = coordinates[:2]
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError("stored event coordinates are out of range")

    magnitude = properties.get("mag")
    if magnitude is not None and (
        isinstance(magnitude, bool)
        or not isinstance(magnitude, (int, float))
        or not math.isfinite(magnitude)
    ):
        raise ValueError("stored event magnitude is invalid")
    if not isinstance(properties.get("place"), str):
        raise ValueError("stored event place is invalid")

    result_properties = dict(properties)
    result_properties["time"] = row["source_time_ms"]
    result_properties["updated"] = row["source_updated_ms"]
    if not isinstance(envelope.get("synthetic_flag"), bool):
        raise ValueError("stored event synthetic marker is invalid")
    if "country_id" not in result_properties or "country_name" not in result_properties:
        raise ValueError("stored event country fields are missing")
    result_properties["source"] = envelope["source"]
    result_properties["synthetic_flag"] = envelope["synthetic_flag"]

    return {
        "type": "Feature",
        "id": row["event_id"],
        "geometry": geometry,
        "properties": result_properties,
    }


def create_app(repository: EventRepository | None = None) -> FastAPI:
    app = FastAPI(title="Observatorio de actividad sísmica")
    app.state.repository = repository or PostgresRepository(os.getenv("DATABASE_URL"))

    @app.get("/api/eventos")
    def get_eventos() -> dict[str, Any]:
        generated = datetime.now(timezone.utc)
        try:
            rows, last_ingestion = app.state.repository.get_current_events(
                int(generated.timestamp() * 1000) - _DAY_MS
            )
            features = [_feature_from_row(row) for row in rows]
            return {
                "type": "FeatureCollection",
                "metadata": {
                    "generated": int(generated.timestamp() * 1000),
                    "last_ingestion": (
                        _to_unix_ms(last_ingestion) if last_ingestion is not None else None
                    ),
                    "mode": "demo",
                    "count": len(features),
                    "truncated": False,
                },
                "features": features,
            }
        except (psycopg.Error, RuntimeError, ValueError, KeyError, TypeError) as error:
            logger.exception("Could not build the event collection")
            raise HTTPException(
                status_code=503,
                detail="No se pudo consultar la colección de eventos",
            ) from error

    @app.get("/api/salud")
    def get_salud() -> dict[str, str]:
        try:
            app.state.repository.check_connection()
        except (psycopg.Error, RuntimeError) as error:
            logger.exception("API dependency health check failed")
            raise HTTPException(
                status_code=503,
                detail="La base de datos no está disponible",
            ) from error
        return {"status": "ok", "database": "available"}

    return app


app = create_app()
