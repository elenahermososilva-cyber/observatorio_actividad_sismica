"""Escritura idempotente de versiones de eventos en PostgreSQL.

Una sola transacción por mensaje:
1. Bloquea (FOR UPDATE) la fila actual del evento, si existe.
2. Clasifica la versión entrante (NEW / DUPLICATE / REVISION / STALE).
3. Guarda la versión en `event_message` salvo que ya exista (UNIQUE event_id, updated_ms).
   Una versión STALE se conserva en el historial pero NO toca `event_current`.
   Las tablas son las del esquema indicado en el `search_path` de la conexión (un esquema por modo, D2).
4. Solo NEW/REVISION actualizan `event_current`; el upsert lleva además un guardia
   `WHERE current_version_ms < EXCLUDED.current_version_ms`, de modo que ni una carrera
   entre consumidores puede hacer retroceder la versión actual.
"""

from dataclasses import dataclass

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from backend.consumer.versioning import EventVersion, VersionDecision, classify_version
from backend.db.columns import extract_columns
from backend.producer.schema import EventMessage


@dataclass(frozen=True)
class StoreResult:
    decision: VersionDecision
    history_row_inserted: bool
    current_updated: bool


_INSERT_MESSAGE = """
INSERT INTO event_message
    (event_id, updated_ms, source, mode, ingested_at, synthetic_flag, payload, replay_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (event_id, updated_ms) DO NOTHING
RETURNING message_id
"""

# country_id/country_status: una versión nueva puede mover el epicentro, así que la atribución previa se
# invalida ('pending') y la recalcula la fase de geografía. Nunca se conserva un país obsoleto.
_UPSERT_CURRENT = """
INSERT INTO event_current
    (event_id, message_id, current_version_ms, last_seen_at,
     time_ms, mag, mag_type, depth_km, lon, lat, place, event_type, ingested_at,
     country_id, country_status)
VALUES (%s, %s, %s, now(), %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, 'pending')
ON CONFLICT (event_id) DO UPDATE SET
    message_id = EXCLUDED.message_id,
    current_version_ms = EXCLUDED.current_version_ms,
    last_seen_at = EXCLUDED.last_seen_at,
    time_ms = EXCLUDED.time_ms,
    mag = EXCLUDED.mag,
    mag_type = EXCLUDED.mag_type,
    depth_km = EXCLUDED.depth_km,
    lon = EXCLUDED.lon,
    lat = EXCLUDED.lat,
    place = EXCLUDED.place,
    event_type = EXCLUDED.event_type,
    ingested_at = EXCLUDED.ingested_at,
    country_id = NULL,
    country_status = 'pending'
WHERE event_current.current_version_ms < EXCLUDED.current_version_ms
"""


async def store_message(conn: AsyncConnection, message: EventMessage) -> StoreResult:
    async with conn.transaction():
        cursor = await conn.execute(
            "SELECT current_version_ms FROM event_current WHERE event_id = %s FOR UPDATE",
            (message.event_id,),
        )
        row = await cursor.fetchone()
        current = EventVersion(message.event_id, row[0]) if row else None
        incoming = EventVersion(message.event_id, message.updated_ms)
        decision = classify_version(incoming, current)

        cursor = await conn.execute(
            _INSERT_MESSAGE,
            (
                message.event_id,
                message.updated_ms,
                message.source,
                message.mode.value,
                message.ingested_at,
                message.synthetic_flag,
                Jsonb(message.payload),
                message.replay_at,
            ),
        )
        inserted = await cursor.fetchone()

        current_updated = False
        if decision in (VersionDecision.NEW, VersionDecision.REVISION):
            if inserted is not None:
                message_id = inserted[0]
            else:  # la versión ya estaba en el historial: se reutiliza su fila
                cursor = await conn.execute(
                    "SELECT message_id FROM event_message WHERE event_id = %s AND updated_ms = %s",
                    (message.event_id, message.updated_ms),
                )
                message_id = (await cursor.fetchone())[0]
            c = extract_columns(message.payload, message.ingested_at)
            cursor = await conn.execute(
                _UPSERT_CURRENT,
                (
                    message.event_id, message_id, message.updated_ms,
                    c.time_ms, c.mag, c.mag_type, c.depth_km, c.lon, c.lat, c.place, c.event_type, c.ingested_at,
                ),
            )
            current_updated = cursor.rowcount == 1

    return StoreResult(decision, inserted is not None, current_updated)
