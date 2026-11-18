"""Contrato HTTP de la Fase 9: filtros, paginación, estadísticas, CORS y salud. Base simulada; requiere fastapi (contenedor)."""

import json
import os
import unittest
from unittest import mock

try:
    from fastapi.testclient import TestClient

    from backend.api.app import create_app
    from backend.api.cors import CorsConfigError
except ImportError:  # host sin dependencias del backend
    TestClient = None

from tests.contract.fakes import BrokenQueries, FailingQueries, FakeQueries, feature

H = 3_600_000
T0 = 1_793_109_600_000  # 2026-10-27T14:00:00Z
NOW = T0 + 2 * H
START = "2026-10-27T00:00:00Z"
LOCAL = "http://localhost:4200"
NETLIFY = "https://mi-sitio.netlify.app"


def events() -> list[dict]:
    """Cinco eventos con reparto conocido: magnitudes 6, 5, 4, 3 y NULL; tres en España, uno en Francia, uno en el mar."""
    return [
        feature("e1", T0 + 4 * 60_000, mag=6.0, country_id="ESP"),
        feature("e2", T0 + 3 * 60_000, mag=5.0, country_id="ESP"),
        feature("e3", T0 + 2 * 60_000, mag=4.0, country_id="FRA"),
        feature("e4", T0 + 1 * 60_000, mag=3.0, country_id=None),
        feature("e5", T0, mag=None, country_id="ESP"),
    ]


def make(queries=None, **kw) -> "TestClient":
    kw.setdefault("clock", lambda: NOW)
    kw.setdefault("default_mode", "demo")
    kw.setdefault("cors_origins", [LOCAL])
    return TestClient(create_app(queries or FakeQueries(events()), **kw))


def ids(body) -> list[str]:
    return [f["id"] for f in body["features"]]


@unittest.skipIf(TestClient is None, "fastapi no disponible")
class MinMagTests(unittest.TestCase):
    def get(self, **params):
        with make() as client:
            return client.get("/api/eventos", params={"start": START, **params}).json()

    def test_null_magnitude_never_satisfies_min_mag_and_is_counted_separately(self) -> None:
        body = self.get(min_mag="4")
        self.assertEqual(ids(body), ["e1", "e2", "e3"])  # e4 (3.0) y e5 (nula) fuera
        self.assertNotIn(None, [f["properties"]["mag"] for f in body["features"]])
        self.assertEqual(body["metadata"]["null_mag_excluded"], 1)  # e5 existía pero no puede cumplirlo
        self.assertEqual(body["metadata"]["null_mag_count"], 0)  # ninguna nula DENTRO del resultado
        self.assertEqual(body["metadata"]["filters"], {"min_mag": 4.0, "country_id": None})

    def test_without_min_mag_null_magnitudes_are_returned_as_null_and_counted(self) -> None:
        body = self.get()
        self.assertEqual(len(body["features"]), 5)
        self.assertIsNone(next(f for f in body["features"] if f["id"] == "e5")["properties"]["mag"])
        self.assertEqual((body["metadata"]["null_mag_count"], body["metadata"]["null_mag_excluded"]), (1, 0))

    def test_zero_is_a_real_threshold_not_no_filter(self) -> None:
        body = self.get(min_mag="0")
        self.assertEqual(len(body["features"]), 4)  # todas salvo la nula
        self.assertEqual(body["metadata"]["null_mag_excluded"], 1)

    def test_boundary_is_inclusive(self) -> None:
        self.assertEqual(ids(self.get(min_mag="5")), ["e1", "e2"])
        self.assertEqual(ids(self.get(min_mag="5.01")), ["e1"])

    def test_threshold_above_everything_is_an_empty_success_not_an_error(self) -> None:
        body = self.get(min_mag="9")
        self.assertEqual((body["features"], body["metadata"]["total"]), ([], 0))
        self.assertEqual(body["metadata"]["null_mag_excluded"], 1)

    def test_invalid_values_are_400_and_never_query(self) -> None:
        queries = FakeQueries(events())
        with make(queries) as client:
            for bad in ("nan", "inf", "abc", "99", "4,5"):
                response = client.get("/api/eventos", params={"min_mag": bad})
                self.assertEqual(response.status_code, 400, bad)
                self.assertEqual(response.json()["error"]["code"], "invalid_parameter")
        self.assertEqual(queries.calls, [])


