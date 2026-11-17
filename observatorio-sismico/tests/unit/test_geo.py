"""Atribución de país contra el catálogo Natural Earth REAL (8.1, 8.6). Requiere shapely (contenedor)."""

import json
import os
import time
import unittest
from pathlib import Path

try:
    from backend.consumer.geo import UNASSIGNED, CountryIndex
except ImportError:  # el host no tiene shapely
    CountryIndex = None

CATALOG = next(
    path
    for path in (
        Path(os.environ["COUNTRIES_GEOJSON"]) if os.environ.get("COUNTRIES_GEOJSON") else None,
        Path(__file__).resolve().parents[2] / "frontend" / "public" / "datos" / "paises.geojson",
    )
    if path is not None and path.is_file()
)


def square(code: str, x0: float, y0: float, x1: float, y1: float) -> dict:
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return {"type": "Feature", "properties": {"ADM0_A3": code}, "geometry": {"type": "Polygon", "coordinates": [ring]}}


@unittest.skipIf(CountryIndex is None, "shapely no disponible")
class RealCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = CountryIndex.from_file(CATALOG)

    def country(self, lon: float, lat: float) -> str | None:
        return self.index.locate(lon, lat).country_id

    def test_catalog_loaded_with_all_entities(self) -> None:
        self.assertEqual(len(self.index), 177)

    def test_known_land_points(self) -> None:
        for name, lon, lat, expected in [
            ("Madrid", -3.70, 40.42, "ESP"), ("París", 2.35, 48.85, "FRA"), ("Tokio", 139.69, 35.68, "JPN"),
            ("Santiago de Chile", -70.65, -33.45, "CHL"), ("Anchorage (Alaska)", -149.9, 61.2, "USA"),
            ("Nairobi", 36.82, -1.29, "KEN"), ("Sídney", 151.2, -33.87, "AUS"),
        ]:
            self.assertEqual(self.country(lon, lat), expected, name)

    def test_ocean_points_are_unassigned_not_attributed_to_the_nearest_country(self) -> None:
        for name, lon, lat in [("Atlántico", -30, 0), ("Pacífico sur", -140, -30), ("Índico", 80, -30), ("Ártico", 0, 88)]:
            result = self.index.locate(lon, lat)
            self.assertIsNone(result.country_id, name)
            self.assertEqual(result.status, "unassigned", name)
            self.assertFalse(result.ambiguous)

    def test_coast_simplification_leaves_small_islands_unassigned(self) -> None:
        """Limitación documentada: con la escala 1:110M faltan islas menores. Se declara, no se esconde."""
        self.assertIsNone(self.country(-179.95, -16.85))  # Taveuni, Fiyi

    def test_point_on_a_shared_border_vertex_is_assigned_deterministically_and_flagged(self) -> None:
        result = self.index.locate(-1.901351, 43.422802)  # vértice compartido España-Francia
        self.assertEqual((result.country_id, result.status, result.ambiguous), ("ESP", "assigned", True))  # ESP < FRA
        self.assertEqual(result.flags, ("country_boundary_ambiguous",))
        for _ in range(5):
            self.assertEqual(self.index.locate(-1.901351, 43.422802), result)

    def test_unambiguous_points_carry_no_boundary_flag(self) -> None:
        self.assertEqual(self.index.locate(-3.70, 40.42).flags, ())
        self.assertEqual(UNASSIGNED.flags, ())

    def test_antimeridian_both_sides(self) -> None:
        self.assertEqual(self.country(179.2, -16.5), "FJI")  # Vanua Levu, lon > 0
        self.assertEqual(self.country(180.0, -16.5), "FJI")  # exactamente en +180
        self.assertEqual(self.country(-180.0, -16.5), "FJI")  # exactamente en -180
        self.assertEqual(self.country(180.0, 66.0), "RUS")
        self.assertEqual(self.country(-180.0, 66.0), "RUS")
        self.assertEqual(self.country(-171.0, 65.6), "RUS")  # Chukotka, lon < 0 (pieza al otro lado del antimeridiano)

    def test_geometries_with_self_intersections_were_repaired_and_still_resolve(self) -> None:
        self.assertEqual(sorted(self.index.repaired), ["SDN", "USA"])
        self.assertEqual(self.country(-149.9, 61.2), "USA")  # dentro de la geometría reparada
        self.assertEqual(self.country(32.5, 15.6), "SDN")  # Jartum

    def test_only_coordinates_matter_not_any_text(self) -> None:
        """`locate` solo recibe lon/lat: el campo `place` no puede influir en la atribución."""
        import inspect

        self.assertEqual(list(inspect.signature(self.index.locate).parameters), ["lon", "lat"])

    def test_resolves_fast_enough_for_a_full_year_of_events(self) -> None:
        points = [(x / 10.0, y / 10.0) for x in range(-1800, 1800, 90) for y in range(-800, 800, 40)]
        start = time.perf_counter()
        for lon, lat in points:
            self.index.locate(lon, lat)
        per_second = len(points) / (time.perf_counter() - start)
        self.assertGreater(per_second, 500, f"{per_second:.0f} puntos/s")  # 18.302 eventos en < 40 s, holgado


