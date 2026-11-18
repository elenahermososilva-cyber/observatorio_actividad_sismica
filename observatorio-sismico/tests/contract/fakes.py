"""Base simulada para tests de contrato (no requiere PostgreSQL).

Reproduce en Python la semántica de filtrado de la API para poder probar el CONTRATO HTTP sin base de datos.
La corrección del SQL real (índices, nulos, instantánea) se prueba en tests/integration/test_api_db.py.
"""

from backend.api.exceptions import DatabaseUnavailable, InvalidParameter
from backend.api.geojson import build_feature
from backend.api.params import NO_COUNTRY, EventFilters
from backend.api.queries import EventsPage, HealthInfo
from backend.api.stats import BaselineData, GroupRow, StatsData
from backend.producer.producer import build_demo_message

KNOWN_COUNTRIES = {"ESP", "FRA", "USA", "CHL"}


def demo_feature() -> dict:
    return build_feature("demo-evt-001", build_demo_message().payload)


def feature(event_id: str, time_ms: int, mag: float | None = 4.0, country_id: str | None = None, **props) -> dict:
    base = demo_feature()
    base["id"] = event_id
    base["properties"].update({"time": time_ms, "mag": mag, "country_id": country_id, **props})
    return base


def default_stats() -> StatsData:
    hour = 1_793_109_600_000  # 2026-10-27T14:00Z
    return StatsData(
        last_ingestion=hour + 1000, total=5, missing_mag=1, missing_depth=2,
        hourly={hour: 3, hour + 3_600_000: 2},
        group_rows=[
            GroupRow(hour, "assigned", "ESP", "España", "Southern Europe", 2),
            GroupRow(hour, "unassigned", None, None, None, 1),
            GroupRow(hour + 3_600_000, "assigned", "FRA", "Francia", "Western Europe", 2),
        ],
        mag_bins={8: 3, 9: 1}, depth_bins={0: 2, 1: 1},
        window_count=4, window_null_mag_excluded=1,
        baseline=BaselineData(2025, year_events_total=18_302, events=18_302, days_with_events=365, null_mag_excluded=0),
    )


class FakeQueries:
    def __init__(self, features: list[dict] | None = None, last_ingestion: int | None = 1_793_110_100_000,
                 stats: StatsData | None = None) -> None:
        self.features = [demo_feature()] if features is None else features
        self.last_ingestion = last_ingestion
        self.stats = stats or default_stats()
        self.calls: list[tuple] = []
        self.stat_calls: list[tuple] = []
        self.health_calls: list[str] = []

    def _check_country(self, filters: EventFilters) -> None:
        if filters.country_id not in (None, NO_COUNTRY) and filters.country_id not in KNOWN_COUNTRIES:
            raise InvalidParameter(f"unknown country_id {filters.country_id!r}")

    @staticmethod
    def _matches(f: dict, filters: EventFilters, *, use_min_mag: bool = True) -> bool:
        p = f["properties"]
        if p["time"] < filters.start_ms or (filters.end_ms is not None and p["time"] >= filters.end_ms):
            return False
        if use_min_mag and filters.min_mag is not None and (p["mag"] is None or p["mag"] < filters.min_mag):
            return False
        if filters.country_id == NO_COUNTRY:
            return p["country_id"] is None
        return filters.country_id is None or p["country_id"] == filters.country_id

    async def fetch_events(self, filters, limit, offset, mode) -> EventsPage:
        self.calls.append((filters, limit, offset, mode))
        self._check_country(filters)
        selected = [f for f in self.features if self._matches(f, filters)]
        selected.sort(key=lambda f: (-f["properties"]["time"], f["id"]))
        page = selected[offset: offset + limit]
        null_count = sum(f["properties"]["mag"] is None for f in selected)
        excluded = 0
        if filters.min_mag is not None:
            excluded = sum(
                f["properties"]["mag"] is None for f in self.features if self._matches(f, filters, use_min_mag=False)
            )
        return EventsPage(
            page, len(selected), offset + len(page) < len(selected), self.last_ingestion, mode, limit, offset,
            null_count, excluded,
        )

    async def fetch_statistics(self, filters, mode, generated_ms, group_by, baseline_year) -> StatsData:
        self.stat_calls.append((filters, mode, generated_ms, group_by, baseline_year))
        self._check_country(filters)
        return self.stats

    async def fetch_health(self, mode) -> HealthInfo:
        self.health_calls.append(mode)
        return HealthInfo(self.last_ingestion)

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FailingQueries(FakeQueries):
    async def fetch_events(self, filters, limit, offset, mode) -> EventsPage:
        raise DatabaseUnavailable("The database query failed")

    async def fetch_statistics(self, filters, mode, generated_ms, group_by, baseline_year) -> StatsData:
        raise DatabaseUnavailable("The database query failed")

    async def fetch_health(self, mode) -> HealthInfo:
        raise DatabaseUnavailable("The database is not reachable")


class BrokenQueries(FakeQueries):
    async def fetch_events(self, filters, limit, offset, mode) -> EventsPage:
        raise RuntimeError("secret internal detail: password=hunter2")

    async def fetch_statistics(self, filters, mode, generated_ms, group_by, baseline_year) -> StatsData:
        raise RuntimeError("secret internal detail: password=hunter2")
