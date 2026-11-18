"""Acceso a PostgreSQL de la API (solo lectura) detrás de una interfaz sustituible en tests.

- El esquema (demo / live / replay) sale de una lista cerrada y se compone con `sql.Identifier`; nunca se interpola
  texto del usuario. Los valores de los filtros van siempre como parámetros (`%s`).
- Todas las lecturas de una respuesta se hacen en UNA transacción de solo lectura con aislamiento REPEATABLE READ:
  el total, la página y las series ven la misma instantánea, aunque el productor escriba entretanto.
- Las estadísticas se calculan en la base de datos sobre TODO el conjunto filtrado (índices en time_ms, country_id, mag).
"""

import logging
from dataclasses import dataclass
from typing import Protocol

import psycopg
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from backend.api.exceptions import DatabaseUnavailable, InvalidParameter
from backend.api.geojson import build_feature_from_row
from backend.api.params import NO_COUNTRY, EventFilters
from backend.api.stats import (
    COMPARISON_MIN_MAG, DAY_MS, DEPTH_BIN_KM, HOUR_MS, MAG_BIN_WIDTH, BaselineData, GroupRow, StatsData, year_bounds_ms,
)
from backend.db.modes import EVENT_MODES, schema_for_mode

log = logging.getLogger("api")
HISTORICAL_SCHEMA = "historico"


@dataclass(frozen=True)
class EventsPage:
    features: list[dict]
    total: int
    truncated: bool
    last_ingestion: int | None
    mode: str
    limit: int | None = None
    offset: int = 0
    null_mag_count: int = 0
    null_mag_excluded: int = 0


@dataclass(frozen=True)
class HealthInfo:
    last_ingestion: int | None


class EventQueries(Protocol):
    async def fetch_events(self, filters: EventFilters, limit: int, offset: int, mode: str) -> EventsPage: ...
    async def fetch_statistics(
        self, filters: EventFilters, mode: str, generated_ms: int, group_by: str, baseline_year: int
    ) -> StatsData: ...
    async def fetch_health(self, mode: str) -> HealthInfo: ...
    async def open(self) -> None: ...
    async def close(self) -> None: ...


def _ms(value) -> int | None:
    return None if value is None else int(value.timestamp() * 1000)


def _checked_schema(mode: str) -> str:
    if mode not in EVENT_MODES:
        raise ValueError(f"mode must be one of {EVENT_MODES}")
    return schema_for_mode(mode)


def _conditions(
    filters: EventFilters, *, start_ms: int | None = None, end_ms: int | None = None, min_mag: float | None = None,
    use_min_mag: bool = True, use_country: bool = True,
) -> tuple[list[sql.Composable], list]:
    """Condiciones WHERE sobre `c` (event_current). Con `start_ms`/`end_ms`/`min_mag` se sustituyen los de `filters`.
    Una magnitud nula nunca cumple `c.mag >= x` (NULL no es verdadero), como exige el contrato."""
    conditions: list[sql.Composable] = []
    params: list = []
    start = filters.start_ms if start_ms is None else start_ms
    end = filters.end_ms if end_ms is None else end_ms
    threshold = filters.min_mag if min_mag is None else min_mag
    conditions.append(sql.SQL("c.time_ms >= %s"))
    params.append(start)
    if end is not None:
        conditions.append(sql.SQL("c.time_ms < %s"))
        params.append(end)
    if use_min_mag and threshold is not None:
        conditions.append(sql.SQL("c.mag >= %s"))
        params.append(threshold)
    if use_country and filters.country_id == NO_COUNTRY:
        conditions.append(sql.SQL("c.country_status = 'unassigned'"))
    elif use_country and filters.country_id:
        conditions.append(sql.SQL("c.country_id = %s"))
        params.append(filters.country_id)
    return conditions, params


