"""Contrato de GET /api/eventos y GET /api/salud (CONTRATO-API.md). Requiere fastapi+httpx (contenedor)."""

import json
import math
import unittest

try:
    from fastapi.testclient import TestClient

    from backend.api.app import create_app
except ImportError:  # host sin dependencias del backend
    TestClient = None

from tests.contract.fakes import FakeQueries, demo_feature

# 2026-10-27T14:00:00Z, instante del evento demo
EVENT_TIME = 1_793_109_600_000
HOUR = 3_600_000


def iso(ms: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def contains_non_finite(value) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(contains_non_finite(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_non_finite(v) for v in value)
    return False


@unittest.skipIf(TestClient is None, "fastapi no disponible")
class EventosContractTests(unittest.TestCase):
    def client(self, queries=None, now=EVENT_TIME + HOUR, max_features=None, default_mode="demo"):
        app = create_app(
            queries or FakeQueries(), clock=lambda: now, max_features=max_features, default_mode=default_mode
        )
        return TestClient(app)

    def test_returns_feature_collection_with_required_metadata(self) -> None:
        with self.client() as client:
            response = client.get("/api/eventos")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))
        body = response.json()
        self.assertEqual(body["type"], "FeatureCollection")
        for key in ("generated", "last_ingestion", "mode", "count", "truncated"):
            self.assertIn(key, body["metadata"])
        self.assertEqual(body["metadata"]["generated"], EVENT_TIME + HOUR)
        self.assertEqual(body["metadata"]["count"], len(body["features"]))
        self.assertIs(body["metadata"]["truncated"], False)

    def test_demo_event_appears_exactly_once_with_contract_shape(self) -> None:
        with self.client() as client:
            body = client.get("/api/eventos").json()
        ids = [f["id"] for f in body["features"]]
        self.assertEqual(ids, ["demo-evt-001"])
        feature = body["features"][0]
        self.assertEqual(feature["type"], "Feature")
        self.assertEqual(feature["geometry"]["type"], "Point")
        self.assertEqual(feature["geometry"]["coordinates"], [-3.7, 40.4, 12])
        for key in ("mag", "magType", "place", "time", "updated", "country_id", "country_name"):
            self.assertIn(key, feature["properties"])

    def test_default_window_is_last_24_hours(self) -> None:
        queries = FakeQueries()
        with self.client(queries, now=EVENT_TIME + 25 * HOUR) as client:
            body = client.get("/api/eventos").json()
        self.assertEqual(queries.calls[0][0].start_ms, EVENT_TIME + 25 * HOUR - 24 * HOUR)
        self.assertEqual(body["features"], [])  # evento de hace 25 h: fuera de la ventana por defecto
        self.assertEqual(body["metadata"]["count"], 0)

    def test_start_inclusive_and_end_exclusive(self) -> None:
        with self.client(now=EVENT_TIME + 100 * HOUR) as client:
            inclusive = client.get("/api/eventos", params={"start": iso(EVENT_TIME)}).json()
            excluded_by_end = client.get(
                "/api/eventos", params={"start": iso(EVENT_TIME - HOUR), "end": iso(EVENT_TIME)}
            ).json()
            included_by_end = client.get(
                "/api/eventos", params={"start": iso(EVENT_TIME - HOUR), "end": iso(EVENT_TIME + 1000)}
            ).json()
        self.assertEqual(inclusive["metadata"]["count"], 1)  # start == time → incluido
        self.assertEqual(excluded_by_end["metadata"]["count"], 0)  # end == time → excluido
        self.assertEqual(included_by_end["metadata"]["count"], 1)

    def test_naive_datetime_is_interpreted_as_utc(self) -> None:
        queries = FakeQueries()
        with self.client(queries) as client:
            client.get("/api/eventos", params={"start": "2026-10-27T14:00:00"})
        self.assertEqual(queries.calls[0][0].start_ms, EVENT_TIME)

    def test_empty_result_is_200_with_empty_features(self) -> None:
        with self.client(FakeQueries(features=[])) as client:
            response = client.get("/api/eventos", params={"start": "2020-01-01"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["features"], [])

    def test_null_values_are_null_not_nan(self) -> None:
        feature = demo_feature()
        feature["properties"]["mag"] = None
        feature["geometry"]["coordinates"][2] = None
        with self.client(FakeQueries([feature])) as client:
            response = client.get("/api/eventos", params={"start": "2020-01-01"})
        self.assertNotIn("NaN", response.text)
        self.assertNotIn("Infinity", response.text)
        body = json.loads(response.text, parse_constant=lambda c: self.fail(f"non-finite constant {c}"))
        self.assertFalse(contains_non_finite(body))
        self.assertIsNone(body["features"][0]["properties"]["mag"])

    def test_truncation_is_reported_with_total(self) -> None:
        features = []
        for index in range(3):
            feature = demo_feature()
            feature["id"] = f"evt-{index}"
            features.append(feature)
        with self.client(FakeQueries(features), max_features=2) as client:
            body = client.get("/api/eventos", params={"start": "2020-01-01"}).json()
        self.assertTrue(body["metadata"]["truncated"])
        self.assertEqual(body["metadata"]["count"], 2)
        self.assertEqual(body["metadata"]["total"], 3)

    def test_mode_defaults_to_configured_value_and_is_echoed_in_metadata(self) -> None:
        queries = FakeQueries()
        with self.client(queries, default_mode="live") as client:
            body = client.get("/api/eventos", params={"start": "2020-01-01"}).json()
        self.assertEqual(queries.calls[0][3], "live")
        self.assertEqual(body["metadata"]["mode"], "live")

    def test_explicit_mode_overrides_default(self) -> None:
        queries = FakeQueries()
        with self.client(queries, default_mode="live") as client:
            for mode in ("demo", "live", "replay"):
                body = client.get("/api/eventos", params={"start": "2020-01-01", "mode": mode}).json()
                self.assertEqual(body["metadata"]["mode"], mode)
        self.assertEqual([c[3] for c in queries.calls], ["demo", "live", "replay"])

    def test_last_ingestion_can_be_null(self) -> None:
        with self.client(FakeQueries(last_ingestion=None)) as client:
            body = client.get("/api/eventos", params={"start": "2020-01-01"}).json()
        self.assertIsNone(body["metadata"]["last_ingestion"])


@unittest.skipIf(TestClient is None, "fastapi no disponible")
class SaludContractTests(unittest.TestCase):
    def test_health_ok_reports_last_ingestion(self) -> None:
        app = create_app(FakeQueries(last_ingestion=1_793_110_100_000), clock=lambda: 5)
        with TestClient(app) as client:
            response = client.get("/api/salud")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["database"], "ok")
        self.assertEqual(body["last_ingestion"], 1_793_110_100_000)
        self.assertEqual(body["generated"], 5)

    def test_health_exposes_no_credentials_or_urls(self) -> None:
        with TestClient(create_app(FakeQueries())) as client:
            text = client.get("/api/salud").text.lower()
        for forbidden in ("password", "postgresql://", "secret", "token"):
            self.assertNotIn(forbidden, text)

    def test_no_documentation_or_admin_routes_are_exposed(self) -> None:
        with TestClient(create_app(FakeQueries())) as client:
            for path in ("/docs", "/redoc", "/openapi.json"):
                self.assertEqual(client.get(path).status_code, 404, path)


if __name__ == "__main__":
    unittest.main()