@unittest.skipIf(CountryIndex is None, "shapely no disponible")
class SyntheticRulesTests(unittest.TestCase):
    def test_edge_and_corner_points_are_inside(self) -> None:
        index = CountryIndex([square("AAA", 0, 0, 10, 10)])
        for lon, lat in [(0, 0), (10, 10), (5, 0), (0, 5), (10, 5), (5, 10)]:
            self.assertEqual(index.locate(lon, lat).country_id, "AAA", (lon, lat))
        for lon, lat in [(-0.0001, 5), (10.0001, 5), (5, 10.0001)]:
            self.assertIsNone(index.locate(lon, lat).country_id, (lon, lat))

    def test_shared_edge_picks_lowest_adm0_a3_regardless_of_catalog_order(self) -> None:
        a, b = square("ZZZ", 0, 0, 5, 10), square("BBB", 5, 0, 10, 10)
        for features in ([a, b], [b, a]):
            result = CountryIndex(features).locate(5, 5)
            self.assertEqual((result.country_id, result.ambiguous), ("BBB", True))
        self.assertFalse(CountryIndex([a, b]).locate(2, 5).ambiguous)

    def test_overlapping_polygons_are_ambiguous_too(self) -> None:
        result = CountryIndex([square("CCC", 0, 0, 10, 10), square("AAA", 5, 5, 15, 15)]).locate(7, 7)
        self.assertEqual((result.country_id, result.ambiguous), ("AAA", True))

    def test_invalid_bowtie_geometry_is_repaired_instead_of_failing(self) -> None:
        bowtie = {"type": "Feature", "properties": {"ADM0_A3": "BOW"}, "geometry": {
            "type": "Polygon", "coordinates": [[[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]]]}}
        index = CountryIndex([bowtie])
        self.assertEqual(index.repaired, ["BOW"])
        self.assertEqual(index.locate(1, 5).country_id, "BOW")  # triángulo izquierdo del lazo

    def test_duplicate_adm0_a3_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "not unique"):
            CountryIndex([square("AAA", 0, 0, 1, 1), square("AAA", 2, 2, 3, 3)])

    def test_multipolygon_countries(self) -> None:
        islands = {"type": "Feature", "properties": {"ADM0_A3": "ISL"}, "geometry": {
            "type": "MultiPolygon", "coordinates": [
                [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]], [[[20, 20], [21, 20], [21, 21], [20, 21], [20, 20]]]]}}
        index = CountryIndex([islands])
        self.assertEqual((index.locate(0.5, 0.5).country_id, index.locate(20.5, 20.5).country_id), ("ISL", "ISL"))
        self.assertIsNone(index.locate(10, 10).country_id)

    def test_empty_catalog_assigns_nothing(self) -> None:
        self.assertIsNone(CountryIndex([]).locate(0, 0).country_id)


if __name__ == "__main__":
    unittest.main()
