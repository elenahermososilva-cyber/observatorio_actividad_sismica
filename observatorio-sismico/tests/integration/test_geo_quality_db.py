"""Fase 8 contra PostgreSQL real: país por punto-en-polígono, calidad, backfill, cargador del histórico, aislamiento.

    docker compose run --rm --no-deps -v ./tests:/app/tests api \
        python -m unittest discover -s tests/integration -t . -p "test_geo_quality_db.py"
"""

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

try:
    import psycopg
    from fastapi.testclient import TestClient

    from backend.api.app import create_app
    from backend.api.queries import PostgresQueries
    from backend.consumer.consumer import handle_record
    from backend.consumer.geo import CountryIndex
    from backend.consumer.geo_backfill import backfill_all
    from backend.consumer.history_loader import load_history
    from backend.consumer.processing import RejectionReason
    from backend.consumer.versioning import VersionDecision
    from backend.db.quarantine import KafkaRef
    from backend.producer.envelope import build_envelope
    from backend.producer.schema import IngestionMode
except ImportError:
    psycopg = None

from tests.integration.dbutil import AVAILABLE, COUNTRIES, TempDatabase

DB = TempDatabase()
GEO = None
NOW = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)
HOUR = 3_600_000


def setUpModule() -> None:
    global GEO
    DB.create()
    if AVAILABLE and psycopg is not None:
        GEO = CountryIndex.from_file(COUNTRIES)


def tearDownModule() -> None:
    DB.drop()


def feature(event_id, lon=-3.7, lat=40.42, depth=10.0, mag=4.5, mag_type="mww", place="Somewhere", updated=None,
            time_ms=None, kind="earthquake") -> dict:
    time_ms = NOW_MS - HOUR if time_ms is None else time_ms
    coordinates = [lon, lat] if depth is False else [lon, lat, depth]
    return {
        "type": "Feature", "id": event_id,
        "geometry": {"type": "Point", "coordinates": coordinates},
        "properties": {"mag": mag, "magType": mag_type, "place": place, "time": time_ms,
                       "updated": time_ms + 1000 if updated is None else updated, "type": kind},
    }


def raw(feat, mode=IngestionMode.LIVE, source="usgs") -> bytes:
    return build_envelope(feat, mode=mode, source=source, synthetic_flag=False, ingested_at=NOW).value


