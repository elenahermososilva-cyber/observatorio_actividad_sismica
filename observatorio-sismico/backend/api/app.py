"""API FastAPI de consulta (solo lectura). Uvicorn: backend.api.app:app en 0.0.0.0:8000.

Endpoints (CONTRATO-API.md):
  GET /api/eventos       GeoJSON. Filtros: start, end, min_mag, country_id, mode. Paginación: limit, offset.
  GET /api/estadisticas  Recuentos por hora UTC y país/subregión, distribuciones y comparación histórica.
                         Mismos filtros que /api/eventos.
  GET /api/salud         Estado de la API y de la base de datos, última ingesta y aviso de datos obsoletos.

No hay rutas de administración ni de documentación. Si la base falla, todos los endpoints devuelven un error
explícito (503); nunca un resultado vacío como si fuera válido.

`mode` (demo | live | replay) elige el esquema aislado de datos. Su valor por defecto es API_DEFAULT_MODE
(`live` si no se define). CORS: orígenes exactos de CORS_ORIGINS; solo GET y OPTIONS.
"""

import logging
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.cors import ALLOWED_HEADERS, ALLOWED_METHODS, parse_origins
from backend.api.errors import DatabaseUnavailable, InvalidParameter, error_body, register_error_handlers
from backend.api.geojson import CollectionMeta, build_collection
from backend.api.params import build_filters, parse_page
from backend.api.queries import EventQueries, PostgresQueries
from backend.api.stats import GROUPINGS, assess_freshness, build_statistics
from backend.common.config import database_url, get_int, get_str
from backend.common.logging_setup import configure_logging
from backend.db.modes import EVENT_MODES

log = logging.getLogger("api")
DEFAULT_BASELINE_YEAR = 2025


def now_ms() -> int:
    return int(time.time() * 1000)


def create_app(
    queries: EventQueries | None = None,
    *,
    clock: Callable[[], int] = now_ms,
    max_features: int | None = None,
    default_mode: str | None = None,
    cors_origins: list[str] | None = None,
    stale_after_seconds: int | None = None,
    baseline_year: int | None = None,
) -> FastAPI:
    state: dict = {
        "queries": queries, "max_features": max_features, "default_mode": default_mode,
        "stale_after": stale_after_seconds, "baseline_year": baseline_year,
    }

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
        if state["stale_after"] is None:
            state["stale_after"] = get_int("STALE_AFTER_SECONDS", 300, minimum=10)
        if state["baseline_year"] is None:
            state["baseline_year"] = get_int("HISTORY_BASELINE_YEAR", DEFAULT_BASELINE_YEAR, minimum=1900)
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

    # Orígenes EXACTOS de CORS_ORIGINS (nunca «*»). Un origen o comodín mal escrito es un error de arranque.
    origins = cors_origins if cors_origins is not None else parse_origins(os.environ.get("CORS_ORIGINS"))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=ALLOWED_METHODS,
        allow_headers=ALLOWED_HEADERS,
        allow_credentials=False,  # API pública de consulta: sin cookies
        max_age=600,
    )
    app.state.cors_origins = origins

    def check_mode(mode: str | None) -> str:
        mode = mode or state["default_mode"]
        if mode not in EVENT_MODES:
            raise InvalidParameter(f"mode must be one of {', '.join(EVENT_MODES)}, got {mode!r}")
        return mode

    @app.get("/api/eventos")
    async def eventos(
        start: str | None = Query(None, description="ISO8601, inclusive. Por defecto: ahora - 24 h"),
        end: str | None = Query(None, description="ISO8601, exclusivo"),
        min_mag: str | None = Query(None, description="Magnitud mínima. Una magnitud nula nunca la cumple"),
        country_id: str | None = Query(None, description="ADM0_A3, o 'none' para «Sin país asignado»"),
        mode: str | None = Query(None, description="demo | live | replay (datos aislados por modo)"),
        limit: str | None = Query(None, description="Máximo de puntos por respuesta (≤ API_MAX_FEATURES)"),
        offset: str | None = Query(None, description="Desplazamiento para paginar"),
    ) -> JSONResponse:
        generated = clock()
        mode = check_mode(mode)
        filters = build_filters(start, end, min_mag, country_id, generated)
        page_limit, page_offset = parse_page(limit, offset, state["max_features"])

        page = await state["queries"].fetch_events(filters, page_limit, page_offset, mode)
        meta = CollectionMeta(
            generated=generated, last_ingestion=page.last_ingestion, mode=page.mode, truncated=page.truncated,
            start=filters.start_ms, end=filters.end_ms, total=page.total, limit=page.limit, offset=page.offset,
            null_mag_count=page.null_mag_count, null_mag_excluded=page.null_mag_excluded, filters=filters.describe(),
        )
        return JSONResponse(build_collection(page.features, meta))

    @app.get("/api/estadisticas")
    async def estadisticas(
        start: str | None = Query(None, description="ISO8601, inclusive. Por defecto: ahora - 24 h"),
        end: str | None = Query(None, description="ISO8601, exclusivo"),
        min_mag: str | None = Query(None),
        country_id: str | None = Query(None),
        mode: str | None = Query(None),
        group: str = Query("country", description="country | subregion: agrupación de los recuentos por hora"),
        baseline_year: str | None = Query(None, description="Año histórico de referencia (por defecto 2025)"),
    ) -> JSONResponse:
        generated = clock()
        mode = check_mode(mode)
        filters = build_filters(start, end, min_mag, country_id, generated)
        if group not in GROUPINGS:
            raise InvalidParameter(f"group must be one of {', '.join(GROUPINGS)}, got {group!r}")
        year = state["baseline_year"]
        if baseline_year not in (None, ""):
            try:
                year = int(baseline_year)
            except ValueError as error:
                raise InvalidParameter(f"baseline_year must be an integer, got {baseline_year!r}") from error
            if not 1900 <= year <= 2200:
                raise InvalidParameter(f"baseline_year out of range: {year}")

        data = await state["queries"].fetch_statistics(filters, mode, generated, group, year)
        return JSONResponse(build_statistics(data, filters, mode=mode, generated=generated, group_by=group))

    @app.get("/api/salud")
    async def salud(mode: str | None = Query(None, description="Modo cuya última ingesta se evalúa")) -> JSONResponse:
        generated = clock()
        mode = check_mode(mode)
        try:
            info = await state["queries"].fetch_health(mode)
        except DatabaseUnavailable as error:
            return JSONResponse(
                {
                    "status": "error", "api": "ok", "database": "unavailable", "mode": mode, "generated": generated,
                    "last_ingestion": None, "stale": None, **error_body(error.code, error.message),
                },
                status_code=503,
            )
        freshness = assess_freshness(mode, info.last_ingestion, generated, state["stale_after"])
        return JSONResponse(
            {
                # «stale»: la API y la base funcionan (HTTP 200) pero los datos live ya no se están actualizando.
                "status": "stale" if freshness.stale else "ok",
                "api": "ok",
                "database": "ok",
                "mode": mode,
                "generated": generated,
                "last_ingestion": info.last_ingestion,
                "stale": freshness.stale,
                "stale_after_seconds": state["stale_after"],
                "seconds_since_last_ingestion": freshness.seconds_since_last_ingestion,
                "stale_reason": freshness.reason,
            }
        )

    return app


app = create_app()