@unittest.skipIf(TestClient is None, "fastapi no disponible")
class CountryFilterTests(unittest.TestCase):
    def get(self, **params):
        with make() as client:
            response = client.get("/api/eventos", params={"start": START, **params})
        return response

    def test_filters_by_country_case_insensitively(self) -> None:
        for value in ("ESP", "esp", " Esp "):
            self.assertEqual(ids(self.get(country_id=value).json()), ["e1", "e2", "e5"], value)
        self.assertEqual(ids(self.get(country_id="FRA").json()), ["e3"])

    def test_none_selects_events_without_a_country(self) -> None:
        body = self.get(country_id="none").json()
        self.assertEqual(ids(body), ["e4"])
        self.assertEqual(body["metadata"]["filters"]["country_id"], "none")
        self.assertEqual(body["features"][0]["properties"]["country_id"], None)

    def test_unknown_country_is_400_not_a_silent_empty_result(self) -> None:
        response = self.get(country_id="ZZZ")
        self.assertEqual(response.status_code, 400)
        self.assertIn("ZZZ", response.json()["error"]["message"])

    def test_malformed_country_is_400(self) -> None:
        for bad in ("españa", "E", "ES'; DROP", "TOOLONGCODE"):
            self.assertEqual(self.get(country_id=bad).status_code, 400, bad)

    def test_country_and_magnitude_combine(self) -> None:
        body = self.get(country_id="ESP", min_mag="5").json()
        self.assertEqual(ids(body), ["e1", "e2"])
        self.assertEqual(body["metadata"]["null_mag_excluded"], 1)  # e5 es de España y de magnitud nula


@unittest.skipIf(TestClient is None, "fastapi no disponible")
class PaginationTests(unittest.TestCase):
    def page(self, **params):
        with make() as client:
            return client.get("/api/eventos", params={"start": START, **params}).json()

    def test_pages_cover_everything_once_in_stable_order(self) -> None:
        seen, offset, pages = [], 0, 0
        while offset is not None:
            body = self.page(limit=2, offset=offset)
            seen.extend(ids(body))
            self.assertEqual(body["metadata"]["total"], 5)
            self.assertEqual(body["metadata"]["limit"], 2)
            offset, pages = body["metadata"]["next_offset"], pages + 1
        self.assertEqual(seen, ["e1", "e2", "e3", "e4", "e5"])  # más recientes primero, sin repetidos ni huecos
        self.assertEqual(pages, 3)

    def test_truncated_flag_and_next_offset(self) -> None:
        first = self.page(limit=2)["metadata"]
        self.assertEqual((first["count"], first["truncated"], first["next_offset"], first["offset"]), (2, True, 2, 0))
        last = self.page(limit=2, offset=4)["metadata"]
        self.assertEqual((last["count"], last["truncated"], last["next_offset"]), (1, False, None))

    def test_exact_fit_is_not_truncated(self) -> None:
        meta = self.page(limit=5)["metadata"]
        self.assertEqual((meta["count"], meta["truncated"], meta["next_offset"]), (5, False, None))

    def test_offset_past_the_end_is_an_empty_success(self) -> None:
        body = self.page(offset=99)
        self.assertEqual((body["features"], body["metadata"]["truncated"], body["metadata"]["total"]), ([], False, 5))

    def test_default_page_size_is_the_documented_maximum(self) -> None:
        with make(max_features=3) as client:
            body = client.get("/api/eventos", params={"start": START}).json()
        self.assertEqual((body["metadata"]["count"], body["metadata"]["limit"], body["metadata"]["truncated"]), (3, 3, True))
        self.assertEqual(body["metadata"]["total"], 5)  # el total completo se informa siempre

    def test_limit_above_the_maximum_is_rejected_not_clamped(self) -> None:
        with make(max_features=3) as client:
            self.assertEqual(client.get("/api/eventos", params={"limit": 4}).status_code, 400)

    def test_invalid_paging_values(self) -> None:
        with make() as client:
            for params in ({"limit": 0}, {"limit": -1}, {"limit": "x"}, {"offset": -1}, {"offset": "x"}, {"limit": 1.5}):
                self.assertEqual(client.get("/api/eventos", params=params).status_code, 400, params)

    def test_pagination_respects_filters(self) -> None:
        body = self.page(limit=1, country_id="ESP")
        self.assertEqual((ids(body), body["metadata"]["total"], body["metadata"]["next_offset"]), (["e1"], 3, 1))