@unittest.skipIf(not AVAILABLE or psycopg is None, "dependencias del backend no disponibles")
class AttributionAndQualityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        DB.truncate_events()
        self.conn = await psycopg.AsyncConnection.connect(DB.conninfo, autocommit=True)
        self.offset = 0

    async def asyncTearDown(self) -> None:
        await self.conn.close()

    async def send(self, feat, mode="live", geo=True, **kw):
        self.offset += 1
        value = raw(feat, **kw) if not isinstance(feat, bytes) else feat
        return await handle_record(self.conn, value, KafkaRef(f"sismos.{mode}", 0, self.offset), mode, GEO if geo else None)

    async def row(self, event_id, schema="live"):
        return await (await self.conn.execute(
            f'SELECT country_id, country_status, quality_flags, mag, depth_km, place, mag_type FROM "{schema}".event_current '
            "WHERE event_id = %s", (event_id,),
        )).fetchone()

    async def scalar(self, sql, *params):
        return (await (await self.conn.execute(sql, params)).fetchone())[0]

    # ------------------------------------------------------------------ país
    async def test_land_event_is_assigned_to_its_country(self) -> None:
        await self.send(feature("madrid", lon=-3.7, lat=40.42))
        await self.send(feature("paris", lon=2.35, lat=48.85))
        self.assertEqual((await self.row("madrid"))[:2], ("ESP", "assigned"))
        self.assertEqual((await self.row("paris"))[:2], ("FRA", "assigned"))

    async def test_maritime_event_is_unassigned_and_stays_in_the_dataset(self) -> None:
        await self.send(feature("mar", lon=-30.0, lat=0.0))
        self.assertEqual((await self.row("mar"))[:2], (None, "unassigned"))
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_current"), 1)  # permanece en el análisis
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.quarantine_record"), 0)  # no es un error

    async def test_place_text_never_decides_the_country(self) -> None:
        await self.send(feature("liar", lon=-30.0, lat=0.0, place="10 km N of Madrid, Spain"))  # texto dice España, mar abierto
        await self.send(feature("liar2", lon=2.35, lat=48.85, place="Atlantic Ocean"))  # texto dice océano, tierra francesa
        self.assertEqual((await self.row("liar"))[:2], (None, "unassigned"))
        self.assertEqual((await self.row("liar2"))[:2], ("FRA", "assigned"))

    async def test_border_vertex_is_assigned_to_lowest_code_and_flagged(self) -> None:
        await self.send(feature("frontera", lon=-1.901351, lat=43.422802))
        country, status, flags, *_ = await self.row("frontera")
        self.assertEqual((country, status), ("ESP", "assigned"))
        self.assertIn("country_boundary_ambiguous", flags)

    async def test_revision_that_moves_the_epicentre_recomputes_the_country(self) -> None:
        await self.send(feature("mueve", lon=-3.7, lat=40.42, updated=NOW_MS - 5000))
        self.assertEqual((await self.row("mueve"))[0], "ESP")
        result = await self.send(feature("mueve", lon=2.35, lat=48.85, updated=NOW_MS - 1000))
        self.assertEqual(result.decision, VersionDecision.REVISION)
        self.assertEqual((await self.row("mueve"))[:2], ("FRA", "assigned"))  # no conserva el país obsoleto
        await self.send(feature("mueve", lon=-30.0, lat=0.0, updated=NOW_MS - 500))
        self.assertEqual((await self.row("mueve"))[:2], (None, "unassigned"))

    async def test_stale_version_does_not_change_the_country(self) -> None:
        await self.send(feature("viejo", lon=2.35, lat=48.85, updated=NOW_MS - 1000))
        result = await self.send(feature("viejo", lon=-3.7, lat=40.42, updated=NOW_MS - 9000))
        self.assertEqual(result.decision, VersionDecision.STALE)
        self.assertEqual((await self.row("viejo"))[0], "FRA")

    async def test_without_a_country_index_the_country_stays_pending_not_invented(self) -> None:
        await self.send(feature("sin_indice"), geo=False)
        country, status, flags, *_ = await self.row("sin_indice")
        self.assertEqual((country, status), (None, "pending"))
        self.assertEqual(flags, [])  # la calidad sí se evalúa sin índice geográfico

    # ------------------------------------------------------------------ calidad
    async def test_null_magnitude_is_kept_flagged_and_never_zero(self) -> None:
        result = await self.send(feature("nd", mag=None, mag_type=None))
        self.assertIsNone(result.rejection)
        _, _, flags, mag, *_ = await self.row("nd")
        self.assertIsNone(mag)
        self.assertEqual(flags, ["gap_mag_missing"])

    async def test_negative_magnitude_and_depth_are_kept_not_rejected(self) -> None:
        result = await self.send(feature("neg", mag=-0.4, depth=-1.2))
        self.assertIsNone(result.rejection)
        _, _, flags, mag, depth, *_ = await self.row("neg")
        self.assertEqual((mag, depth), (-0.4, -1.2))
        self.assertEqual(sorted(flags), ["anomaly_depth_negative", "anomaly_mag_negative"])

    async def test_missing_depth_is_null_and_flagged(self) -> None:
        await self.send(feature("sin_prof", depth=False))
        _, _, flags, _, depth, *_ = await self.row("sin_prof")
        self.assertIsNone(depth)
        self.assertEqual(flags, ["gap_depth_missing"])

    async def test_transformations_change_the_stored_columns_and_are_recorded(self) -> None:
        await self.send(feature("fix", place="  10 km N of Madrid \n", mag_type="Mww"))
        _, _, flags, _, _, place, mag_type = await self.row("fix")
        self.assertEqual((place, mag_type), ("10 km N of Madrid", "mww"))
        self.assertEqual(sorted(flags), ["fixed_mag_type_lowercased", "fixed_place_trimmed"])
        # el original NO se altera: el payload conserva el valor tal como llegó
        original = await self.scalar(
            "SELECT m.payload->'properties'->>'place' FROM live.event_message m WHERE m.event_id = 'fix'"
        )
        self.assertEqual(original, "  10 km N of Madrid \n")

    async def test_how_many_records_each_rule_affects_can_be_counted_in_sql(self) -> None:
        for feat in (
            feature("a", mag=None, mag_type=None), feature("b", mag=None, mag_type=None), feature("c", mag=-1.0),
            feature("d", place=" x "), feature("e"), feature("f", lon=-30.0, lat=0.0),
        ):
            await self.send(feat)
        counts = dict(await (await self.conn.execute(
            "SELECT code, count(*) FROM live.event_current, unnest(quality_flags) code GROUP BY code"
        )).fetchall())
        self.assertEqual(counts, {"gap_mag_missing": 2, "anomaly_mag_negative": 1, "fixed_place_trimmed": 1})
        clean = await self.scalar("SELECT count(*) FROM live.event_current WHERE cardinality(quality_flags) = 0")
        self.assertEqual(clean, 2)  # e (limpio) y f (mar: sin país no es una anomalía de calidad)

    async def test_what_cannot_be_treated_still_goes_to_quarantine_with_its_reason(self) -> None:
        bad_lat = await self.send(feature("lat", lat=95.0))
        blast = await self.send(feature("blast", kind="explosion"))
        self.assertEqual(bad_lat.rejection.reason, RejectionReason.INVALID_COORDINATES)
        self.assertEqual(blast.rejection.reason, RejectionReason.NON_EARTHQUAKE_TYPE)
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_current"), 0)
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.quarantine_record"), 2)

    # ------------------------------------------------------------------ backfill
    async def test_backfill_evaluates_legacy_rows_once(self) -> None:
        await self.send(feature("legacy1", lon=-3.7, lat=40.42, place=" x "), geo=False)
        await self.send(feature("legacy2", lon=-30.0, lat=0.0), geo=False)
        await self.conn.execute("UPDATE live.event_current SET quality_flags = NULL")  # filas previas a la Fase 8
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_current WHERE country_status = 'pending'"), 2)

        done = await backfill_all(self.conn, GEO)
        self.assertEqual(done["live"], 2)
        self.assertEqual((await self.row("legacy1"))[:2], ("ESP", "assigned"))
        self.assertEqual((await self.row("legacy2"))[:2], (None, "unassigned"))
        self.assertEqual((await self.row("legacy1"))[2], ["fixed_place_trimmed"])
        self.assertEqual(await self.row("legacy1") is not None and (await self.row("legacy1"))[5], "x")

        self.assertEqual(await backfill_all(self.conn, GEO), {"demo": 0, "live": 0, "replay": 0, "historico": 0})  # idempotente

    # ------------------------------------------------------------------ API
    def api_get(self, path: str, **params):
        def call():
            with TestClient(create_app(PostgresQueries(DB.conninfo), default_mode="live")) as client:
                return client.get(path, params=params).json()

        return asyncio.to_thread(call)

    async def test_api_returns_country_name_for_assigned_and_null_for_maritime(self) -> None:
        await self.send(feature("madrid", lon=-3.7, lat=40.42))
        await self.send(feature("mar", lon=-30.0, lat=0.0))
        body = await self.api_get("/api/eventos", start="1970-01-01")
        props = {f["id"]: f["properties"] for f in body["features"]}
        self.assertEqual((props["madrid"]["country_id"], props["madrid"]["country_name"]), ("ESP", "España"))
        self.assertEqual((props["mar"]["country_id"], props["mar"]["country_name"]), (None, None))
        self.assertEqual(body["metadata"]["count"], 2)  # el evento marítimo sigue en la respuesta


