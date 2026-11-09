import asyncio
import logging
import os
from typing import Protocol

import psycopg
from aiokafka import AIOKafkaConsumer
from pydantic import ValidationError

from db.repository import PostgresRepository
from producer.schema import EventMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EventPersister(Protocol):
    def persist_event(self, event: EventMessage) -> bool: ...


class OffsetCommitter(Protocol):
    async def commit(self) -> None: ...


async def process_message(
    raw_message: bytes,
    repository: EventPersister,
    consumer: OffsetCommitter,
) -> None:
    try:
        event = EventMessage.model_validate_json(raw_message)
    except (ValidationError, ValueError):
        logger.exception("Rejected malformed Kafka message; offset remains uncommitted")
        raise

    try:
        await asyncio.to_thread(repository.persist_event, event)
    except psycopg.Error:
        logger.exception(
            "Could not persist event %s; offset remains uncommitted",
            event.event_id,
        )
        raise

    await consumer.commit()
    logger.info("Persisted event %s and committed its Kafka offset", event.event_id)


async def run() -> None:
    consumer = AIOKafkaConsumer(
        os.environ["KAFKA_TOPIC"],
        bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"],
        group_id=os.environ["KAFKA_GROUP_ID"],
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    repository = PostgresRepository(os.environ["DATABASE_URL"])
    await consumer.start()
    try:
        async for record in consumer:
            await process_message(record.value, repository, consumer)
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(run())
