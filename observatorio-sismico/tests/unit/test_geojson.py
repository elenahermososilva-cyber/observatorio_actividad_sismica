import json
import unittest

from backend.api.geojson import CollectionMeta, build_collection, build_feature, finite_or_none
from backend.producer.producer import build_demo_message


def payload() -> dict:
    return build_demo_message().payload


class FeatureTests(unittest.TestCase):
    def test_demo_feature_matches_contract_shape(self) -> None:
        feature = build_feature("demo-evt-001", payload())
        self.assertEqual(feature["type"], "Feature")
        self.assertEqual(feature["id"], "demo-evt-001")
        self.assertEqual(feature["geometry"], {"type": "Point", "coordinates": [-3.7, 40.4, 12]})
        props = feature["properties"]
        self.assertEqual(
            set(props), {"mag", "magType", "place", "time", "updated", "country_id", "country_name"}
        )
        self.assertEqual(props["mag"], 3.2)
        self.assertIsNone(props["country_id"])

    def test_null_magnitude_and_depth_stay_null(self) -> None:
        p = payload()
        p["properties"]["mag"] = None
        p["geometry"]["coordinates"] = [-3.7, 40.4]
        feature = build_feature("x", p)
        self.assertIsNone(feature["properties"]["mag"])
        self.assertEqual(feature["geometry"]["coordinates"], [-3.7, 40.4, None])

    def test_non_finite_values_become_null_and_serialize_without_nan(self) -> None:
        p = payload()
        p["properties"]["mag"] = float("nan")
        p["geometry"]["coordinates"] = [-3.7, 40.4, float("inf")]
        feature = build_feature("x", p)
        json.dumps(feature, allow_nan=False)  # no lanza
        self.assertIsNone(feature["properties"]["mag"])
        self.assertIsNone(feature["geometry"]["coordinates"][2])

    def test_invalid_geometry_returns_none_instead_of_inventing_a_point(self) -> None:
        for geometry in (
            None,
            {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            {"type": "Point", "coordinates": [1]},
            {"type": "Point", "coordinates": [float("nan"), 1]},
            {"type": "Point", "coordinates": ["a", "b"]},
        ):
            p = payload()
            p["geometry"] = geometry
            self.assertIsNone(build_feature("x", p), geometry)

    def test_finite_or_none(self) -> None:
        self.assertEqual(finite_or_none(0), 0)
        self.assertIsNone(finite_or_none(True))
        self.assertIsNone(finite_or_none("3"))
        self.assertIsNone(finite_or_none(float("-inf")))


class CollectionTests(unittest.TestCase):
    def test_metadata_fields_and_count(self) -> None:
        meta = CollectionMeta(10, None, "live", False, 1, None, 0)
        empty = build_collection([], meta)
        self.assertEqual(empty["type"], "FeatureCollection")
        self.assertEqual(empty["features"], [])
        for key in ("generated", "last_ingestion", "mode", "count", "truncated"):
            self.assertIn(key, empty["metadata"])
        self.assertEqual(empty["metadata"]["count"], 0)
        self.assertIsNone(empty["metadata"]["last_ingestion"])


if __name__ == "__main__":
    unittest.main()
