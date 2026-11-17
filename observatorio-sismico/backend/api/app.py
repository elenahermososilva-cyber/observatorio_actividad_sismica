"""API FastAPI de consulta (solo lectura). Uvicorn: backend.api.app:app en 0.0.0.0:8000.

Endpoints: GET /api/eventos (start, end, mode), GET /api/salud.
Filtros min_mag/country_id, estadísticas, paginación y CORS llegan en la Fase 9.

`mode` (demo | live | replay) elige el esquema aislado de datos. Su valor por defecto es API_DEFAULT_MODE
(`live` si no se define); el stack de la entrega vertical lo fija en `demo` desde .env.
"""

import logging
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from backend.api.errors import DatabaseUnavailable, InvalidParameter, error_body, register_error_handlers
from backend.api.geojson import CollectionMeta, build_collection
from backend.api.queries import EventQueries, PostgresQueries
from backend.common.config import database_url, get_int, get_str
from backend.common.logging_setup import configure_logging
from backend.db.modes import EVENT_MODES

log = logging.getLogger("api")
DEFAULT_WINDOW_MS = 24 * 3600 * 1000


def now_ms() -> int:
    return int(time.time() * 1000)


def parse_instant(name: str, value: str) -> int:
    """ISO8601 → ms Unix UTC. Sin zona horaria se interpreta como UTC."""
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as error:
        raise InvalidParameter(f"{name} must be an ISO8601 date or datetime, got {value!r}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def create_app(
    queries: EventQueries | None = None,
    *,
    clock: Callable[[], int] = now_ms,
    max_features: int | None = None,
    default_mode: str | None = None,
) -> FastAPI:
    state: dict = {"queries": queries, "max_features": max_features, "default_mode": default_mode}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if state["queries"] is None:
            configure_logging("api")
            state["queries"] = PostgresQueries(database_url())
        await state["queries"].open()
        if state["max_features"] is None:
            state["max_features"] = get_int("API_MAX_FEATURES", 5000, minimum=1)
        if state["default_mode"] is None:
            state["default_mode"] = get_str("API_DEFAULT_MODE", "live")
        if state["default_mode"] not in EVENT_MODES:
            raise ValueError(f"API_DEFAULT_MODE must be one of {EVENT_MODES}")
        yield
        await state["queries"].close()

    app = FastAPI(
        title="Observatorio sísmico API",
        lifespan=lifespan,
        docs_url=None,  # sin rutas auxiliares expuestas por el túnel
        redoc_url=None,
        openapi_url=None,
    )
    register_error_handlers(app)

    def check_mode(mode: str | None) -> str:
        mode = mode or state["default_mode"]
        if mode not in EVENT_MODES:
            raise InvalidParameter(f"mode must be one of {', '.join(EVENT_MODES)}, got {mode!r}")
        return mode

    @app.get("/api/eventos")
    async def eventos(
        start: str | None = Query(None, description="ISO8601, inclusive. Por defecto: ahora - 24 h"),
        end: str | None = Query(None, description="ISO8601, exclusivo"),
        mode: str | None = Query(None, description="demo | live | replay (datos aislados por modo)"),
    ) -> JSONResponse:
        generated = clock()
        mode = check_mode(mode)
        start_ms = parse_instant("start", start) if start else generated - DEFAULT_WINDOW_MS
        end_ms = parse_instant("end", end) if end else None
        if end_ms is not None and start_ms >= end_ms:
            raise InvalidParameter("start must be earlier than end")

        page = await state["queries"].fetch_events(start_ms, end_ms, state["max_features"], mode)
        meta = CollectionMeta(
            generated=generated,
            last_ingestion=page.last_ingestion,
            mode=page.mode,
            truncated=page.truncated,
            start=start_ms,
            end=end_ms,
            total=page.total,
        )
        return JSONResponse(build_collection(page.features, meta))

    @app.get("/api/salud")
    async def salud() -> JSONResponse:
        generated = clock()
        try:
            info = await state["queries"].fetch_health(state["default_mode"])
        except DatabaseUnavailable as error:
            return JSONResponse(
                {
                    "status": "error",
                    "api": "ok",
                    "database": "unavailable",
                    "generated": generated,
                    "last_ingestion": None,
                    **error_body(error.code, error.message),
                },
                status_code=503,
            )
        return JSONResponse(
            {
                "status": "ok",
                "api": "ok",
                "database": "ok",
                "generated": generated,
                "last_ingestion": info.last_ingestion,
            }
        )

    return app


app = create_app()