@unittest.skipIf(not AVAILABLE or psycopg is None, "dependencias del backend no disponibles")
class HistoryLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        DB.truncate_events()
        self.conn = await psycopg.AsyncConnection.connect(DB.conninfo, autocommit=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    async def asyncTearDown(self) -> None:
        await self.conn.close()
        self.tmp.cleanup()

    def write(self, name, features) -> None:
        (self.dir / name).write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")

    def two_files(self) -> None:
        edge_v1 = feature("edge", lon=2.35, lat=48.85, updated=100 + NOW_MS - 10 * HOUR)
        edge_v2 = feature("edge", lon=2.35, lat=48.85, mag=6.0, updated=900 + NOW_MS - 10 * HOUR)
        self.write("2025-01.geojson", [
            feature("madrid", lon=-3.7, lat=40.42), feature("blast", kind="explosion"), feature("badlat", lat=95.0), edge_v1,
        ])
        self.write("2025-02.geojson", [edge_v1, edge_v2, feature("mar", lon=-30.0, lat=0.0)])

    async def scalar(self, sql, *params):
        return (await (await self.conn.execute(sql, params)).fetchone())[0]

    async def test_loads_into_historico_with_the_same_pipeline(self) -> None:
        self.two_files()
        report = await load_history(self.conn, self.dir, GEO)
        self.assertEqual(report["processed"], 7)
        self.assertEqual(report["decisions"], {"NEW": 3, "DUPLICATE": 1, "REVISION": 1})
        self.assertEqual(report["rejections"], {"non_earthquake_type": 1, "invalid_coordinates": 1})
        self.assertEqual(await self.scalar("SELECT count(*) FROM historico.event_current"), 3)  # madrid, edge, mar
        self.assertEqual(await self.scalar("SELECT count(*) FROM historico.event_message"), 4)  # + revisión de edge
        self.assertEqual(await self.scalar("SELECT mag FROM historico.event_current WHERE event_id = 'edge'"), 6.0)
        self.assertEqual(
            await self.scalar("SELECT country_id FROM historico.event_current WHERE event_id = 'madrid'"), "ESP"
        )
        self.assertEqual(
            await self.scalar("SELECT country_status FROM historico.event_current WHERE event_id = 'mar'"), "unassigned"
        )  # sin país asignado permanece en el análisis
        self.assertEqual(
            await self.scalar("SELECT DISTINCT mode || '/' || source FROM historico.event_message"), "historical/usgs-catalog"
        )

    async def test_rejections_keep_a_stable_reference_to_the_original_file_and_position(self) -> None:
        self.two_files()
        await load_history(self.conn, self.dir, GEO)
        rows = await (await self.conn.execute(
            "SELECT event_id, left(reason, 19), kafka_topic, kafka_offset FROM historico.quarantine_record ORDER BY kafka_offset"
        )).fetchall()
        self.assertEqual(rows, [("blast", "non_earthquake_type", "file:2025-01.geojson", 1),
                                ("badlat", "invalid_coordinates", "file:2025-01.geojson", 2)])

    async def test_loading_twice_changes_nothing(self) -> None:
        self.two_files()
        await load_history(self.conn, self.dir, GEO)
        before = [await self.scalar(f"SELECT count(*) FROM historico.{t}") for t in ("event_current", "event_message", "quarantine_record")]
        again = await load_history(self.conn, self.dir, GEO)
        after = [await self.scalar(f"SELECT count(*) FROM historico.{t}") for t in ("event_current", "event_message", "quarantine_record")]
        self.assertEqual(before, after)
        self.assertEqual(set(again["decisions"]) <= {"DUPLICATE", "STALE"}, True)  # nada NEW ni REVISION
        self.assertEqual(await self.scalar("SELECT mag FROM historico.event_current WHERE event_id = 'edge'"), 6.0)

    async def test_history_never_leaks_into_other_modes(self) -> None:
        self.two_files()
        await load_history(self.conn, self.dir, GEO)
        for schema in ("demo", "live", "replay"):
            self.assertEqual(await self.scalar(f"SELECT count(*) FROM {schema}.event_current"), 0, schema)
            self.assertEqual(await self.scalar(f"SELECT count(*) FROM {schema}.event_message"), 0, schema)

    async def test_missing_history_is_an_explicit_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            await load_history(self.conn, self.dir, GEO)

    async def test_a_live_message_sent_to_the_historical_path_is_rejected(self) -> None:
        result = await handle_record(
            self.conn, raw(feature("x")), KafkaRef("file:x.geojson", 0, 0), "historical", GEO
        )
        self.assertEqual(result.rejection.reason, RejectionReason.MODE_MISMATCH)
        self.assertEqual(await self.scalar("SELECT count(*) FROM historico.event_current"), 0)


@unittest.skipIf(not AVAILABLE or psycopg is None, "dependencias del backend no disponibles")
class DatabaseIsolationTests(unittest.IsolatedAsyncioTestCase):
    """El aislamiento por modo ya no depende solo del consumidor: la base de datos lo impone."""

    async def asyncSetUp(self) -> None:
        DB.truncate_events()
        self.conn = await psycopg.AsyncConnection.connect(DB.conninfo, autocommit=True)

    async def asyncTearDown(self) -> None:
        await self.conn.close()

    async def insert(self, schema: str, mode: str) -> None:
        replay_at = "now()" if mode == "replay" else "NULL"
        await self.conn.execute(
            f"INSERT INTO {schema}.event_message (event_id, updated_ms, source, mode, ingested_at, synthetic_flag, payload, replay_at) "
            f"VALUES ('x', 1, 's', '{mode}', now(), false, '{{}}', {replay_at})"
        )

    async def test_each_schema_accepts_only_its_own_mode(self) -> None:
        allowed = {"demo": "demo", "live": "live", "replay": "replay", "historico": "historical"}
        for schema, own in allowed.items():
            await self.insert(schema, own)  # el propio: admitido
            for other in ("demo", "live", "replay", "historical"):
                if other != own:
                    with self.assertRaises(psycopg.errors.CheckViolation, msg=f"{other} en {schema}"):
                        await self.insert(schema, other)

    async def test_unknown_mode_is_rejected_everywhere(self) -> None:
        for schema in ("demo", "live", "replay", "historico"):
            with self.assertRaises(psycopg.errors.CheckViolation):
                await self.insert(schema, "production")


if __name__ == "__main__":
    unittest.main()
