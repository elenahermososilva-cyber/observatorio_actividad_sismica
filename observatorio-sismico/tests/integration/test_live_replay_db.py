"""Productor live y replay contra PostgreSQL real + consumidor real, con USGS y Kafka simulados.

Nada sale a internet: el feed se sirve con httpx.MockTransport y Kafka es un `FakeSender` que guarda los mensajes.
Los mensajes que «publica» el productor se entregan después al consumidor real (`handle_record`), de modo que se
prueba el recorrido completo productor → consumidor → esquema aislado.

    docker compose run --rm --no-deps -v ./tests:/app/tests api \
        python -m unittest discover -s tests/integration -t . -p "test_live_replay_db.py"
"""

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:
    import httpx
    import psycopg
    from fastapi.testclient import TestClient

    from backend.api.app import create_app
    from backend.api.queries import PostgresQueries
    from backend.consumer.consumer import handle_record
    from backend.consumer.processing import RejectionReason
    from backend.consumer.versioning import VersionDecision
    from backend.db.connection import Database
    from backend.db.quarantine import KafkaRef
    from backend.producer import live, raw_store
    from backend.producer.envelope import build_envelope
    from backend.producer.replay import build_plan, select_events
    from backend.producer.schema import IngestionMode
    from backend.producer.usgs import fetch_feature_collection
except ImportError:
    httpx = None

from tests.integration.dbutil import AVAILABLE, TempDatabase

DB = TempDatabase()
URL = "https://usgs.test/all_day.geojson"


def setUpModule() -> None:
    DB.create()


def tearDownModule() -> None:
    DB.drop()


def feature(event_id="us1", updated=2_000, time_ms=1_000, mag=5.5, kind="earthquake", coords=(10.0, 20.0, 5.0)) -> dict:
    return {
        "type": "Feature", "id": event_id,
        "geometry": {"type": "Point", "coordinates": list(coords)},
        "properties": {"mag": mag, "magType": "mww", "place": "X", "time": time_ms, "updated": updated, "type": kind},
    }


class FakeSender:
    def __init__(self, fail_at: int | None = None) -> None:
        self.sent: list[tuple[str, bytes, bytes | None]] = []
        self.fail_at = fail_at

    async def send_and_wait(self, topic, value, key=None):
        if self.fail_at is not None and len(self.sent) == self.fail_at:
            raise ConnectionError("Kafka did not acknowledge")
        self.sent.append((topic, value, key))


class FeedServer:
    """Sirve respuestas del feed en orden; cada una puede ser una lista de features o un httpx.Response de error."""

    def __init__(self, *responses) -> None:
        self.queue = list(responses)
        self.requests = 0

    def handler(self, request):
        self.requests += 1
        item = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(item, httpx.Response):
            return item
        body = {"type": "FeatureCollection", "metadata": {"generated": 1_000 + self.requests}, "features": item}
        return httpx.Response(200, content=json.dumps(body).encode())


def one_attempt_fetch(*args, **kwargs):
    return fetch_feature_collection(*args, attempts=2, sleep=_no_sleep, **kwargs)


async def _no_sleep(_):
    return None


