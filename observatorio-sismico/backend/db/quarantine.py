"""Cuarentena duradera: nunca se descarta un registro rechazado sin dejar constancia."""

from dataclasses import dataclass

from psycopg import AsyncConnection


@dataclass(frozen=True)
class KafkaRef:
    topic: str
    partition: int
    offset: int


_INSERT = """
INSERT INTO quarantine_record
    (event_id, source, reason, original_payload, kafka_topic, kafka_partition, kafka_offset)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (kafka_topic, kafka_partition, kafka_offset)
    WHERE kafka_topic IS NOT NULL
DO NOTHING
"""


def payload_to_text(raw: bytes) -> str:
    """Texto almacenable del mensaje original.

    Los bytes no UTF-8 se decodifican con U+FFFD y se sustituye NUL, que TEXT no admite.
    La referencia (topic, partition, offset) permite recuperar los bytes exactos mientras Kafka los retenga.
    """
    return raw.decode("utf-8", errors="replace").replace("\x00", "�")


async def quarantine(
    conn: AsyncConnection,
    *,
    raw: bytes,
    reason: str,
    ref: KafkaRef,
    event_id: str | None = None,
    source: str | None = None,
) -> bool:
    """Registra el rechazo. Idempotente por offset de Kafka. Devuelve True si insertó una fila nueva."""
    async with conn.transaction():
        cursor = await conn.execute(
            _INSERT,
            (event_id, source, reason, payload_to_text(raw), ref.topic, ref.partition, ref.offset),
        )
        return cursor.rowcount == 1
