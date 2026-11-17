"""API contra PostgreSQL real (base temporal migrada con el migrador real). Se ejecuta en el contenedor:

    docker compose run --rm --no-deps -v ./tests:/app/tests api \
        python -m unittest discover -s tests/integration -t . -p "test_api_db.py"
"""

import asyncio
import json
import unittest

try:
    import psycopg
    from fastapi.testclient import TestClient

    from backend.api.app import create_app
    from backend.api.queries import PostgresQueries
    from backend.consumer.consumer import handle_record
    from backend.db.quarantine import KafkaRef
except ImportError:
    psycopg = None

from backend.producer.producer import DEMO_UPDATED_MS, build_demo_message
from tests.integration.dbutil import AVAILABLE, TempDatabase

DB = TempDatabase()
EVENT_TIME = 1_793_109_600_000  # ocurrencia del evento demo: 2026-10-27T14:00:00Z
START = "2026-10-27T00:00:00Z"


def setUpModule() -> None:
    DB.create()


def tearDownModule() -> None:
    DB.drop()


def live_raw(**overrides) -> bytes:
    value = build_demo_message().to_dict()
    value.update({"mode": "live", "synthetic_flag": False, "source": "usgs"})
    value.update(overrides)
    return json.dumps(value).encode()


@unittest.skipIf(not AVAILABLE or psycopg is None, "dependencias del backend no disponibles")
class ApiDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        DB.truncate_events()
        self.admin = await psycopg.AsyncConnection.connect(DB.conninfo, autocommit=True, connect_timeout=3)
        self.offset = 0

    async def asyncTearDown(self) -> None:
        await self.admin.close()

    async def ingest(self, message, mode: str = "demo") -> None:
        self.offset += 1
        await handle_record(self.admin, message.to_json().encode(), KafkaRef(f"sismos.{mode}", 0, self.offset), mode)

    async def get(self, path: str, default_mode: str = "demo", **params):
        """TestClient es síncrono: se ejecuta en un hilo para no bloquear el bucle del test."""

        def call():
            app = create_app(PostgresQueries(DB.conninfo), clock=lambda: EVENT_TIME + 3_600_000, default_mode=default_mode)
            with TestClient(app) as client:
                return client.get(path, params=params)

        return await asyncio.to_thread(call)

    async def test_empty_database_is_200_with_empty_features(self) -> None:
        response = await self.get("/api/eventos", start="2020-01-01")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["features"], [])
        self.assertIsNone(body["metadata"]["last_ingestion"])

    async def test_ingested_demo_event_appears_exactly_once_even_after_duplicates(self) -> None:
        await self.ingest(build_demo_message())
        await self.ingest(build_demo_message())  # duplicado
        body = (await self.get("/api/eventos", start=START)).json()
        self.assertEqual([f["id"] for f in body["features"]], ["demo-evt-001"])
        self.assertEqual(body["metadata"]["count"], 1)
        self.assertEqual(body["metadata"]["mode"], "demo")
        self.assertIsInstance(body["metadata"]["last_ingestion"], int)
        self.assertEqual(
            body["features"][0]["geometry"]["coordinates"], [-3.7, 40.4, 12.0]
        )

    async def test_revision_replaces_current_and_stale_does_not(self) -> None:
        await self.ingest(build_demo_message())
        await self.ingest(build_demo_message(updated_ms=DEMO_UPDATED_MS + 5000, mag=4.1))
        await self.ingest(build_demo_message())  # versión antigua tardía
        body = (await self.get("/api/eventos", start=START)).json()
        self.assertEqual(body["metadata"]["count"], 1)
        self.assertEqual(body["features"][0]["properties"]["mag"], 4.1)
        self.assertEqual(body["features"][0]["properties"]["updated"], DEMO_UPDATED_MS + 5000)

    async def test_time_filters_against_database(self) -> None:
        await self.ingest(build_demo_message())
        inclusive = await self.get("/api/eventos", start="2026-10-27T14:00:00Z")
        exclusive_end = await self.get("/api/eventos", start=START, end="2026-10-27T14:00:00Z")
        self.assertEqual(inclusive.json()["metadata"]["count"], 1)  # start == time → incluido
        self.assertEqual(exclusive_end.json()["metadata"]["count"], 0)  # end == time → excluido

    async def test_null_magnitude_is_serialized_as_null(self) -> None:
        await self.ingest(build_demo_message(mag=None))
        body = (await self.get("/api/eventos", start=START)).json()
        self.assertIsNone(body["features"][0]["properties"]["mag"])

    async def test_quarantined_records_never_appear_as_points(self) -> None:
        await handle_record(self.admin, b'{"broken', KafkaRef("sismos.demo", 0, 99), "demo")
        body = (await self.get("/api/eventos", start="2020-01-01")).json()
        self.assertEqual(body["features"], [])

    # --- modos aislados (D2) ---

    async def test_mode_parameter_selects_isolated_data(self) -> None:
        await self.ingest(build_demo_message(), "demo")
        await handle_record(self.admin, live_raw(), KafkaRef("sismos.live", 0, 500), "live")
        demo = (await self.get("/api/eventos", start=START, mode="demo")).json()
        live = (await self.get("/api/eventos", start=START, mode="live")).json()
        replay = (await self.get("/api/eventos", start=START, mode="replay")).json()
        self.assertEqual((demo["metadata"]["mode"], demo["metadata"]["count"]), ("demo", 1))
        self.assertEqual((live["metadata"]["mode"], live["metadata"]["count"]), ("live", 1))
        self.assertEqual((replay["metadata"]["mode"], replay["metadata"]["count"]), ("replay", 0))

    async def test_default_mode_applies_when_mode_is_omitted(self) -> None:
        await self.ingest(build_demo_message(), "demo")
        as_demo = (await self.get("/api/eventos", default_mode="demo", start=START)).json()
        as_live = (await self.get("/api/eventos", default_mode="live", start=START)).json()
        self.assertEqual(as_demo["metadata"]["count"], 1)
        self.assertEqual(as_live["metadata"]["count"], 0)

    async def test_invalid_mode_is_400_and_never_reaches_sql(self) -> None:
        for bad in ("historico", "public", 'demo"; DROP TABLE event_current;--'):
            response = await self.get("/api/eventos", start=START, mode=bad)
            self.assertEqual(response.status_code, 400, bad)
            self.assertEqual(response.json()["error"]["code"], "invalid_parameter")
        await self.ingest(build_demo_message())  # las tablas siguen existiendo
        self.assertEqual((await self.get("/api/eventos", start=START)).json()["metadata"]["count"], 1)

    # --- país ---

    async def test_country_name_comes_from_dimension_when_assigned(self) -> None:
        await self.ingest(build_demo_message())
        pending = (await self.get("/api/eventos", start=START)).json()["features"][0]["properties"]
        self.assertEqual((pending["country_id"], pending["country_name"]), (None, None))
        await self.admin.execute('SET search_path TO "demo"')
        await self.admin.execute("UPDATE event_current SET country_id = 'ESP', country_status = 'assigned'")
        assigned = (await self.get("/api/eventos", start=START)).json()["features"][0]["properties"]
        self.assertEqual(assigned["country_id"], "ESP")
        self.assertEqual(assigned["country_name"], "España")

    async def test_health_reflects_last_ingestion(self) -> None:
        await self.ingest(build_demo_message())
        response = await self.get("/api/salud")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"], "ok")
        self.assertIsInstance(response.json()["last_ingestion"], int)

    async def test_unreachable_database_returns_503_not_empty_collection(self) -> None:
        def call():
            queries = PostgresQueries("postgresql://nobody:x@127.0.0.1:1/none", timeout=1.0)
            with TestClient(create_app(queries, clock=lambda: EVENT_TIME, default_mode="demo")) as client:
                return client.get("/api/eventos", params={"start": "2020-01-01"}), client.get("/api/salud")

        eventos, salud = await asyncio.to_thread(call)
        self.assertEqual(eventos.status_code, 503)
        self.assertNotIn("features", eventos.json())
        self.assertEqual(eventos.json()["error"]["code"], "database_unavailable")
        self.assertEqual(salud.status_code, 503)


if __name__ == "__main__":
    unittest.main()