def _where(conditions: list[sql.Composable]) -> sql.Composable:
    return sql.SQL("WHERE ") + sql.SQL(" AND ").join(conditions)


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

    @staticmethod
    async def _snapshot(conn) -> None:
        await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")

    @staticmethod
    async def _ensure_country_exists(conn, country_id: str | None) -> None:
        if country_id in (None, NO_COUNTRY):
            return
        row = await (await conn.execute("SELECT 1 FROM ref.dim_country WHERE country_id = %s", (country_id,))).fetchone()
        if row is None:
            raise InvalidParameter(f"unknown country_id {country_id!r}; use an ADM0_A3 code from the catalogue or 'none'")

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

    # ------------------------------------------------------------------------------------------ /api/eventos
    async def fetch_events(self, filters: EventFilters, limit: int, offset: int, mode: str) -> EventsPage:
        schema = _checked_schema(mode)
        table = sql.Identifier(schema, "event_current")
        conditions, params = _conditions(filters)
        where = _where(conditions)
        from_clause = sql.SQL("FROM {} c LEFT JOIN ref.dim_country dc ON dc.country_id = c.country_id ").format(table)
        select = sql.SQL(
            "SELECT c.event_id, c.lon, c.lat, c.depth_km, c.mag, c.mag_type, c.place, c.time_ms, "
            "c.current_version_ms, c.country_id, dc.name_es "
        )
        try:
            async with self._pool.connection() as conn:
                async with conn.transaction():
                    await self._snapshot(conn)
                    await self._ensure_country_exists(conn, filters.country_id)
                    rows = await (await conn.execute(
                        select + from_clause + where + sql.SQL(" ORDER BY c.time_ms DESC, c.event_id LIMIT %s OFFSET %s"),
                        (*params, limit, offset),
                    )).fetchall()
                    total, null_mag_count = await (await conn.execute(
                        sql.SQL("SELECT count(*), count(*) FILTER (WHERE c.mag IS NULL) FROM {} c ").format(table) + where,
                        params,
                    )).fetchone()
                    null_excluded = 0
                    if filters.min_mag is not None:
                        # Eventos de magnitud nula que cumplen el resto de filtros: no pueden satisfacer min_mag.
                        other, other_params = _conditions(filters, use_min_mag=False)
                        null_excluded = (await (await conn.execute(
                            sql.SQL("SELECT count(*) FROM {} c ").format(table)
                            + _where(other + [sql.SQL("c.mag IS NULL")]),
                            other_params,
                        )).fetchone())[0]
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
        return EventsPage(
            features, total, offset + len(rows) < total, last_ingestion, mode, limit, offset, null_mag_count, null_excluded
        )

    # ------------------------------------------------------------------------------------------ /api/estadisticas
    async def fetch_statistics(
        self, filters: EventFilters, mode: str, generated_ms: int, group_by: str, baseline_year: int
    ) -> StatsData:
        schema = _checked_schema(mode)
        table = sql.Identifier(schema, "event_current")
        historical = sql.Identifier(HISTORICAL_SCHEMA, "event_current")
        conditions, params = _conditions(filters)
        where = _where(conditions)
        ref_ms = filters.end_ms if filters.end_ms is not None else generated_ms
        threshold = max(filters.min_mag if filters.min_mag is not None else COMPARISON_MIN_MAG, COMPARISON_MIN_MAG)
        year_start, year_end = year_bounds_ms(baseline_year)
        try:
            async with self._pool.connection() as conn:
                async with conn.transaction():
                    await self._snapshot(conn)
                    await self._ensure_country_exists(conn, filters.country_id)

                    total, missing_mag, missing_depth = await (await conn.execute(
                        sql.SQL(
                            "SELECT count(*), count(*) FILTER (WHERE c.mag IS NULL), "
                            "count(*) FILTER (WHERE c.depth_km IS NULL) FROM {} c "
                        ).format(table) + where, params,
                    )).fetchone()

                    hourly = dict(await (await conn.execute(
                        sql.SQL("SELECT (c.time_ms / %s) * %s AS hour, count(*) FROM {} c ").format(table)
                        + where + sql.SQL(" GROUP BY 1"),
                        (HOUR_MS, HOUR_MS, *params),
                    )).fetchall())

                    group_rows = [
                        GroupRow(hour, status, country_id, name, subregion, count)
                        for hour, status, country_id, name, subregion, count in await (await conn.execute(
                            sql.SQL(
                                "SELECT (c.time_ms / %s) * %s, c.country_status, c.country_id, dc.name_es, dc.subregion, count(*) "
                                "FROM {} c LEFT JOIN ref.dim_country dc ON dc.country_id = c.country_id "
                            ).format(table) + where + sql.SQL(" GROUP BY 1, 2, 3, 4, 5"),
                            (HOUR_MS, HOUR_MS, *params),
                        )).fetchall()
                    ]

                    mag_bins = dict(await (await conn.execute(
                        sql.SQL("SELECT floor(c.mag / %s)::int, count(*) FROM {} c ").format(table)
                        + _where(conditions + [sql.SQL("c.mag IS NOT NULL")]) + sql.SQL(" GROUP BY 1"),
                        (MAG_BIN_WIDTH, *params),
                    )).fetchall())
                    depth_bins = dict(await (await conn.execute(
                        sql.SQL("SELECT floor(c.depth_km / %s)::int, count(*) FROM {} c ").format(table)
                        + _where(conditions + [sql.SQL("c.depth_km IS NOT NULL")]) + sql.SQL(" GROUP BY 1"),
                        (DEPTH_BIN_KM, *params),
                    )).fetchall())

                    # --- comparación: últimas 24 h (en el modo consultado) frente a la media diaria del año de referencia ---
                    win_conds, win_params = _conditions(filters, start_ms=ref_ms - DAY_MS, end_ms=ref_ms, min_mag=threshold)
                    window_count = (await (await conn.execute(
                        sql.SQL("SELECT count(*) FROM {} c ").format(table) + _where(win_conds), win_params
                    )).fetchone())[0]
                    nm_conds, nm_params = _conditions(
                        filters, start_ms=ref_ms - DAY_MS, end_ms=ref_ms, use_min_mag=False
                    )
                    window_null = (await (await conn.execute(
                        sql.SQL("SELECT count(*) FROM {} c ").format(table)
                        + _where(nm_conds + [sql.SQL("c.mag IS NULL")]), nm_params,
                    )).fetchone())[0]

                    year_total = (await (await conn.execute(
                        sql.SQL("SELECT count(*) FROM {} c WHERE c.time_ms >= %s AND c.time_ms < %s").format(historical),
                        (year_start, year_end),
                    )).fetchone())[0]
                    b_conds, b_params = _conditions(filters, start_ms=year_start, end_ms=year_end, min_mag=threshold)
                    base_events, base_days = await (await conn.execute(
                        sql.SQL("SELECT count(*), count(DISTINCT c.time_ms / %s) FROM {} c ").format(historical)
                        + _where(b_conds), (DAY_MS, *b_params),
                    )).fetchone()
                    # Distribución diaria del año con TODOS los días (generate_series): los días sin eventos valen 0.
                    n_days = (year_end - year_start) // DAY_MS
                    median_day, min_day, max_day = await (await conn.execute(
                        sql.SQL(
                            "WITH days AS (SELECT generate_series(0, %s - 1) AS d), "
                            "per_day AS (SELECT (c.time_ms - %s) / %s AS d, count(*) AS n FROM {} c "
                        ).format(historical) + _where(b_conds)
                        + sql.SQL(
                            " GROUP BY 1) SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY coalesce(per_day.n, 0)), "
                            "min(coalesce(per_day.n, 0)), max(coalesce(per_day.n, 0)) FROM days LEFT JOIN per_day USING (d)"
                        ),
                        (n_days, year_start, DAY_MS, *b_params),
                    )).fetchone()
                    bn_conds, bn_params = _conditions(
                        filters, start_ms=year_start, end_ms=year_end, use_min_mag=False
                    )
                    base_null = (await (await conn.execute(
                        sql.SQL("SELECT count(*) FROM {} c ").format(historical)
                        + _where(bn_conds + [sql.SQL("c.mag IS NULL")]), bn_params,
                    )).fetchone())[0]

                    last_ingestion = await self._last_ingestion(conn, mode)
        except psycopg.Error as error:
            log.error("statistics query failed: %s", error)
            raise DatabaseUnavailable("The database query failed") from error

        return StatsData(
            last_ingestion=last_ingestion, total=total, missing_mag=missing_mag, missing_depth=missing_depth,
            hourly=hourly, group_rows=group_rows, mag_bins=mag_bins, depth_bins=depth_bins,
            window_count=window_count, window_null_mag_excluded=window_null,
            baseline=BaselineData(
                baseline_year, year_total, base_events, base_days, base_null,
                None if median_day is None else float(median_day), min_day, max_day,
            ),
        )

    # ------------------------------------------------------------------------------------------ /api/salud
    async def fetch_health(self, mode: str) -> HealthInfo:
        _checked_schema(mode)
        try:
            async with self._pool.connection() as conn:
                await conn.execute("SELECT 1")
                last_ingestion = await self._last_ingestion(conn, mode)
        except psycopg.Error as error:
            log.error("health query failed: %s", error)
            raise DatabaseUnavailable("The database is not reachable") from error
        return HealthInfo(last_ingestion)
