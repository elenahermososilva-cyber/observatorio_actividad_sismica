import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from aiokafka import AIOKafkaProducer

from consumer.consumer import process_message
from db.repository import PostgresRepository
from producer.producer import build_synthetic_event


class RecordingRepository:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def persist_event(self, event: Any) -> bool:
        self.actions.append(f"persist:{event.event_id}")
        return True


class RecordingConsumer:
    def __init__(self, actions: list[str]) -> None:
        self.actions = actions

    async def commit(self) -> None:
        self.actions.append("commit")


def test_consumer_commits_only_after_persistence_returns() -> None:
    repository = RecordingRepository()
    consumer = RecordingConsumer(repository.actions)
    event = build_synthetic_event(datetime.now(timezone.utc))

    asyncio.run(
        process_message(
            event.model_dump_json().encode("utf-8"),
            repository,
            consumer,
        )
    )

    assert repository.actions == ["persist:demo-evt-001", "commit"]


def test_repository_commits_version_and_current_state_in_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions: list[str] = []

    class FakeCursor:
        rowcount = 1

        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(self, query: str, _params: tuple[Any, ...]) -> None:
            if "INSERT INTO event_message" in query:
                actions.append("version")
            elif "INSERT INTO event_current" in query:
                assert "WHERE event_current.current_version_ms < EXCLUDED.current_version_ms" in query
                actions.append("current")

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, exc_type: object, *_: object) -> None:
            actions.append("commit" if exc_type is None else "rollback")

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    monkeypatch.setattr(
        "db.repository.psycopg.connect",
        lambda *_args, **_kwargs: FakeConnection(),
    )
    repository = PostgresRepository("postgresql://test")

    changed = repository.persist_event(build_synthetic_event())

    assert changed is True
    assert actions == ["version", "current", "commit"]


@pytest.mark.skipif(
    os.getenv("RUN_DOCKER_INTEGRATION") != "1",
    reason="requiere los cinco servicios levantados con Docker Compose",
)
def test_publishing_same_event_twice_produces_one_api_feature() -> None:
    async def publish_twice(message: dict[str, Any]) -> None:
        producer = AIOKafkaProducer(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            key_serializer=lambda key: key.encode("utf-8"),
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        )
        await producer.start()
        try:
            for _ in range(2):
                await producer.send_and_wait(
                    os.getenv("KAFKA_TOPIC", "earthquakes"),
                    message,
                    key=message["event_id"],
                )
        finally:
            await producer.stop()

    event = build_synthetic_event()
    asyncio.run(publish_twice(event.model_dump(mode="json")))

    deadline = time.monotonic() + 60
    with httpx.Client(timeout=5) as client:
        while time.monotonic() < deadline:
            response = client.get(os.getenv("API_BASE_URL", "http://localhost:8000") + "/api/eventos")
            assert response.status_code == 200, response.text
            matches = [
                feature
                for feature in response.json()["features"]
                if feature["id"] == event.event_id
            ]
            if matches:
                assert len(matches) == 1
                return
            time.sleep(1)

    raise AssertionError(f"El evento {event.event_id} no apareció en la API")
