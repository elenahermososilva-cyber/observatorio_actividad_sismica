"""Contrato de errores: "sin resultados" ≠ "fallo del servicio" (FR-007, FR-008, SC-004)."""

import unittest

try:
    from fastapi.testclient import TestClient

    from backend.api.app import create_app
except ImportError:
    TestClient = None

from tests.contract.fakes import BrokenQueries, FailingQueries, FakeQueries


def assert_error_body(test: unittest.TestCase, response, status: int, code: str) -> None:
    test.assertEqual(response.status_code, status)
    test.assertTrue(response.headers["content-type"].startswith("application/json"))
    body = response.json()
    test.assertEqual(body["error"]["code"], code)
    test.assertTrue(body["error"]["message"])
    test.assertNotIn("features", body)  # jamás una colección, ni siquiera vacía
    test.assertNotEqual(body.get("type"), "FeatureCollection")


@unittest.skipIf(TestClient is None, "fastapi no disponible")
class ApiErrorContractTests(unittest.TestCase):
    def test_database_failure_is_503_not_empty_collection(self) -> None:
        with TestClient(create_app(FailingQueries())) as client:
            response = client.get("/api/eventos", params={"start": "2020-01-01"})
        assert_error_body(self, response, 503, "database_unavailable")

    def test_empty_success_differs_from_failure(self) -> None:
        with TestClient(create_app(FakeQueries(features=[]))) as client:
            empty = client.get("/api/eventos", params={"start": "2020-01-01"})
        with TestClient(create_app(FailingQueries())) as client:
            failed = client.get("/api/eventos", params={"start": "2020-01-01"})
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["features"], [])
        self.assertNotEqual(failed.status_code, 200)

    def test_health_reports_database_failure_explicitly(self) -> None:
        with TestClient(create_app(FailingQueries())) as client:
            response = client.get("/api/salud")
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["database"], "unavailable")
        self.assertEqual(body["error"]["code"], "database_unavailable")

    def test_api_does_not_claim_knowledge_about_the_consumer(self) -> None:
        with TestClient(create_app(FailingQueries())) as client:
            text = (client.get("/api/salud").text + client.get("/api/eventos").text).lower()
        self.assertNotIn("consumer", text)
        self.assertNotIn("consumidor", text)

    def test_invalid_dates_are_400(self) -> None:
        with TestClient(create_app(FakeQueries())) as client:
            for params in ({"start": "ayer"}, {"end": "2026-13-45"}, {"start": "not-a-date", "end": "2026-01-01"}):
                assert_error_body(self, client.get("/api/eventos", params=params), 400, "invalid_parameter")

    def test_start_not_before_end_is_400(self) -> None:
        with TestClient(create_app(FakeQueries())) as client:
            response = client.get("/api/eventos", params={"start": "2026-01-02", "end": "2026-01-01"})
            equal = client.get("/api/eventos", params={"start": "2026-01-01", "end": "2026-01-01"})
        assert_error_body(self, response, 400, "invalid_parameter")
        assert_error_body(self, equal, 400, "invalid_parameter")

    def test_invalid_mode_is_400_and_does_not_query_the_database(self) -> None:
        queries = FakeQueries()
        with TestClient(create_app(queries, default_mode="demo")) as client:
            for bad in ("historico", "public", "DEMO", "demo;drop"):
                response = client.get("/api/eventos", params={"mode": bad, "start": "2020-01-01"})
                assert_error_body(self, response, 400, "invalid_parameter")
        self.assertEqual(queries.calls, [])

    def test_invalid_default_mode_in_configuration_fails_at_startup(self) -> None:
        with self.assertRaises(ValueError):
            with TestClient(create_app(FakeQueries(), default_mode="historico")):
                pass

    def test_unexpected_error_is_500_without_internal_details(self) -> None:
        with TestClient(create_app(BrokenQueries()), raise_server_exceptions=False) as client:
            response = client.get("/api/eventos", params={"start": "2020-01-01"})
        assert_error_body(self, response, 500, "internal_error")
        self.assertNotIn("hunter2", response.text)
        self.assertNotIn("secret", response.text)


if __name__ == "__main__":
    unittest.main()