@unittest.skipIf(not AVAILABLE or httpx is None, "dependencias del backend no disponibles")
class LiveCycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        DB.truncate_events()
        self.conn = await psycopg.AsyncConnection.connect(DB.conninfo, autocommit=True)
        await self.conn.execute("TRUNCATE ingest.published_version, ingest.extraction_log RESTART IDENTITY")
        self.db = Database(DB.conninfo)
        self.tmp = tempfile.TemporaryDirectory()
        self.raw_dir = Path(self.tmp.name) / "live"
        self.clock_value = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
        patcher = mock.patch.object(live, "fetch_feature_collection", one_attempt_fetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.offset = 0

    async def asyncTearDown(self) -> None:
        await self.db.close()
        await self.conn.close()
        self.tmp.cleanup()

    def clock(self) -> datetime:
        self.clock_value = self.clock_value.replace(second=self.clock_value.second + 1)
        return self.clock_value

    async def cycle(self, server: FeedServer, sender: FakeSender):
        async with httpx.AsyncClient(transport=httpx.MockTransport(server.handler)) as http:
            return await live.run_cycle(
                http=http, sender=sender, db=self.db, topic="sismos.live", url=URL, raw_dir=self.raw_dir,
                retention_days=14, now=self.clock,
            )

    async def scalar(self, sql, *params):
        return (await (await self.conn.execute(sql, params)).fetchone())[0]

    async def deliver(self, sender: FakeSender, start: int = 0):
        """Entrega al consumidor real los mensajes que «publicó» el productor y devuelve sus resultados."""
        results = []
        for topic, value, _ in sender.sent[start:]:
            self.offset += 1
            results.append(await handle_record(self.conn, value, KafkaRef(topic, 0, self.offset), "live"))
        return results

    # ------------------------------------------------------------------ 7.2 / 7.3 / 7.4
    async def test_first_cycle_publishes_everything_and_registers_the_query(self) -> None:
        sender = FakeSender()
        report = await self.cycle(FeedServer([feature("a"), feature("b"), feature("c")]), sender)
        self.assertEqual((report.ok, report.fetched, report.published, report.skipped), (True, 3, 3, 0))
        self.assertEqual([k for _, _, k in sender.sent], [b"a", b"b", b"c"])  # clave Kafka = event_id
        self.assertEqual(await self.scalar("SELECT count(*) FROM ingest.published_version WHERE mode = 'live'"), 3)
        row = await (await self.conn.execute(
            "SELECT ok, record_count, http_status, response_sha256, raw_path, error, source_url FROM ingest.extraction_log"
        )).fetchone()
        self.assertEqual(row[:3], (True, 3, 200))
        self.assertEqual((row[5], row[6]), (None, URL))
        self.assertIsNotNone(row[4])
        original = json.loads(raw_store.read_raw(Path(row[4])))
        self.assertEqual(len(original["features"]), 3)  # el original íntegro se conserva

    async def test_identical_content_is_not_republished_nor_stored_again(self) -> None:
        sender = FakeSender()
        server = FeedServer([feature("a"), feature("b")])  # el feed repite los mismos eventos; `generated` cambia
        await self.cycle(server, sender)
        report = await self.cycle(server, sender)
        self.assertEqual((report.published, report.skipped), (0, 2))
        self.assertEqual(len(sender.sent), 2)
        self.assertEqual(await self.scalar("SELECT count(*) FROM ingest.extraction_log WHERE ok"), 2)  # ambas consultas registradas
        self.assertEqual(await self.scalar("SELECT count(raw_path) FROM ingest.extraction_log"), 1)  # solo un original guardado
        self.assertEqual(len(list(self.raw_dir.rglob("*.geojson.gz"))), 1)

    async def test_only_new_events_and_revisions_are_published(self) -> None:
        sender = FakeSender()
        await self.cycle(FeedServer([feature("a"), feature("b")]), sender)
        report = await self.cycle(
            FeedServer([feature("a"), feature("b", updated=3_000, mag=6.0), feature("c")]), sender
        )
        self.assertEqual((report.published, report.skipped), (2, 1))
        self.assertEqual([k for _, _, k in sender.sent[2:]], [b"b", b"c"])  # la revisión de b y el nuevo c
        self.assertEqual(await self.scalar("SELECT count(*) FROM ingest.extraction_log WHERE raw_path IS NOT NULL"), 2)

    async def test_failed_query_is_logged_and_keeps_previous_valid_state(self) -> None:
        sender = FakeSender()
        await self.cycle(FeedServer([feature("a")]), sender)
        published_before = await self.scalar("SELECT count(*) FROM ingest.published_version")
        report = await self.cycle(FeedServer(httpx.Response(503)), sender)
        self.assertFalse(report.ok)
        self.assertIn("HTTP 503", report.error)
        self.assertEqual(len(sender.sent), 1)  # nada nuevo publicado
        self.assertEqual(await self.scalar("SELECT count(*) FROM ingest.published_version"), published_before)
        row = await (await self.conn.execute(
            "SELECT ok, http_status, record_count, error FROM ingest.extraction_log ORDER BY extraction_id DESC LIMIT 1"
        )).fetchone()
        self.assertEqual(row[:3], (False, 503, None))
        self.assertIn("HTTP 503", row[3])
        # tras recuperarse, el siguiente ciclo continúa sin republicar lo ya publicado
        report = await self.cycle(FeedServer([feature("a"), feature("b")]), sender)
        self.assertEqual((report.ok, report.published, report.skipped), (True, 1, 1))

    async def test_invalid_json_response_is_a_logged_failure(self) -> None:
        report = await self.cycle(FeedServer(httpx.Response(200, content=b"<html>down</html>")), FakeSender())
        self.assertFalse(report.ok)
        self.assertEqual(await self.scalar("SELECT count(*) FROM ingest.extraction_log WHERE NOT ok"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM ingest.published_version"), 0)

    async def test_version_is_marked_published_only_after_kafka_ack(self) -> None:
        sender = FakeSender(fail_at=2)  # Kafka confirma 2 mensajes y deja de confirmar
        server = FeedServer([feature("a"), feature("b"), feature("c"), feature("d")])
        with self.assertRaises(ConnectionError):
            await self.cycle(server, sender)
        marked = {r[0] for r in await (await self.conn.execute("SELECT event_id FROM ingest.published_version")).fetchall()}
        self.assertEqual(marked, {"a", "b"})  # c no se marcó: Kafka no lo confirmó
        sender.fail_at = None
        report = await self.cycle(server, sender)
        self.assertEqual((report.published, report.skipped), (2, 2))
        self.assertEqual([k for _, _, k in sender.sent], [b"a", b"b", b"c", b"d"])  # sin republicar a ni b

    async def test_crash_between_ack_and_mark_republishes_and_consumer_tolerates_it(self) -> None:
        sender = FakeSender()
        await self.cycle(FeedServer([feature("a")]), sender)
        await self.conn.execute("TRUNCATE ingest.published_version")  # simula caída tras el ack y antes de marcar
        await self.cycle(FeedServer([feature("a")]), sender)
        self.assertEqual(len(sender.sent), 2)  # reenviado: es el comportamiento documentado
        results = await self.deliver(sender)
        self.assertEqual([r.decision for r in results], [VersionDecision.NEW, VersionDecision.DUPLICATE])
        self.assertEqual(await self.scalar('SELECT count(*) FROM live.event_current'), 1)

    # ------------------------------------------------------------------ calidad: todo lo publicado llega a algún sitio
    async def test_non_earthquakes_and_malformed_features_are_quarantined_once_not_dropped(self) -> None:
        sender = FakeSender()
        no_id = feature("zzz")
        del no_id["id"]
        features = [
            feature("quake"), feature("blast", kind="explosion"), feature("badlat", coords=(10.0, 95.0, 5.0)),
            no_id, feature("nullmag", mag=None),
        ]
        server = FeedServer(features)
        first = await self.cycle(server, sender)
        second = await self.cycle(server, sender)  # siguen en la ventana de 24 h: no deben volver a publicarse
        self.assertEqual((first.published, first.malformed, second.published, second.skipped), (5, 2, 0, 5))

        results = await self.deliver(sender)
        reasons = sorted(r.rejection.reason.value for r in results if r.rejection)
        self.assertEqual(reasons, sorted(["non_earthquake_type", "invalid_coordinates", "schema_violation"]))
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_current"), 2)  # quake y nullmag
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.quarantine_record"), 3)  # nada descartado en silencio
        self.assertIsNone(await self.scalar("SELECT mag FROM live.event_current WHERE event_id = 'nullmag'"))
        self.assertEqual(await self.scalar("SELECT count(*) FROM demo.event_current"), 0)  # aislamiento

    async def test_revision_arrives_through_the_pipeline_and_replaces_current(self) -> None:
        sender = FakeSender()
        await self.cycle(FeedServer([feature("a", updated=2_000, mag=4.0)]), sender)
        await self.cycle(FeedServer([feature("a", updated=9_000, mag=4.6)]), sender)
        results = await self.deliver(sender)
        self.assertEqual([r.decision for r in results], [VersionDecision.NEW, VersionDecision.REVISION])
        self.assertEqual(await self.scalar("SELECT mag FROM live.event_current"), 4.6)
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_message"), 2)

    # ------------------------------------------------------------------ API: last_ingestion
    def api_get(self, path: str, **params):
        def call():
            app = create_app(PostgresQueries(DB.conninfo), default_mode="live")
            with TestClient(app) as client:
                return client.get(path, params=params).json()

        return asyncio.to_thread(call)

    async def test_last_ingestion_is_the_last_successful_usgs_query_not_the_last_event(self) -> None:
        sender = FakeSender()
        await self.cycle(FeedServer([feature("a")]), sender)
        await self.cycle(FeedServer([feature("a")]), sender)  # consulta correcta SIN eventos nuevos: igualmente avanza
        ok_ms = await self.scalar(
            "SELECT (extract(epoch FROM max(started_at)) * 1000)::bigint FROM ingest.extraction_log WHERE ok"
        )
        self.assertEqual((await self.api_get("/api/eventos", start="1970-01-01"))["metadata"]["last_ingestion"], ok_ms)
        await self.cycle(FeedServer(httpx.Response(503)), sender)  # una consulta fallida NO mueve last_ingestion
        failed_ms = await self.scalar(
            "SELECT (extract(epoch FROM max(started_at)) * 1000)::bigint FROM ingest.extraction_log WHERE NOT ok"
        )
        self.assertGreater(failed_ms, ok_ms)  # la fallida es posterior: no basta con tomar el máximo de todas
        body = await self.api_get("/api/eventos", start="1970-01-01")
        self.assertEqual(body["metadata"]["last_ingestion"], ok_ms)
        self.assertEqual(body["metadata"]["mode"], "live")
        self.assertEqual((await self.api_get("/api/salud"))["last_ingestion"], ok_ms)

    async def test_live_with_no_successful_query_reports_null(self) -> None:
        await self.cycle(FeedServer(httpx.Response(500)), FakeSender())
        self.assertIsNone((await self.api_get("/api/eventos", start="1970-01-01"))["metadata"]["last_ingestion"])


@unittest.skipIf(not AVAILABLE or httpx is None, "dependencias del backend no disponibles")
class ReplayThroughConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        DB.truncate_events()
        self.conn = await psycopg.AsyncConnection.connect(DB.conninfo, autocommit=True)
        self.offset = 0

    async def asyncTearDown(self) -> None:
        await self.conn.close()

    async def scalar(self, sql, *params):
        return (await (await self.conn.execute(sql, params)).fetchone())[0]

    def replay_messages(self, events):
        now = datetime(2026, 11, 17, 15, 30, 0, tzinfo=timezone.utc)
        out = []
        for item in build_plan(events):
            env = build_envelope(
                item.feature, mode=IngestionMode.REPLAY, source=item.source, synthetic_flag=item.synthetic_flag,
                ingested_at=now, replay_at=now,
            )
            out.append((item, env.value))
        return out

    async def run_plan(self, events):
        results = []
        for item, value in self.replay_messages(events):
            self.offset += 1
            result = await handle_record(self.conn, value, KafkaRef("sismos.replay", 0, self.offset), "replay")
            results.append((item, result))
        return results

    def history(self):
        return select_events(
            [feature(f"e{i}", time_ms=1_735_689_600_000 + i * 3_600_000, updated=1_736_000_000_000 + i, mag=5.0 + i / 10)
             for i in range(6)],
            start_ms=0, min_mag=5.0, count=3,
        )

    async def test_controlled_cases_produce_the_expected_decisions(self) -> None:
        results = await self.run_plan(self.history())
        self.assertEqual(
            [(i.label, r.decision.value.upper()) for i, r in results],
            [("original", "NEW")] * 3 + [("duplicate", "DUPLICATE"), ("revision", "REVISION"), ("stale", "STALE")],
        )
        for item, result in results:
            self.assertEqual(result.decision.value.upper(), item.expected)

    async def test_replay_state_is_isolated_and_keeps_original_event_time_plus_replay_time(self) -> None:
        events = self.history()
        await self.run_plan(events)
        self.assertEqual(await self.scalar("SELECT count(*) FROM replay.event_current"), 3)
        self.assertEqual(await self.scalar("SELECT count(*) FROM replay.event_message"), 4)  # 3 + la revisión
        for schema in ("live", "demo", "historico"):
            self.assertEqual(await self.scalar(f"SELECT count(*) FROM {schema}.event_current"), 0, schema)
        # tiempo de ocurrencia ORIGINAL intacto (nada se desplaza a «hoy») y tiempo de reproducción aparte
        event = events[0]
        row = await (await self.conn.execute(
            "SELECT c.time_ms, m.replay_at, m.mode FROM replay.event_current c JOIN replay.event_message m "
            "USING (message_id) WHERE c.event_id = %s", (event["id"],),
        )).fetchone()
        self.assertEqual(row[0], event["properties"]["time"])
        self.assertEqual(row[1], datetime(2026, 11, 17, 15, 30, tzinfo=timezone.utc))
        self.assertEqual(row[2], "replay")

    async def test_revision_replaces_current_and_stale_does_not(self) -> None:
        events = self.history()
        await self.run_plan(events)
        revised = await (await self.conn.execute(
            "SELECT mag, current_version_ms FROM replay.event_current WHERE event_id = %s", (events[1]["id"],)
        )).fetchone()
        self.assertEqual(revised[0], round(events[1]["properties"]["mag"] + 0.2, 1))
        self.assertEqual(revised[1], events[1]["properties"]["updated"] + 60_000)

    async def test_running_the_replay_twice_changes_nothing(self) -> None:
        events = self.history()
        await self.run_plan(events)
        before = [await self.scalar(f"SELECT count(*) FROM replay.{t}") for t in ("event_current", "event_message")]
        await self.run_plan(events)
        after = [await self.scalar(f"SELECT count(*) FROM replay.{t}") for t in ("event_current", "event_message")]
        self.assertEqual(before, after)

    async def test_replay_message_on_the_live_topic_is_rejected_not_mixed(self) -> None:
        _, value = self.replay_messages(self.history())[0]
        result = await handle_record(self.conn, value, KafkaRef("sismos.live", 0, 1), "live")
        self.assertEqual(result.rejection.reason, RejectionReason.MODE_MISMATCH)
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_current"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.quarantine_record"), 1)

    async def test_database_enforces_replay_at_even_for_direct_inserts(self) -> None:
        with self.assertRaises(psycopg.errors.CheckViolation):
            await self.conn.execute(
                "INSERT INTO replay.event_message (event_id, updated_ms, source, mode, ingested_at, synthetic_flag, payload) "
                "VALUES ('x', 1, 's', 'replay', now(), false, '{}')"
            )
        with self.assertRaises(psycopg.errors.CheckViolation):
            await self.conn.execute(
                "INSERT INTO live.event_message (event_id, updated_ms, source, mode, ingested_at, synthetic_flag, payload, replay_at) "
                "VALUES ('x', 1, 's', 'live', now(), false, '{}', now())"
            )


if __name__ == "__main__":
    unittest.main()
