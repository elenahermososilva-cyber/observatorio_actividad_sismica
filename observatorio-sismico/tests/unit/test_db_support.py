import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.db.columns import extract_columns
from backend.db.countries import CatalogError, fingerprint, read_catalog
from backend.db.migrate import PER_SCHEMA_MARKER, discover_migrations
from backend.db.modes import EVENT_MODES, MODE_SCHEMAS, schema_for_mode
from backend.producer.producer import build_demo_message

# En el host el catálogo está en frontend/public/datos; en la imagen, en /app/data (COUNTRIES_GEOJSON).
CATALOG = next(
    path
    for path in (
        Path(os.environ["COUNTRIES_GEOJSON"]) if os.environ.get("COUNTRIES_GEOJSON") else None,
        Path(__file__).resolve().parents[2] / "frontend" / "public" / "datos" / "paises.geojson",
    )
    if path is not None and path.is_file()
)
INGESTED = datetime(2026, 11, 17, tzinfo=timezone.utc)


def feature(code: str | None, geometry: str = "Polygon") -> dict:
    props = {"NAME_ES": "N", "ADMIN": "A", "CONTINENT": "C", "SUBREGION": "S"}
    if code is not None:
        props["ADM0_A3"] = code
    return {"type": "Feature", "properties": props, "geometry": {"type": geometry, "coordinates": []}}


def write_catalog(directory: str, features: list[dict]) -> Path:
    path = Path(directory) / "c.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    return path


class ModesTests(unittest.TestCase):
    def test_event_modes_are_a_subset_of_schemas(self) -> None:
        self.assertEqual(set(MODE_SCHEMAS), {"demo", "live", "replay", "historico"})
        self.assertTrue(set(EVENT_MODES) <= set(MODE_SCHEMAS))
        self.assertNotIn("historico", EVENT_MODES)  # el histórico no llega por Kafka ni se consulta como modo
        self.assertNotIn("historical", EVENT_MODES)
        self.assertEqual(schema_for_mode("historical"), "historico")  # el modo `historical` escribe en `historico`

    def test_schema_for_mode_rejects_anything_outside_the_closed_list(self) -> None:
        self.assertEqual(schema_for_mode("live"), "live")
        for bad in ("public", "ingest", "historico", "", 'demo"; DROP', "DEMO"):
            with self.assertRaises(ValueError, msg=bad):
                schema_for_mode(bad)


class ExtractColumnsTests(unittest.TestCase):
    def test_demo_payload(self) -> None:
        c = extract_columns(build_demo_message().payload, INGESTED)
        self.assertEqual((c.time_ms, c.mag, c.mag_type, c.depth_km), (1_793_109_600_000, 3.2, "ml", 12.0))
        self.assertEqual((c.lon, c.lat, c.event_type, c.ingested_at), (-3.7, 40.4, "earthquake", INGESTED))

    def test_missing_values_stay_none_never_zero(self) -> None:
        payload = build_demo_message(mag=None).payload
        payload["geometry"]["coordinates"] = [-3.7, 40.4]
        del payload["properties"]["magType"]
        c = extract_columns(payload, INGESTED)
        self.assertIsNone(c.mag)
        self.assertIsNone(c.depth_km)
        self.assertIsNone(c.mag_type)

    def test_negative_magnitude_and_depth_are_preserved_not_rejected(self) -> None:
        payload = build_demo_message(mag=-0.4).payload
        payload["geometry"]["coordinates"] = [-3.7, 40.4, -1.2]
        c = extract_columns(payload, INGESTED)
        self.assertEqual((c.mag, c.depth_km), (-0.4, -1.2))

    def test_non_text_place_becomes_none(self) -> None:
        payload = build_demo_message().payload
        payload["properties"]["place"] = 123
        self.assertIsNone(extract_columns(payload, INGESTED).place)


class CatalogTests(unittest.TestCase):
    def test_real_catalog_has_177_unique_ids_and_published_fingerprint(self) -> None:
        catalog = read_catalog(CATALOG)
        self.assertEqual(len(catalog.countries), 177)
        self.assertEqual(len({c.country_id for c in catalog.countries}), 177)
        self.assertEqual(catalog.sha256, "6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f")

    def test_fingerprint_ignores_crlf_line_endings(self) -> None:
        self.assertEqual(fingerprint(b'{"a":1}\n{"b":2}\n'), fingerprint(b'{"a":1}\r\n{"b":2}\r\n'))
        self.assertNotEqual(fingerprint(b"a\n"), fingerprint(b"b\n"))

    def test_duplicate_adm0_a3_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(CatalogError, "not unique"):
                read_catalog(write_catalog(tmp, [feature("AAA"), feature("BBB"), feature("AAA")]))

    def test_missing_id_wrong_geometry_and_invalid_json_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(CatalogError, "no ADM0_A3"):
                read_catalog(write_catalog(tmp, [feature(None)]))
            with self.assertRaisesRegex(CatalogError, "Polygon or MultiPolygon"):
                read_catalog(write_catalog(tmp, [feature("AAA", "Point")]))
            bad = Path(tmp) / "bad.geojson"
            bad.write_text("{nope", encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "not valid JSON"):
                read_catalog(bad)
            with self.assertRaisesRegex(CatalogError, "non-empty"):
                read_catalog(write_catalog(tmp, []))


class MigrationFilesTests(unittest.TestCase):
    def test_per_schema_marker_detection(self) -> None:
        by_version = {m.version: m for m in discover_migrations()}
        self.assertFalse(by_version[1].per_schema)  # schema.sql: public, inmutable
        self.assertFalse(by_version[2].per_schema)  # esquemas, movimiento de tablas, ref
        for version in (3, 4, 5, 7, 8):
            self.assertTrue(by_version[version].per_schema, version)
            self.assertTrue(by_version[version].sql.startswith(PER_SCHEMA_MARKER))
        self.assertFalse(by_version[6].per_schema)  # ingest: estado del productor, un solo esquema
        self.assertFalse(by_version[9].per_schema)  # restricciones distintas por esquema (modo ↔ esquema)

    def test_migrations_are_consecutive_and_cover_the_phase(self) -> None:
        self.assertEqual([m.version for m in discover_migrations()], [1, 2, 3, 4, 5, 6, 7, 8, 9])


if __name__ == "__main__":
    unittest.main()
