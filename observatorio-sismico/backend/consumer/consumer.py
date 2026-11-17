"""Consumidor Kafka → PostgreSQL con procesamiento al-menos-una-vez y escritura idempotente.

Regla central: el offset se confirma SOLO después de que PostgreSQL haya hecho COMMIT
(del evento o de su registro de cuarentena).

- Dato inválido (JSON, esquema, coordenadas, tipo ≠ earthquake): cuarentena durable y luego commit del offset.
- Violación de restricción de la base por un mensaje ya validado: también a cuarentena (evita un "poison pill").
- Fallo de infraestructura (PostgreSQL no disponible): NO se confirma; se reconecta con espera
  progresiva y se reintenta el mismo mensaje. No se escribe en cuarentena porque tampoco hay base donde hacerlo.

Uso: python -m backend.consumer.consumer
"""

import asyncio
import logging
import os
import signal
from pathlib import Path
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TypeVar

import psycopg
from psycopg import sql

from backend.common.backoff import backoff_delays, retry_async
from backend.common.config import database_url, get_list, get_str
from backend.common.health import heartbeat_loop
from backend.common.logging_setup import configure_logging
from backend.consumer.geo import CountryIndex
from backend.consumer.geo_backfill import backfill_all
from backend.consumer.processing import Rejection, RejectionReason, parse_message
from backend.consumer.versioning import VersionDecision
from backend.db.connection import Database
from backend.db.modes import EVENT_MODES, schema_for_mode
from backend.db.quarantine import KafkaRef, quarantine
from backend.db.repository import store_message

log = logging.getLogger("consumer")
T = TypeVar("T")

DB_ERRORS_TO_QUARANTINE = (psycopg.errors.DataError, psycopg.errors.IntegrityError)


@dataclass(frozen=True)
class HandleResult:
    decision: VersionDecision | None = None
    rejection: Rejection | None = None


async def use_mode_schema(conn: psycopg.AsyncConnection, mode: str) -> None:
    """Dirige las escrituras al esquema del modo (D2). `mode` sale de una lista cerrada, nunca de texto libre."""
    await conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_for_mode(mode))))


async def handle_record(
    conn: psycopg.AsyncConnection, raw: bytes, ref: KafkaRef, mode: str = "demo", geo: CountryIndex | None = None
) -> HandleResult:
    """Procesa un mensaje completo. Al volver, el resultado ya está confirmado (COMMIT) en PostgreSQL.

    `mode` es el modo que corresponde al topic de origen; el mensaje debe declarar el mismo (aislamiento).
    """
    await use_mode_schema(conn, mode)
    parsed = parse_message(raw)
    if not isinstance(parsed, Rejection) and parsed.mode.value != mode:
        parsed = Rejection(
            RejectionReason.MODE_MISMATCH,
            f"message mode {parsed.mode.value!r} does not match topic mode {mode!r}",
            parsed.event_id,
            parsed.source,
        )
    if isinstance(parsed, Rejection):
        await quarantine(conn, raw=raw, reason=parsed.text, ref=ref, event_id=parsed.event_id, source=parsed.source)
        log.warning("quarantined %s/%d@%d: %s", ref.topic, ref.partition, ref.offset, parsed.text)
        return HandleResult(rejection=parsed)

    try:
        stored = await store_message(conn, parsed, geo)
    except DB_ERRORS_TO_QUARANTINE as error:
        rejection = Rejection(
            RejectionReason.PERSISTENCE_CONSTRAINT, f"{type(error).__name__}: {error}", parsed.event_id, parsed.source
        )
        await quarantine(
            conn, raw=raw, reason=rejection.text, ref=ref, event_id=parsed.event_id, source=parsed.source
        )
        log.error("quarantined (database rejected) %s/%d@%d: %s", ref.topic, ref.partition, ref.offset, rejection.text)
        return HandleResult(rejection=rejection)

    log.info(
        "%s event_id=%s updated=%d (%s/%d@%d)",
        stored.decision.value.upper(), parsed.event_id, parsed.updated_ms, ref.topic, ref.partition, ref.offset,
    )
    return HandleResult(decision=stored.decision)


async def _start_consumer(bootstrap: str, group_id: str, topics: list[str]):
    from aiokafka import AIOKafkaConsumer

    async def connect() -> AIOKafkaConsumer:
        consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap,
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        try:
            await consumer.start()
        except Exception:
            await consumer.stop()
            raise
        return consumer

    return await retry_async(connect, maximum=15.0, description="kafka connection")


def topic_modes(env: Mapping[str, str]) -> dict[str, str]:
    """topic -> modo. Un topic por modo (D2); el modo decide el esquema de destino."""
    defaults = {"demo": "sismos.demo", "live": "sismos.live", "replay": "sismos.replay"}
    mapping = {get_str(f"KAFKA_TOPIC_{mode.upper()}", defaults[mode], env): mode for mode in EVENT_MODES}
    if len(mapping) != len(EVENT_MODES):
        raise ValueError("KAFKA_TOPIC_DEMO/LIVE/REPLAY must be three different topics")
    return mapping


async def consume(consumer, db: Database, modes: Mapping[str, str], geo: CountryIndex) -> None:
    from aiokafka import TopicPartition

    async for record in consumer:
        ref = KafkaRef(record.topic, record.partition, record.offset)
        mode = modes[record.topic]
        await db.run(lambda conn: handle_record(conn, record.value, ref, mode, geo))
        # Solo aquí, tras el COMMIT en PostgreSQL:
        await consumer.commit({TopicPartition(record.topic, record.partition): record.offset + 1})


async def main(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    configure_logging("consumer")
    bootstrap = get_str("KAFKA_BOOTSTRAP_SERVERS", env=env)
    group_id = get_str("KAFKA_CONSUMER_GROUP", "observatorio-consumer", env)
    modes = topic_modes(env)
    topics = get_list("CONSUMER_TOPICS", ",".join(modes), env)
    unknown = [t for t in topics if t not in modes]
    if unknown:
        raise ValueError(f"CONSUMER_TOPICS contains topics without a mode: {unknown}")
    db = Database(database_url(env), hint="offset NOT committed")
    # Sin catálogo no hay atribución de país: es un fallo de arranque, no algo que se omita en silencio.
    geo = CountryIndex.from_file(Path(get_str("COUNTRIES_GEOJSON", "/app/data/paises.geojson", env)))
    log.info("country index ready: %d countries (repaired geometries: %s)", len(geo), geo.repaired or "none")
    # Evalúa lo que quedó sin país/calidad (filas anteriores a esta versión o escritas sin índice).
    await db.run(lambda conn: backfill_all(conn, geo))

    heartbeat = asyncio.create_task(heartbeat_loop())
    consumer = await _start_consumer(bootstrap, group_id, topics)
    log.info("consuming %s as group %s", topics, group_id)
    task = asyncio.create_task(consume(consumer, db, modes, geo))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, task.cancel)
        except NotImplementedError:  # Windows
            pass
    try:
        await task
    except asyncio.CancelledError:
        log.info("shutdown requested")
    finally:
        heartbeat.cancel()
        await consumer.stop()
        await db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
