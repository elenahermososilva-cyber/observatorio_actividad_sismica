import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI

from api.app import create_app
from producer.producer import build_synthetic_event


class FakeRepository:
    def __init__(self, rows: list[dict[str, Any]], last_ingestion: datetime | None) -> None:
        self.rows = rows
        self.last_ingestion = last_ingestion

    def get_current_events(
        self, since_ms: int
    ) -> tuple[list[dict[str, Any]], datetime | None]:
        return self.rows, self.last_ingestion

    def check_connection(self) -> None:
        return None


def _row_for_demo_event() -> tuple[dict[str, Any], datetime]:
    event = build_synthetic_event(datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc))
    return (
        {
            "event_id": event.event_id,
            "payload": event.model_dump(mode="json"),
            "source_time_ms": event.time,
            "source_updated_ms": event.updated,
        },
        event.ingested_at,
    )


async def _get_events(app: FastAPI) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.get("/api/eventos")


def test_returns_geojson_feature_collection_with_one_synthetic_event() -> None:
    row, last_ingestion = _row_for_demo_event()

    response = asyncio.run(_get_events(create_app(FakeRepository([row], last_ingestion))))

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert body["metadata"]["count"] == 1
    assert body["metadata"]["mode"] == "demo"
    assert body["metadata"]["truncated"] is False
    assert isinstance(body["metadata"]["generated"], int)
    assert body["metadata"]["last_ingestion"] == int(last_ingestion.timestamp() * 1000)
    assert len(body["features"]) == 1
    feature = body["features"][0]
    assert feature["id"] == "demo-evt-001"
    assert feature["properties"]["source"] == "synthetic-demo"
    assert feature["properties"]["synthetic_flag"] is True
    assert feature["properties"]["time"] == row["source_time_ms"]
    assert feature["properties"]["updated"] == row["source_updated_ms"]
    assert feature["properties"]["country_id"] is None
    assert feature["properties"]["country_name"] is None


def test_successful_query_without_events_returns_empty_collection() -> None:
    response = asyncio.run(_get_events(create_app(FakeRepository([], None))))

    assert response.status_code == 200
    assert response.json()["features"] == []
    assert response.json()["metadata"]["count"] == 0
