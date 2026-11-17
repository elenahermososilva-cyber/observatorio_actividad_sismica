"""Estado persistente del productor en PostgreSQL (D1): esquema `ingest`.

- `published_version`: versiones (event_id, updated_ms) ya publicadas por modo. Se marca SOLO tras el ack de Kafka.
  Si el proceso cae entre ambas operaciones se reenvía el mensaje y el consumidor lo tolera (idempotencia).
- `extraction_log`: una fila por consulta a USGS. Solo las consultas `ok` mueven `last_ingestion`.
"""

from datetime import datetime

from psycopg import AsyncConnection


async def already_published(conn: AsyncConnection, mode: str, keys: list[tuple[str, int]]) -> set[tuple[str, int]]:
    """Subconjunto de `keys` que ya está registrado como publicado (una sola consulta para todo el lote)."""
    if not keys:
        return set()
    cursor = await conn.execute(
        "SELECT event_id, updated_ms FROM ingest.published_version "
        "WHERE mode = %s AND (event_id, updated_ms) IN (SELECT * FROM unnest(%s::text[], %s::bigint[]))",
        (mode, [k[0] for k in keys], [k[1] for k in keys]),
    )
    return {(row[0], row[1]) for row in await cursor.fetchall()}


async def mark_published(conn: AsyncConnection, mode: str, event_id: str, updated_ms: int) -> None:
    await conn.execute(
        "INSERT INTO ingest.published_version (mode, event_id, updated_ms) VALUES (%s, %s, %s) "
        "ON CONFLICT DO NOTHING",
        (mode, event_id, updated_ms),
    )


async def last_ok_content_hash(conn: AsyncConnection, mode: str) -> str | None:
    cursor = await conn.execute(
        "SELECT response_sha256 FROM ingest.extraction_log WHERE mode = %s AND ok "
        "ORDER BY started_at DESC, extraction_id DESC LIMIT 1",
        (mode,),
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def log_extraction(
    conn: AsyncConnection,
    *,
    mode: str,
    url: str,
    started_at: datetime,
    ok: bool,
    latency_ms: int | None = None,
    http_status: int | None = None,
    record_count: int | None = None,
    response_bytes: int | None = None,
    content_sha256: str | None = None,
    raw_path: str | None = None,
    error: str | None = None,
) -> None:
    await conn.execute(
        "INSERT INTO ingest.extraction_log (mode, source_url, started_at, latency_ms, http_status, ok, "
        "record_count, response_bytes, response_sha256, raw_path, error) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (mode, url, started_at, latency_ms, http_status, ok, record_count, response_bytes, content_sha256, raw_path, error),
    )
