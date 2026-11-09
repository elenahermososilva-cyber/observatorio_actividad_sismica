import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from aiokafka import AIOKafkaProducer

from producer.schema import EventMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_synthetic_event(now: datetime | None = None) -> EventMessage:
    occurred_at = now or datetime.now(timezone.utc)
    if occurred_at.utcoffset() != timedelta(0):
        raise ValueError("the demo timestamp must use UTC")
    occurred_at = occurred_at.replace(microsecond=(occurred_at.microsecond // 1000) * 1000)
    updated_ms = int(occurred_at.timestamp() * 1000)
    event_time_ms = updated_ms - 60_000

    feature = {
        "type": "Feature",
        "id": "demo-evt-001",
        "geometry": {"type": "Point", "coordinates": [-20.0, 0.0, 12.0]},
        "properties": {
            "mag": 3.2,
            "magType": "ml",
            "place": "Evento de prueba sintético",
            "time": event_time_ms,
            "updated": updated_ms,
            "country_id": None,
            "country_name": None,
        },
    }
    return EventMessage(
        event_id="demo-evt-001",
        source="synthetic-demo",
        mode="demo",
        time=event_time_ms,
        updated=updated_ms,
        ingested_at=occurred_at,
        replayed_at=None,
        payload=feature,
        synthetic_flag=True,
    )


async def run() -> None:
    bootstrap_servers = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
    topic = os.environ["KAFKA_TOPIC"]
    interval_seconds = float(os.environ["DEMO_PUBLISH_INTERVAL_SECONDS"])
    if interval_seconds <= 0:
        raise ValueError("DEMO_PUBLISH_INTERVAL_SECONDS must be positive")

    event = build_synthetic_event()
    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        key_serializer=lambda key: key.encode("utf-8"),
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )
    await producer.start()
    try:
        while True:
            await producer.send_and_wait(topic, event.model_dump(mode="json"), key=event.event_id)
            logger.info("Published synthetic demo event %s", event.event_id)
            await asyncio.sleep(interval_seconds)
    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(run())
