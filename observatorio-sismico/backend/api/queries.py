"""Acceso a PostgreSQL de la API (solo lectura) detrás de una interfaz sustituible en tests.

El esquema (demo / live / replay) sale de una lista cerrada y se compone con `sql.Identifier`;
nunca se interpola texto del usuario.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

import psycopg
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from backend.api.errors import DatabaseUnavailable
from backend.api.geojson import build_feature_from_row
from backend.db.modes import EVENT_MODES, schema_for_mode

log = logging.getLogger("api")


@dataclass(frozen=True)
class EventsPage:
    features: list[dict]
    total: int
    truncated: bool
    last_ingestion: int | None
    mode: str


@dataclass(frozen=True)
class HealthInfo:
    last_ingestion: int | None


class EventQueries(Protocol):
    async def fetch_events(
        self, start_ms: int | None, end_ms: int | None, limit: int, mode: str
    ) -> EventsPage: ...
    async def fetch_health(self, mode: str) -> HealthInfo: ...
    async def open(self) -> None: ...
    async def close(self) -> None: ...


def _ms(value) -> int | None:
    return None if value is None else int(value.timestamp() * 1000)


def _checked_schema(mode: str) -> str:
    if mode not in EVENT_MODES:
        raise ValueError(f"mode must be one of {EVENT_MODES}")
    return schema_for_mode(mode)


class PostgresQueries:
    def __init__(self, conninfo: str, *, max_size: int = 5, timeout: float = 3.0) -> None:
        self._pool = AsyncConnectionPool(
            conninfo,
            min_size=1,
            max_size=max_size,
            timeout=timeout,
            open=False,
            kwargs={"autocommit": True, "connect_timeout": 3},
        )

    async def open(self) -> None:
        # Sin esperar: la API arranca aunque la base no esté lista y responde 503 hasta que lo esté.
        await self._pool.open(wait=False)

    async def close(self) -> None:
        await self._pool.close()

    async def _last_ingestion(self, conn, mode: str) -> int | None:
        """Última ingesta correcta del modo, en ms Unix UTC (`null` si no hay ninguna).

        live:  última CONSULTA correcta a USGS (ingest.extraction_log, ok = true). Es lo que define el contrato y
               puede avanzar aunque no haya eventos nuevos. Si el productor falla, deja de avanzar: el panel lo detecta.
        demo / replay: no hay consultas a USGS; se usa la última ingesta de mensajes aceptada.
        """
        if mode == "live":
            query = sql.SQL(
                "SELECT started_at FROM ingest.extraction_log WHERE mode = 'live' AND ok "
                "ORDER BY started_at DESC LIMIT 1"  # usa ix_extraction_log_ok_started
            )
        else:
            # ORDER BY ... LIMIT 1 usa ix_event_message_ingested_at (búsqueda por índice, no recorrido completo).
            query = sql.SQL("SELECT ingested_at FROM {} ORDER BY ingested_at DESC LIMIT 1").format(
                sql.Identifier(schema_for_mode(mode), "event_message")
            )
        row = await (await conn.execute(query)).fetchone()
        return _ms(row[0]) if row else None

    async def fetch_events(self, start_ms: int | None, end_ms: int | None, limit: int, mode: str) -> EventsPage:
        schema = _checked_schema(mode)
        table = sql.Identifier(schema, "event_current")
        conditions, params = [], []
        if start_ms is not None:
            conditions.append(sql.SQL("c.time_ms >= %s"))
            params.append(start_ms)
        if end_ms is not None:
            conditions.append(sql.SQL("c.time_ms < %s"))
            params.append(end_ms)
        where = sql.SQL("WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")
        base = sql.SQL("FROM {} c LEFT JOIN ref.dim_country dc ON dc.country_id = c.country_id {}").format(table, where)
        select = sql.SQL(
            "SELECT c.event_id, c.lon, c.lat, c.depth_km, c.mag, c.mag_type, c.place, c.time_ms, "
            "c.current_version_ms, c.country_id, dc.name_es "
        )
        try:
            async with self._pool.connection() as conn:
                cursor = await conn.execute(
                    select + base + sql.SQL(" ORDER BY c.time_ms DESC, c.event_id LIMIT %s"), (*params, limit + 1)
                )
                rows = await cursor.fetchall()
                truncated = len(rows) > limit
                rows = rows[:limit]
                if truncated:
                    cursor = await conn.execute(sql.SQL("SELECT count(*) ") + base, params)
                    total = (await cursor.fetchone())[0]
                else:
                    total = len(rows)
                last_ingestion = await self._last_ingestion(conn, mode)
        except psycopg.Error as error:
            log.error("events query failed: %s", error)
            raise DatabaseUnavailable("The database query failed") from error

        features = []
        for row in rows:
            feature = build_feature_from_row(*row)
            if feature is None:  # no debería ocurrir: lon/lat tienen NOT NULL y CHECK de rango
                log.error("event %s has invalid stored coordinates; omitted", row[0])
                continue
            features.append(feature)
        return EventsPage(features, total, truncated, last_ingestion, mode)

    async def fetch_health(self, mode: str) -> HealthInfo:
        schema = _checked_schema(mode)
        try:
            async with self._pool.connection() as conn:
                await conn.execute("SELECT 1")
                last_ingestion = await self._last_ingestion(conn, mode)
        except psycopg.Error as error:
            log.error("health query failed: %s", error)
            raise DatabaseUnavailable("The database is not reachable") from error
        return HealthInfo(last_ingestion)
