"""El migrador real sobre bases temporales: idempotencia, aislamiento por modo, migración de datos previos y dim_country.

    docker compose run --rm --no-deps -v ./tests:/app/tests api \
        python -m unittest discover -s tests/integration -t . -p "test_migrations.py"
"""

import json
import unittest
from pathlib import Path

try:
    import psycopg

    from backend.db.migrate import discover_migrations, run_migrations
    from backend.db.modes import MODE_SCHEMAS
except ImportError:
    psycopg = None

from tests.integration.dbutil import AVAILABLE, COUNTRIES, TempDatabase


def columns(conn, schema: str, table: str) -> list[tuple]:
    return conn.execute(
        "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (schema, table),
    ).fetchall()


def indexes(conn, schema: str) -> list[tuple]:
    return conn.execute(
        "SELECT tablename, indexname, regexp_replace(indexdef, 'ON \\S+\\.', 'ON ') FROM pg_indexes "
        "WHERE schemaname = %s ORDER BY indexname",
        (schema,),
    ).fetchall()


@unittest.skipIf(not AVAILABLE or psycopg is None, "dependencias del backend no disponibles")
class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = TempDatabase()
        self.addCleanup(self.db.drop)

    def connect(self):
        return psycopg.connect(self.db.conninfo, autocommit=True)

    def test_second_run_applies_nothing(self) -> None:
        self.db.create()
        self.assertEqual(run_migrations(self.db.conninfo), [])
        with self.connect() as conn:
            versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY 1")]
        self.assertEqual(versions, [m.version for m in discover_migrations()])

    def test_every_mode_schema_has_identical_tables_columns_and_indexes(self) -> None:
        self.db.create()
        with self.connect() as conn:
            for table in ("event_message", "event_current", "quarantine_record"):
                reference = columns(conn, "demo", table)
                self.assertTrue(reference, table)
                for schema in MODE_SCHEMAS:
                    self.assertEqual(columns(conn, schema, table), reference, f"{schema}.{table}")
            reference_indexes = indexes(conn, "demo")
            self.assertGreaterEqual(len(reference_indexes), 8)
            for schema in MODE_SCHEMAS:
                self.assertEqual(indexes(conn, schema), reference_indexes, schema)

    def test_event_current_has_denormalized_columns_and_indexes(self) -> None:
        self.db.create()
        with self.connect() as conn:
            names = {c[0] for c in columns(conn, "live", "event_current")}
            self.assertTrue(
                {"time_ms", "mag", "mag_type", "depth_km", "lon", "lat", "place", "event_type",
                 "ingested_at", "country_id", "country_status"} <= names
            )
            idx = {i[1] for i in indexes(conn, "live")}
            self.assertTrue(
                {"ix_event_current_time", "ix_event_current_country_time", "ix_event_current_mag",
                 "ix_event_current_status"} <= idx
            )

    def test_public_schema_keeps_only_migration_bookkeeping(self) -> None:
        self.db.create()
        with self.connect() as conn:
            tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
        self.assertEqual(tables, {"schema_migrations"})

    def test_ingest_state_tables_exist_and_enforce_their_rules(self) -> None:
        self.db.create()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO ingest.extraction_log (mode, source_url, started_at, ok, record_count) "
                "VALUES ('live', 'https://example.test', now(), true, 3)"
            )
            with self.assertRaises(psycopg.errors.CheckViolation):  # un fallo sin motivo no es válido
                conn.execute(
                    "INSERT INTO ingest.extraction_log (mode, source_url, started_at, ok) "
                    "VALUES ('live', 'https://example.test', now(), false)"
                )
            conn.execute("INSERT INTO ingest.published_version (mode, event_id, updated_ms) VALUES ('live', 'a', 1)")
            with self.assertRaises(psycopg.errors.UniqueViolation):
                conn.execute("INSERT INTO ingest.published_version (mode, event_id, updated_ms) VALUES ('live', 'a', 1)")
            # el mismo (event_id, updated) en otro modo es otra publicación
            conn.execute("INSERT INTO ingest.published_version (mode, event_id, updated_ms) VALUES ('replay', 'a', 1)")

    def test_dim_country_loaded_with_unique_ids_and_documented_fingerprint(self) -> None:
        self.db.create()
        with self.connect() as conn:
            total, distinct, shas = conn.execute(
                "SELECT count(*), count(DISTINCT country_id), array_agg(DISTINCT source_sha256) FROM ref.dim_country"
            ).fetchone()
            spain = conn.execute("SELECT name_es, admin, continent FROM ref.dim_country WHERE country_id = 'ESP'").fetchone()
        self.assertEqual((total, distinct), (177, 177))
        # huella publicada en docs/curso/FUENTES-Y-LICENCIAS.md (independiente de CRLF/LF del equipo)
        self.assertEqual(shas, ["6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f"])
        self.assertEqual(spain, ("España", "Spain", "Europe"))

    def test_country_load_is_idempotent(self) -> None:
        from backend.db.migrate import load_countries

        self.db.create()
        self.assertEqual(load_countries(self.db.conninfo, COUNTRIES), (177, 0))  # sin cambios: 0 filas tocadas

    def test_existing_public_data_moves_to_demo_and_gets_backfilled_columns(self) -> None:
        """Una base con la migración 001 y datos reales (estado de la entrega vertical) sube sin perder nada."""
        self.db.create(load_catalog=False, upto=1)
        payload = {
            "type": "Feature", "id": "legacy-1",
            "geometry": {"type": "Point", "coordinates": [-3.7, 40.4, 12]},
            "properties": {"type": "earthquake", "mag": 3.2, "magType": "ml", "place": "Antiguo",
                           "time": 1_793_109_600_000, "updated": 1_793_110_000_000},
        }
        with self.connect() as conn:
            message_id = conn.execute(
                "INSERT INTO event_message (event_id, updated_ms, source, mode, ingested_at, synthetic_flag, payload) "
                "VALUES ('legacy-1', 1793110000000, 'synthetic-demo', 'demo', now(), true, %s) RETURNING message_id",
                (json.dumps(payload),),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO event_current (event_id, message_id, current_version_ms, last_seen_at) "
                "VALUES ('legacy-1', %s, 1793110000000, now())", (message_id,),
            )
            conn.execute(
                "INSERT INTO quarantine_record (reason, original_payload) VALUES ('invalid_json: x', '{broken')"
            )
        run_migrations(self.db.conninfo)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT event_id, time_ms, mag, mag_type, depth_km, lon, lat, place, event_type, country_status "
                "FROM demo.event_current"
            ).fetchone()
            self.assertEqual(
                row, ("legacy-1", 1_793_109_600_000, 3.2, "ml", 12.0, -3.7, 40.4, "Antiguo", "earthquake", "pending")
            )
            self.assertEqual(conn.execute("SELECT count(*) FROM demo.event_message").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM demo.quarantine_record").fetchone()[0], 1)
            for schema in ("live", "replay", "historico"):
                self.assertEqual(conn.execute(f'SELECT count(*) FROM "{schema}".event_current').fetchone()[0], 0)

    def test_edited_migration_is_detected(self) -> None:
        self.db.create()
        with self.connect() as conn:
            conn.execute("UPDATE schema_migrations SET checksum = 'tampered' WHERE version = 4")
        with self.assertRaisesRegex(RuntimeError, "modified after being applied"):
            run_migrations(self.db.conninfo)

    def test_migration_files_use_only_expected_per_schema_marker(self) -> None:
        for migration in discover_migrations():
            text = Path(migration.path).read_text(encoding="utf-8")
            if migration.per_schema:
                self.assertTrue(text.startswith("-- @per-schema"), migration.path.name)
                self.assertNotIn("public.", text, "una migración por esquema no debe calificar con public")


if __name__ == "__main__":
    unittest.main()
