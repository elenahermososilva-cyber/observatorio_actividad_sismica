"""Base simulada para tests de contrato (no requiere PostgreSQL)."""

from backend.api.errors import DatabaseUnavailable
from backend.api.geojson import build_feature
from backend.api.queries import EventsPage, HealthInfo
from backend.producer.producer import build_demo_message


def demo_feature() -> dict:
    return build_feature("demo-evt-001", build_demo_message().payload)


class FakeQueries:
    def __init__(self, features: list[dict] | None = None, last_ingestion: int | None = 1_793_110_100_000) -> None:
        self.features = [demo_feature()] if features is None else features
        self.last_ingestion = last_ingestion
        self.calls: list[tuple] = []

    async def fetch_events(self, start_ms, end_ms, limit, mode) -> EventsPage:
        self.calls.append((start_ms, end_ms, limit, mode))
        selected = [
            f
            for f in self.features
            if (start_ms is None or f["properties"]["time"] >= start_ms)
            and (end_ms is None or f["properties"]["time"] < end_ms)
        ]
        shown = selected[:limit]
        return EventsPage(shown, len(selected), len(selected) > limit, self.last_ingestion, mode)

    async def fetch_health(self, mode) -> HealthInfo:
        return HealthInfo(self.last_ingestion)

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FailingQueries(FakeQueries):
    async def fetch_events(self, start_ms, end_ms, limit, mode) -> EventsPage:
        raise DatabaseUnavailable("The database query failed")

    async def fetch_health(self, mode) -> HealthInfo:
        raise DatabaseUnavailable("The database is not reachable")


class BrokenQueries(FakeQueries):
    async def fetch_events(self, start_ms, end_ms, limit, mode) -> EventsPage:
        raise RuntimeError("secret internal detail: password=hunter2")
