"""Integración con PostgreSQL real (sin Kafka). El módulo crea una base temporal migrada con el migrador real;
cada test parte de tablas vacías. Los eventos se escriben en el esquema del modo (demo por defecto).

Ejecución (desde observatorio-sismico/, con postgres levantado):
    docker compose run --rm --no-deps -v ./tests:/app/tests api \
        python -m unittest discover -s tests/integration -t . -p "test_consumer_db.py"

Se omite si DATABASE_URL no existe o la base no es accesible (por ejemplo, en el host).
"""

import json
import unittest

try:
    import psycopg

    from backend.consumer.consumer import handle_record
    from backend.consumer.processing import RejectionReason
    from backend.consumer.versioning import VersionDecision
    from backend.db.quarantine import KafkaRef
except ImportError as error:  # dependencias no instaladas en el host
    psycopg = None
    IMPORT_ERROR = str(error)

from backend.producer.producer import DEMO_UPDATED_MS, build_demo_message
from tests.integration.dbutil import AVAILABLE, TempDatabase

DB = TempDatabase()


def setUpModule() -> None:
    DB.create()


def tearDownModule() -> None:
    DB.drop()


def raw(message) -> bytes:
    return message.to_json().encode()


@unittest.skipIf(not AVAILABLE or psycopg is None, "dependencias del backend no disponibles")
class ConsumerDatabaseTests(unittest.IsolatedAsyncioTestCase):
    mode = "demo"

    async def asyncSetUp(self) -> None:
        DB.truncate_events()
        self.conn = await psycopg.AsyncConnection.connect(DB.conninfo, autocommit=True, connect_timeout=3)
        self.offset = 0

    async def asyncTearDown(self) -> None:
        await self.conn.close()

    def ref(self) -> KafkaRef:
        self.offset += 1
        return KafkaRef("sismos.demo", 0, self.offset)

    async def send(self, raw_bytes: bytes, ref: KafkaRef | None = None, mode: str | None = None):
        return await handle_record(self.conn, raw_bytes, ref or self.ref(), mode or self.mode)

    async def scalar(self, sql: str, schema: str | None = None):
        # Tras handle_record el search_path apunta al esquema del último modo usado.
        await self.conn.execute(f'SET search_path TO "{schema or self.mode}"')
        return (await (await self.conn.execute(sql)).fetchone())[0]

    async def counts(self, schema: str | None = None) -> tuple[int, int, int]:
        return (
            await self.scalar("SELECT count(*) FROM event_current", schema),
            await self.scalar("SELECT count(*) FROM event_message", schema),
            await self.scalar("SELECT count(*) FROM quarantine_record", schema),
        )

    # --- aceptación §11: nuevo / duplicado / revisión / antigua ---

    async def test_new_event_creates_one_current_row(self) -> None:
        result = await self.send(raw(build_demo_message()))
        self.assertEqual(result.decision, VersionDecision.NEW)
        self.assertEqual(await self.counts(), (1, 1, 0))

    async def test_same_version_twice_does_not_increase_counts(self) -> None:
        await self.send(raw(build_demo_message()))
        result = await self.send(raw(build_demo_message()))
        self.assertEqual(result.decision, VersionDecision.DUPLICATE)
        self.assertEqual(await self.counts(), (1, 1, 0))

    async def test_newer_version_replaces_current_and_keeps_history(self) -> None:
        await self.send(raw(build_demo_message()))
        result = await self.send(raw(build_demo_message(updated_ms=DEMO_UPDATED_MS + 5000, mag=4.1)))
        self.assertEqual(result.decision, VersionDecision.REVISION)
        self.assertEqual(await self.counts(), (1, 2, 0))
        self.assertEqual(await self.scalar("SELECT current_version_ms FROM event_current"), DEMO_UPDATED_MS + 5000)
        mag = await self.scalar(
            "SELECT m.payload->'properties'->>'mag' FROM event_current c "
            "JOIN event_message m ON m.message_id = c.message_id"
        )
        self.assertEqual(mag, "4.1")

    async def test_older_version_after_newer_does_not_replace_current(self) -> None:
        await self.send(raw(build_demo_message(updated_ms=DEMO_UPDATED_MS + 5000, mag=4.1)))
        result = await self.send(raw(build_demo_message()))  # versión anterior llega tarde
        self.assertEqual(result.decision, VersionDecision.STALE)
        self.assertEqual(await self.scalar("SELECT current_version_ms FROM event_current"), DEMO_UPDATED_MS + 5000)
        self.assertEqual(await self.counts(), (1, 2, 0))  # la versión antigua queda en el historial

    async def test_replaying_whole_sequence_is_idempotent(self) -> None:
        sequence = [
            build_demo_message(),
            build_demo_message(updated_ms=DEMO_UPDATED_MS + 5000, mag=4.1),
            build_demo_message(),
        ]
        for message in sequence:
            await self.send(raw(message))
        before = await self.counts()
        current_before = await self.scalar("SELECT current_version_ms FROM event_current")
        for message in sequence:  # reinicio del consumidor: se relee todo
            await self.send(raw(message))
        self.assertEqual(await self.counts(), before)
        self.assertEqual(await self.scalar("SELECT current_version_ms FROM event_current"), current_before)

    async def test_null_magnitude_is_kept(self) -> None:
        await self.send(raw(build_demo_message(mag=None)))
        mag = await self.scalar(
            "SELECT m.payload->'properties'->'mag' FROM event_current c JOIN event_message m USING (message_id)"
        )
        self.assertIsNone(mag if mag != "null" else None)
        self.assertEqual(await self.counts(), (1, 1, 0))

    # --- cuarentena ---

    async def test_invalid_json_is_quarantined_with_reference(self) -> None:
        ref = KafkaRef("sismos.demo", 0, 77)
        result = await self.send(b"{broken", ref)
        self.assertEqual(result.rejection.reason, RejectionReason.INVALID_JSON)
        self.assertEqual(await self.counts(), (0, 0, 1))
        await self.conn.execute('SET search_path TO "demo"')
        row = await (
            await self.conn.execute("SELECT reason, original_payload, kafka_topic, kafka_partition, kafka_offset FROM quarantine_record")
        ).fetchone()
        self.assertTrue(row[0].startswith("invalid_json"))
        self.assertEqual(row[1:], ("{broken", "sismos.demo", 0, 77))

    async def test_invalid_coordinates_are_quarantined_and_no_point_is_created(self) -> None:
        value = build_demo_message().to_dict()
        value["payload"]["geometry"]["coordinates"] = [-3.7, 95.0, 10]
        result = await self.send(json.dumps(value).encode())
        self.assertEqual(result.rejection.reason, RejectionReason.INVALID_COORDINATES)
        self.assertEqual(await self.counts(), (0, 0, 1))
        self.assertEqual(await self.scalar("SELECT event_id FROM quarantine_record"), "demo-evt-001")

    async def test_non_earthquake_is_quarantined_with_reason(self) -> None:
        value = build_demo_message().to_dict()
        value["payload"]["properties"]["type"] = "explosion"
        result = await self.send(json.dumps(value).encode())
        self.assertEqual(result.rejection.reason, RejectionReason.NON_EARTHQUAKE_TYPE)
        self.assertIn("explosion", await self.scalar("SELECT reason FROM quarantine_record"))
        self.assertEqual(await self.counts(), (0, 0, 1))

    async def test_reprocessing_same_kafka_offset_does_not_duplicate_quarantine(self) -> None:
        ref = KafkaRef("sismos.demo", 0, 5)
        await self.send(b"nope", ref)
        await self.send(b"nope", ref)
        self.assertEqual(await self.scalar("SELECT count(*) FROM quarantine_record"), 1)

    async def test_nul_and_non_utf8_bytes_can_be_quarantined(self) -> None:
        await self.send(b"\x00\xff\xfe broken")
        self.assertEqual(await self.scalar("SELECT count(*) FROM quarantine_record"), 1)

    async def test_rejected_message_does_not_disturb_existing_current_row(self) -> None:
        await self.send(raw(build_demo_message()))
        await self.send(b"junk")
        self.assertEqual(await self.counts(), (1, 1, 1))


    # --- columnas desnormalizadas (Fase 6) ---

    async def row(self, sql: str, schema: str = "demo"):
        await self.conn.execute(f'SET search_path TO "{schema}"')
        return await (await self.conn.execute(sql)).fetchone()

    async def test_denormalized_columns_are_filled_from_payload(self) -> None:
        await self.send(raw(build_demo_message()))
        row = await self.row(
            "SELECT time_ms, mag, mag_type, depth_km, lon, lat, place, event_type, country_id, country_status, "
            "extract(epoch FROM ingested_at) > 0 FROM event_current"
        )
        self.assertEqual(
            row,
            (1_793_109_600_000, 3.2, "ml", 12.0, -3.7, 40.4, "Evento de prueba sintético", "earthquake",
             None, "pending", True),
        )

    async def test_null_magnitude_is_a_sql_null_not_zero(self) -> None:
        await self.send(raw(build_demo_message(mag=None)))
        self.assertEqual(await self.row("SELECT mag, mag IS NULL FROM event_current"), (None, True))

    async def test_revision_updates_columns_and_invalidates_previous_country(self) -> None:
        await self.send(raw(build_demo_message()))
        await self.row("SELECT 1")
        await self.conn.execute("UPDATE event_current SET country_id = 'ESP', country_status = 'assigned'")
        value = build_demo_message(updated_ms=DEMO_UPDATED_MS + 5000, mag=4.1).to_dict()
        value["payload"]["geometry"]["coordinates"] = [2.35, 48.85, 10]  # el epicentro se mueve a otro país
        await self.send(json.dumps(value).encode())
        row = await self.row("SELECT mag, lon, lat, country_id, country_status FROM event_current")
        self.assertEqual(row, (4.1, 2.35, 48.85, None, "pending"))  # no se conserva un país obsoleto

    async def test_country_columns_reject_inconsistent_state(self) -> None:
        await self.send(raw(build_demo_message()))
        await self.conn.execute('SET search_path TO "demo"')
        with self.assertRaises(psycopg.errors.CheckViolation):
            await self.conn.execute("UPDATE event_current SET country_status = 'assigned'")  # sin country_id
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            await self.conn.execute("UPDATE event_current SET country_id = 'ZZZ', country_status = 'assigned'")

    # --- aislamiento entre modos (D2) ---

    @staticmethod
    def live_raw() -> bytes:
        value = build_demo_message().to_dict()
        value.update({"mode": "live", "synthetic_flag": False, "source": "usgs"})
        return json.dumps(value).encode()

    async def test_modes_are_stored_in_separate_schemas(self) -> None:
        await self.send(raw(build_demo_message()), mode="demo")
        await self.send(self.live_raw(), mode="live")
        self.assertEqual(await self.counts("demo"), (1, 1, 0))
        self.assertEqual(await self.counts("live"), (1, 1, 0))
        self.assertEqual(await self.counts("replay"), (0, 0, 0))
        self.assertEqual(await self.counts("historico"), (0, 0, 0))

    async def test_same_event_id_in_two_modes_does_not_interfere(self) -> None:
        await self.send(self.live_raw(), mode="live")
        await self.send(raw(build_demo_message(updated_ms=DEMO_UPDATED_MS + 9000, mag=5.0)), mode="demo")
        self.assertEqual(await self.scalar("SELECT current_version_ms FROM event_current", "live"), DEMO_UPDATED_MS)
        self.assertEqual(await self.scalar("SELECT current_version_ms FROM event_current", "demo"), DEMO_UPDATED_MS + 9000)

    async def test_message_declaring_another_mode_is_quarantined_in_the_topic_schema(self) -> None:
        result = await self.send(raw(build_demo_message()), mode="live")  # mensaje demo llegado por el topic live
        self.assertEqual(result.rejection.reason, RejectionReason.MODE_MISMATCH)
        self.assertEqual(await self.counts("live"), (0, 0, 1))
        self.assertEqual(await self.counts("demo"), (0, 0, 0))
        self.assertIn("mode_mismatch", await self.scalar("SELECT reason FROM quarantine_record", "live"))

    async def test_unknown_mode_is_rejected_before_touching_the_database(self) -> None:
        with self.assertRaises(ValueError):
            await self.send(raw(build_demo_message()), mode="public")


if __name__ == "__main__":
    unittest.main()