@unittest.skipIf(TestClient is None, "fastapi no disponible")
class StatisticsContractTests(unittest.TestCase):
    def test_returns_all_sections(self) -> None:
        with make() as client:
            response = client.get("/api/estadisticas", params={"start": START})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))
        body = response.json()
        self.assertEqual(set(body), {"metadata", "totals", "hourly", "groups", "distributions", "historical_comparison"})
        self.assertEqual(set(body["distributions"]), {"magnitude", "depth_km"})
        self.assertEqual(body["metadata"]["generated"], NOW)

    def test_statistics_receive_exactly_the_same_filters_as_the_map(self) -> None:
        """«Los filtros de estadísticas deben equivaler a los del mapa»: misma cadena de consulta ⇒ mismos filtros."""
        queries = FakeQueries(events())
        params = {"start": START, "end": "2026-10-28T00:00:00Z", "min_mag": "4", "country_id": "esp", "mode": "replay"}
        with make(queries) as client:
            client.get("/api/eventos", params=params)
            client.get("/api/estadisticas", params=params)
        self.assertEqual(queries.calls[0][0], queries.stat_calls[0][0])
        self.assertEqual((queries.calls[0][3], queries.stat_calls[0][1]), ("replay", "replay"))

    def test_default_window_matches_the_map_default(self) -> None:
        queries = FakeQueries(events())
        with make(queries) as client:
            client.get("/api/eventos")
            client.get("/api/estadisticas")
        self.assertEqual(queries.calls[0][0], queries.stat_calls[0][0])
        self.assertEqual(queries.stat_calls[0][0].start_ms, NOW - 24 * H)

    def test_group_and_baseline_year_parameters(self) -> None:
        queries = FakeQueries(events())
        with make(queries) as client:
            client.get("/api/estadisticas", params={"group": "subregion", "baseline_year": "2024"})
            client.get("/api/estadisticas")
        self.assertEqual((queries.stat_calls[0][3], queries.stat_calls[0][4]), ("subregion", 2024))
        self.assertEqual((queries.stat_calls[1][3], queries.stat_calls[1][4]), ("country", 2025))  # valores por defecto

    def test_invalid_parameters_are_400_without_querying(self) -> None:
        queries = FakeQueries(events())
        with make(queries) as client:
            for params in ({"group": "continent"}, {"baseline_year": "abc"}, {"baseline_year": "1500"},
                           {"min_mag": "nan"}, {"mode": "historico"}, {"start": "ayer"}, {"country_id": "ZZZ"}):
                response = client.get("/api/estadisticas", params=params)
                self.assertEqual(response.status_code, 400, params)
        self.assertEqual(queries.stat_calls[:-1], [])  # solo la de país desconocido llega a la capa de datos

    def test_hourly_series_zero_fills_and_counts_match(self) -> None:
        with make() as client:
            body = client.get("/api/estadisticas", params={"start": "2026-10-27T14:00:00Z", "end": "2026-10-27T17:00:00Z"}).json()
        series = body["hourly"]["series"]
        self.assertEqual([s["count"] for s in series], [3, 2, 0])  # la hora sin eventos aparece como 0
        self.assertTrue(body["hourly"]["zero_filled"])
        self.assertEqual(sum(s["count"] for s in series), body["totals"]["events"])

    def test_no_country_group_is_explicit(self) -> None:
        with make() as client:
            body = client.get("/api/estadisticas", params={"start": START}).json()
        totals = {t["name"]: t["count"] for t in body["groups"]["totals"]}
        self.assertEqual(totals["Sin país asignado"], 1)
        self.assertEqual(body["groups"]["no_country_label"], "Sin país asignado")

    def test_strict_json(self) -> None:
        with make() as client:
            text = client.get("/api/estadisticas").text
        json.loads(text, parse_constant=lambda c: self.fail(f"non-finite constant {c}"))

    def test_database_failure_is_503_not_zeros(self) -> None:
        with make(FailingQueries()) as client:
            response = client.get("/api/estadisticas")
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["error"]["code"], "database_unavailable")
        for section in ("totals", "hourly", "groups", "distributions", "historical_comparison"):
            self.assertNotIn(section, body)

    def test_unexpected_error_is_500_without_details(self) -> None:
        with TestClient(create_app(BrokenQueries(), clock=lambda: NOW, default_mode="demo", cors_origins=[LOCAL]),
                        raise_server_exceptions=False) as client:
            response = client.get("/api/estadisticas")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("hunter2", response.text)


