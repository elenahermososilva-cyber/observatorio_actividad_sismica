"""Reglas de calidad (8.2): una prueba por regla. Puras; corren también en el host."""

import unittest
from datetime import datetime, timezone

from backend.consumer.quality import FLAG_CODES, assess
from backend.db.columns import EventColumns

INGESTED = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
INGESTED_MS = int(INGESTED.timestamp() * 1000)
HOUR = 3_600_000


def columns(**overrides) -> EventColumns:
    base = dict(
        time_ms=INGESTED_MS - HOUR, mag=4.5, mag_type="mww", depth_km=10.0, lon=-3.7, lat=40.4,
        place="5 km N of Madrid, Spain", event_type="earthquake", ingested_at=INGESTED,
    )
    base.update(overrides)
    return EventColumns(**base)


def flags(updated_ms=INGESTED_MS - HOUR + 1, **overrides) -> tuple[str, ...]:
    return assess(columns(**overrides), updated_ms).flags


class CleanRecordTests(unittest.TestCase):
    def test_clean_record_has_no_flags_and_is_unchanged(self) -> None:
        original = columns()
        result = assess(original, original.time_ms + 1)
        self.assertEqual(result.flags, ())
        self.assertEqual(result.columns, original)


class GapsAreKeptNotFilledTests(unittest.TestCase):
    def test_missing_magnitude_stays_null_and_is_flagged(self) -> None:
        result = assess(columns(mag=None, mag_type=None), INGESTED_MS)
        self.assertIsNone(result.columns.mag)  # jamás 0
        self.assertEqual(result.flags, ("gap_mag_missing",))  # sin magnitud no se exige su tipo

    def test_magnitude_without_type_is_flagged(self) -> None:
        self.assertEqual(flags(mag_type=None), ("gap_mag_type_missing",))
        self.assertEqual(flags(mag_type="   "), ("gap_mag_type_missing",))

    def test_missing_depth_stays_null_and_is_flagged(self) -> None:
        result = assess(columns(depth_km=None), INGESTED_MS)
        self.assertIsNone(result.columns.depth_km)
        self.assertEqual(result.flags, ("gap_depth_missing",))

    def test_missing_place_is_flagged(self) -> None:
        self.assertEqual(flags(place=None), ("gap_place_missing",))


class AnomaliesAreKeptTests(unittest.TestCase):
    def test_negative_magnitude_is_kept_and_flagged_not_rejected(self) -> None:
        result = assess(columns(mag=-0.4), INGESTED_MS)
        self.assertEqual(result.columns.mag, -0.4)
        self.assertEqual(result.flags, ("anomaly_mag_negative",))

    def test_negative_depth_is_kept_and_flagged(self) -> None:
        result = assess(columns(depth_km=-1.2), INGESTED_MS)
        self.assertEqual(result.columns.depth_km, -1.2)
        self.assertEqual(result.flags, ("anomaly_depth_negative",))

    def test_magnitude_outside_plausible_range(self) -> None:
        self.assertIn("anomaly_mag_out_of_range", flags(mag=10.4))
        self.assertIn("anomaly_mag_out_of_range", flags(mag=-3.0))
        self.assertNotIn("anomaly_mag_out_of_range", flags(mag=-2.0))  # límites incluidos
        self.assertNotIn("anomaly_mag_out_of_range", flags(mag=10.0))
        self.assertIn("anomaly_mag_negative", flags(mag=-3.0))  # además es negativa

    def test_very_deep_event(self) -> None:
        self.assertIn("anomaly_depth_very_large", flags(depth_km=801.0))
        self.assertNotIn("anomaly_depth_very_large", flags(depth_km=700.0))

    def test_event_in_the_future(self) -> None:
        self.assertIn("anomaly_time_in_future", flags(time_ms=INGESTED_MS + 10 * 60 * 1000))
        self.assertNotIn("anomaly_time_in_future", flags(time_ms=INGESTED_MS + 60 * 1000))  # dentro de la tolerancia

    def test_update_before_occurrence_is_inconsistent(self) -> None:
        self.assertIn("anomaly_updated_before_time", flags(updated_ms=INGESTED_MS - 2 * HOUR))
        self.assertNotIn("anomaly_updated_before_time", flags(updated_ms=INGESTED_MS - HOUR))  # igual: coherente

    def test_zero_is_a_real_value_not_missing(self) -> None:
        self.assertEqual(flags(mag=0.0, depth_km=0.0), ())


class TransformationsAreRecordedTests(unittest.TestCase):
    def test_place_is_trimmed_and_recorded(self) -> None:
        result = assess(columns(place="  Madrid, Spain \n"), INGESTED_MS)
        self.assertEqual(result.columns.place, "Madrid, Spain")
        self.assertEqual(result.flags, ("fixed_place_trimmed",))

    def test_blank_place_becomes_null_and_is_also_a_gap(self) -> None:
        result = assess(columns(place="   "), INGESTED_MS)
        self.assertIsNone(result.columns.place)
        self.assertEqual(result.flags, ("fixed_place_blank_to_null", "gap_place_missing"))

    def test_mag_type_is_lowercased_and_recorded(self) -> None:
        result = assess(columns(mag_type="Mww"), INGESTED_MS)
        self.assertEqual(result.columns.mag_type, "mww")
        self.assertEqual(result.flags, ("fixed_mag_type_lowercased",))

    def test_untouched_values_leave_no_fix_flag(self) -> None:
        self.assertEqual(flags(place="Madrid", mag_type="ml"), ())

    def test_assessment_never_mutates_the_input(self) -> None:
        original = columns(place=" x ", mag_type="ML")
        assess(original, INGESTED_MS)
        self.assertEqual((original.place, original.mag_type), (" x ", "ML"))


class CatalogOfCodesTests(unittest.TestCase):
    def test_every_emitted_code_is_documented(self) -> None:
        emitted = set()
        for case in (
            dict(mag=None, mag_type=None, depth_km=None, place=None), dict(mag=-5.0, depth_km=-1.0),
            dict(mag=11.0, depth_km=900.0), dict(place=" x ", mag_type="ML"), dict(place=" ", mag_type=None),
            dict(time_ms=INGESTED_MS + HOUR),
        ):
            emitted.update(assess(columns(**case), 0).flags)
        self.assertTrue(emitted <= set(FLAG_CODES), emitted - set(FLAG_CODES))
        self.assertTrue(all(code.split("_")[0] in {"gap", "anomaly", "fixed", "country"} for code in FLAG_CODES))


if __name__ == "__main__":
    unittest.main()
