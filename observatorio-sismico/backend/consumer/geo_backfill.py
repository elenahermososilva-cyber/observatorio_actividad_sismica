"""Evalúa país y calidad de filas de `event_current` que aún no lo tienen.

Cubre dos casos: filas escritas antes de existir la atribución (`country_status = 'pending'`) y filas sin evaluar
(`quality_flags IS NULL`). Es idempotente y solo toca esas filas: un evento ya evaluado no se vuelve a calcular.
Se ejecuta al arrancar el consumidor y también a mano:

    docker compose run --rm --no-deps consumer python -m backend.consumer.geo_backfill
"""

import asyncio
import logging
import os
from datetime import timezone
from pathlib import Path

import psycopg
from psycopg import sql

from backend.common.config import database_url, get_str
from backend.common.logging_setup import configure_logging
from backend.consumer.geo import CountryIndex
from backend.consumer.quality import assess
from backend.db.columns import extract_columns
from backend.db.modes import MODE_SCHEMAS

log = logging.getLogger("geo_backfill")
BATCH = 500


async def backfill_schema(conn: psycopg.AsyncConnection, schema: str, geo: CountryIndex) -> int:
    event_current = sql.Identifier(schema, "event_current")
    event_message = sql.Identifier(schema, "event_message")
    select = sql.SQL(
        "SELECT c.event_id, c.current_version_ms, m.payload, m.ingested_at FROM {} c JOIN {} m USING (message_id) "
        "WHERE c.country_status = 'pending' OR c.quality_flags IS NULL ORDER BY c.event_id LIMIT %s"
    ).format(event_current, event_message)
    update = sql.SQL(
        "UPDATE {} SET place = %s, mag_type = %s, country_id = %s, country_status = %s, quality_flags = %s "
        "WHERE event_id = %s AND current_version_ms = %s"
    ).format(event_current)

    total = 0
    while True:
        rows = await (await conn.execute(select, (BATCH,))).fetchall()
        if not rows:
            return total
        async with conn.transaction():
            for event_id, version, payload, ingested_at in rows:
                assessment = assess(extract_columns(payload, ingested_at.astimezone(timezone.utc)), version)
                c = assessment.columns
                attribution = geo.locate(c.lon, c.lat)
                await conn.execute(
                    update,
                    (c.place, c.mag_type, attribution.country_id, attribution.status,
                     list(assessment.flags) + list(attribution.flags), event_id, version),
                )
        total += len(rows)


async def backfill_all(conn: psycopg.AsyncConnection, geo: CountryIndex) -> dict[str, int]:
    done = {}
    for schema in MODE_SCHEMAS:
        count = await backfill_schema(conn, schema, geo)
        if count:
            log.info("backfill %s: %d events evaluated (country + quality)", schema, count)
        done[schema] = count
    return done


async def main() -> int:
    configure_logging("geo_backfill")
    geo = CountryIndex.from_file(Path(get_str("COUNTRIES_GEOJSON", "/app/data/paises.geojson")))
    async with await psycopg.AsyncConnection.connect(database_url(os.environ), autocommit=True) as conn:
        done = await backfill_all(conn, geo)
    log.info("done: %s", done)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
