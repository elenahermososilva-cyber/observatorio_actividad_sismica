"""Productor Kafka.

PRODUCER_MODE selecciona qué hace este servicio:
  demo    evento sintético estable `demo-evt-001` (y duplicados opcionales); luego queda en reposo.
  live    consulta el feed de USGS cada POLL_SECONDS y publica novedades y revisiones (live.py).
  replay  reproduce de forma acelerada una selección del histórico en un topic aislado (replay.py).

Garantías:
- Clave Kafka = event_id (orden por evento dentro de la partición).
- `acks=all` y `send_and_wait`: un mensaje cuenta como publicado solo tras el ack del broker.
- Conexión con reintentos y espera progresiva (el healthcheck del broker no basta).
- En modo demo publica una vez y queda en reposo: con `restart: unless-stopped`
  un proceso que termina se relanzaría y reenviaría el evento sin parar.

Uso: python -m backend.producer.producer
"""

import asyncio
import logging
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Protocol

from backend.common.backoff import retry_async
from backend.common.config import database_url, get_int, get_str
from backend.common.health import heartbeat_loop
from backend.common.logging_setup import configure_logging
from backend.producer.schema import EventMessage, IngestionMode

log = logging.getLogger("producer")

DEMO_EVENT_ID = "demo-evt-001"
DEMO_SOURCE = "synthetic-demo"
# Fechas fijas: el evento es reproducible y distinguible de datos reales.
# 2026-10-27T14:00:00Z (ocurrencia) y +400 s = 14:06:40Z (actualización de la fuente).
DEMO_TIME_MS = 1_793_109_600_000
DEMO_UPDATED_MS = 1_793_110_000_000


class KafkaSender(Protocol):
    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> object: ...


def build_demo_message(
    ingested_at: datetime | None = None,
    updated_ms: int = DEMO_UPDATED_MS,
    mag: float | None = 3.2,
) -> EventMessage:
    """Evento sintético. `updated_ms` y `mag` permiten fabricar revisiones controladas en tests."""
    return EventMessage(
        event_id=DEMO_EVENT_ID,
        source=DEMO_SOURCE,
        mode=IngestionMode.DEMO,
        ingested_at=ingested_at or datetime.now(timezone.utc),
        updated_ms=updated_ms,
        payload={
            "type": "Feature",
            "id": DEMO_EVENT_ID,
            "geometry": {"type": "Point", "coordinates": [-3.7, 40.4, 12]},
            "properties": {
                "type": "earthquake",
                "mag": mag,
                "magType": "ml",
                "place": "Evento de prueba sintético",
                "time": DEMO_TIME_MS,
                "updated": updated_ms,
            },
        },
        synthetic_flag=True,
    )


async def publish(sender: KafkaSender, topic: str, message: EventMessage) -> None:
    """Publica y espera el ack. Lanza si Kafka no confirma."""
    await sender.send_and_wait(
        topic,
        value=message.to_json().encode("utf-8"),
        key=message.event_id.encode("utf-8"),
    )
    log.info("published %s updated=%d mode=%s topic=%s", message.event_id, message.updated_ms, message.mode.value, topic)


async def run_demo(sender: KafkaSender, topic: str, duplicates: int) -> int:
    """Publica la versión demo y `duplicates` reenvíos idénticos (misma versión). Devuelve nº de mensajes."""
    message = build_demo_message()
    total = 1 + duplicates
    for _ in range(total):
        await publish(sender, topic, message)
    return total


async def _start_producer(bootstrap: str):
    from aiokafka import AIOKafkaProducer

    async def connect() -> AIOKafkaProducer:
        producer = AIOKafkaProducer(bootstrap_servers=bootstrap, acks="all", enable_idempotence=True)
        try:
            await producer.start()
        except Exception:
            await producer.stop()
            raise
        return producer

    return await retry_async(connect, maximum=15.0, description="kafka connection")


MODES = ("demo", "live", "replay")


async def main(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    configure_logging("producer")
    mode = get_str("PRODUCER_MODE", "demo", env)
    if mode not in MODES:
        log.error("PRODUCER_MODE=%s no es válido; valores admitidos: %s", mode, ", ".join(MODES))
        return 2
    bootstrap = get_str("KAFKA_BOOTSTRAP_SERVERS", env=env)

    # Importaciones perezosas: demo no necesita httpx/psycopg y los tests unitarios del host tampoco.
    from backend.producer.live import install_stop_handlers

    stop = asyncio.Event()
    install_stop_handlers(stop)
    heartbeat = asyncio.create_task(heartbeat_loop())
    producer = await _start_producer(bootstrap)
    db = None
    exit_code = 0
    try:
        if mode == "demo":
            sent = await run_demo(
                producer, get_str("KAFKA_TOPIC_DEMO", "sismos.demo", env), get_int("DEMO_DUPLICATES", 0, minimum=0, env=env)
            )
            log.info("demo completa: %d mensaje(s) confirmados por Kafka; en reposo", sent)
            await stop.wait()  # en reposo: un proceso que termina sería relanzado por `restart: unless-stopped`
        elif mode == "live":
            from backend.db.connection import Database
            from backend.producer.live import run_live

            db = Database(database_url(env), hint="producer cycle waits for the database")
            log.info("modo live: consultando USGS cada %s s", get_int("POLL_SECONDS", 60, minimum=10, env=env))
            await run_live(producer, env, db, stop)
        else:
            from backend.producer.replay import run_replay

            exit_code = await run_replay(producer, env, stop)
            if exit_code == 0:
                log.info("replay completo; en reposo")
                await stop.wait()
    finally:
        heartbeat.cancel()
        if db is not None:
            await db.close()
        await producer.stop()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