@unittest.skipIf(TestClient is None, "fastapi no disponible")
class CorsTests(unittest.TestCase):
    def preflight(self, client, origin=LOCAL, method="GET", headers="ngrok-skip-browser-warning", path="/api/eventos"):
        request = {"Origin": origin, "Access-Control-Request-Method": method}
        if headers:
            request["Access-Control-Request-Headers"] = headers
        return client.options(path, headers=request)

    def test_preflight_from_localhost_allows_get_and_the_ngrok_header(self) -> None:
        with make() as client:
            response = self.preflight(client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], LOCAL)
        self.assertIn("ngrok-skip-browser-warning", response.headers["access-control-allow-headers"].lower())
        self.assertIn("GET", response.headers["access-control-allow-methods"])
        self.assertIn("OPTIONS", response.headers["access-control-allow-methods"])

    def test_preflight_works_on_every_endpoint(self) -> None:
        with make() as client:
            for path in ("/api/eventos", "/api/estadisticas", "/api/salud"):
                self.assertEqual(self.preflight(client, path=path).status_code, 200, path)

    def test_netlify_origin_is_accepted_once_configured_and_localhost_still_works(self) -> None:
        with make(cors_origins=[LOCAL, NETLIFY]) as client:
            for origin in (LOCAL, NETLIFY):
                response = self.preflight(client, origin=origin)
                self.assertEqual(response.status_code, 200, origin)
                self.assertEqual(response.headers["access-control-allow-origin"], origin)

    def test_unlisted_origin_is_refused(self) -> None:
        with make() as client:
            self.assertEqual(self.preflight(client, origin=NETLIFY).status_code, 400)
            self.assertEqual(self.preflight(client, origin="http://evil.example").status_code, 400)
            # la petición real tampoco recibe permiso: el navegador descartará la respuesta
            response = client.get("/api/salud", headers={"Origin": NETLIFY})
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_no_wildcard_and_no_credentials(self) -> None:
        with make() as client:
            response = client.get("/api/salud", headers={"Origin": LOCAL})
        self.assertEqual(response.headers["access-control-allow-origin"], LOCAL)
        self.assertNotEqual(response.headers["access-control-allow-origin"], "*")
        self.assertNotIn("access-control-allow-credentials", response.headers)

    def test_only_get_and_options_are_allowed(self) -> None:
        with make() as client:
            for method in ("POST", "PUT", "DELETE", "PATCH"):
                self.assertEqual(self.preflight(client, method=method).status_code, 400, method)
                self.assertEqual(client.request(method, "/api/eventos").status_code, 405, method)

    def test_other_request_headers_are_refused(self) -> None:
        with make() as client:
            self.assertEqual(self.preflight(client, headers="authorization").status_code, 400)
            self.assertEqual(self.preflight(client, headers="x-admin-token").status_code, 400)

    def test_error_responses_also_carry_cors_so_the_panel_can_read_them(self) -> None:
        with make(FailingQueries()) as client:
            fail = client.get("/api/eventos", headers={"Origin": LOCAL})
            bad = client.get("/api/eventos", params={"min_mag": "nan"}, headers={"Origin": LOCAL})
        for response, status in ((fail, 503), (bad, 400)):
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.headers["access-control-allow-origin"], LOCAL)

    def test_requests_without_origin_are_unaffected(self) -> None:
        with make() as client:
            response = client.get("/api/eventos", params={"start": START})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_cors_origins_are_read_from_the_environment(self) -> None:
        with mock.patch.dict(os.environ, {"CORS_ORIGINS": f"{LOCAL}, {NETLIFY}/"}):
            app = create_app(FakeQueries(), default_mode="demo")
        self.assertEqual(app.state.cors_origins, [LOCAL, NETLIFY])
        with TestClient(app) as client:
            self.assertEqual(self.preflight(client, origin=NETLIFY).status_code, 200)

    def test_default_without_the_variable_is_localhost_only(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CORS_ORIGINS", None)
            app = create_app(FakeQueries(), default_mode="demo")
        self.assertEqual(app.state.cors_origins, [LOCAL])

    def test_wildcard_in_the_environment_stops_startup(self) -> None:
        with mock.patch.dict(os.environ, {"CORS_ORIGINS": "*"}):
            with self.assertRaises(CorsConfigError):
                create_app(FakeQueries(), default_mode="demo")


@unittest.skipIf(TestClient is None, "fastapi no disponible")
class HealthTests(unittest.TestCase):
    def health(self, last_ingestion, mode="live", **kw):
        with make(FakeQueries(events(), last_ingestion=last_ingestion), default_mode=mode, stale_after_seconds=300, **kw) as client:
            response = client.get("/api/salud")
        return response

    def test_fresh_live_data(self) -> None:
        response = self.health(NOW - 60_000)
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual((body["status"], body["stale"], body["seconds_since_last_ingestion"]), ("ok", False, 60))
        self.assertEqual((body["stale_after_seconds"], body["mode"], body["database"]), (300, "live", "ok"))

    def test_stale_live_data_is_reported_with_http_200_because_the_service_works(self) -> None:
        response = self.health(NOW - 3_600_000)
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual((body["status"], body["stale"], body["stale_reason"]), ("stale", True, "last_successful_query_too_old"))
        self.assertEqual(body["last_ingestion"], NOW - 3_600_000)

    def test_live_with_no_successful_query_is_stale(self) -> None:
        body = self.health(None).json()
        self.assertEqual((body["status"], body["stale"], body["stale_reason"]), ("stale", True, "no_successful_query"))

    def test_demo_and_replay_are_never_stale(self) -> None:
        for mode in ("demo", "replay"):
            body = self.health(NOW - 10**9, mode=mode).json()
            self.assertEqual((body["status"], body["stale"]), ("ok", None), mode)

    def test_mode_parameter_overrides_the_default(self) -> None:
        queries = FakeQueries(events(), last_ingestion=NOW - 10**9)
        with make(queries, default_mode="demo") as client:
            body = client.get("/api/salud", params={"mode": "live"}).json()
        self.assertEqual((queries.health_calls, body["stale"]), (["live"], True))
        with make(queries, default_mode="demo") as client:
            self.assertEqual(client.get("/api/salud", params={"mode": "historico"}).status_code, 400)

    def test_database_down_is_503_with_explicit_state(self) -> None:
        with make(FailingQueries(), default_mode="live") as client:
            response = client.get("/api/salud")
        body = response.json()
        self.assertEqual(response.status_code, 503)
        self.assertEqual((body["status"], body["database"], body["api"], body["stale"]), ("error", "unavailable", "ok", None))

    def test_no_secrets_in_the_response(self) -> None:
        text = self.health(NOW).text.lower()
        for forbidden in ("password", "postgresql://", "secret", "token", "cors"):
            self.assertNotIn(forbidden, text)


@unittest.skipIf(TestClient is None, "fastapi no disponible")
class SurfaceTests(unittest.TestCase):
    def test_only_the_three_contract_routes_exist(self) -> None:
        with make() as client:
            for path in ("/", "/admin", "/api", "/api/admin", "/api/eventos/1", "/metrics", "/docs", "/redoc",
                         "/openapi.json", "/api/config", "/api/debug"):
                self.assertEqual(client.get(path).status_code, 404, path)
            for path in ("/api/eventos", "/api/estadisticas", "/api/salud"):
                self.assertEqual(client.post(path).status_code, 405, path)

    def test_database_failure_is_503_on_every_data_endpoint(self) -> None:
        with make(FailingQueries()) as client:
            for path in ("/api/eventos", "/api/estadisticas", "/api/salud"):
                response = client.get(path)
                self.assertEqual(response.status_code, 503, path)
                self.assertNotIn("features", response.json())


if __name__ == "__main__":
    unittest.main()
