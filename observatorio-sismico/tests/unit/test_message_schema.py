import unittest
from datetime import datetime, timezone

from backend.producer.schema import EventMessage, IngestionMode


def make_demo_message() -> EventMessage:
    updated_ms = 1_800_000_000_000
    return EventMessage(
        event_id="demo-evt-001",
        source="synthetic-demo",
        mode=IngestionMode.DEMO,
        ingested_at=datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc),
        updated_ms=updated_ms,
        payload={
            "type": "Feature",
            "id": "demo-evt-001",
            "geometry": {
                "type": "Point",
                "coordinates": [-3.7, 40.4, 12],
            },
            "properties": {
                "type": "earthquake",
                "mag": 3.2,
                "magType": "ml",
                "place": "Evento de prueba sintético",
                "time": updated_ms,
                "updated": updated_ms,
            },
        },
        synthetic_flag=True,
    )


class EventMessageTests(unittest.TestCase):
    def test_round_trip_json_preserves_contract_fields(self) -> None:
        original = make_demo_message()

        restored = EventMessage.from_json(original.to_json())

        self.assertEqual(restored, original)
        self.assertEqual(restored.to_dict()["updated"], original.updated_ms)
        self.assertEqual(restored.to_dict()["mode"], "demo")
        self.assertTrue(restored.to_dict()["synthetic_flag"])

    def test_serializes_ingestion_time_as_utc(self) -> None:
        serialized = make_demo_message().to_dict()

        self.assertEqual(serialized["ingested_at"], "2026-11-16T12:00:00Z")

    def test_rejects_demo_message_not_marked_synthetic(self) -> None:
        message = make_demo_message().to_dict()
        message["synthetic_flag"] = False

        with self.assertRaisesRegex(ValueError, "marked synthetic"):
            EventMessage.from_dict(message)

    def test_rejects_live_message_marked_synthetic(self) -> None:
        message = make_demo_message().to_dict()
        message["mode"] = "live"
        message["source"] = "usgs"
        message["synthetic_flag"] = True

        with self.assertRaisesRegex(ValueError, "cannot be marked synthetic"):
            EventMessage.from_dict(message)

    def test_rejects_payload_id_mismatch(self) -> None:
        message = make_demo_message().to_dict()
        message["payload"]["id"] = "another-event"

        with self.assertRaisesRegex(ValueError, "match event_id"):
            EventMessage.from_dict(message)

    def test_rejects_timestamp_version_mismatch(self) -> None:
        message = make_demo_message().to_dict()
        message["updated"] += 1

        with self.assertRaisesRegex(ValueError, "must match"):
            EventMessage.from_dict(message)

    def test_rejects_invalid_coordinates(self) -> None:
        message = make_demo_message().to_dict()
        message["payload"]["geometry"]["coordinates"] = [-181, 40]

        with self.assertRaisesRegex(ValueError, "longitude"):
            EventMessage.from_dict(message)

    def test_rejects_more_than_three_coordinates(self) -> None:
        message = make_demo_message().to_dict()
        message["payload"]["geometry"]["coordinates"] = [-3.7, 40.4, 12, 1]

        with self.assertRaisesRegex(ValueError, "longitude and latitude"):
            EventMessage.from_dict(message)

    def test_allows_unknown_depth_and_magnitude(self) -> None:
        message = make_demo_message().to_dict()
        message["payload"]["geometry"]["coordinates"] = [-3.7, 40.4, None]
        message["payload"]["properties"]["mag"] = None

        restored = EventMessage.from_dict(message)

        self.assertIsNone(restored.payload["properties"]["mag"])
        self.assertIsNone(restored.payload["geometry"]["coordinates"][2])

    def test_rejects_non_finite_magnitude(self) -> None:
        message = make_demo_message().to_dict()
        message["payload"]["properties"]["mag"] = float("nan")

        with self.assertRaisesRegex(ValueError, "finite number or null"):
            EventMessage.from_dict(message)

    def test_rejects_invalid_event_timestamp(self) -> None:
        message = make_demo_message().to_dict()
        message["payload"]["properties"]["time"] = -1

        with self.assertRaisesRegex(ValueError, "properties.time"):
            EventMessage.from_dict(message)

    def test_rejects_non_utc_ingestion_time(self) -> None:
        message = make_demo_message().to_dict()
        message["ingested_at"] = "2026-11-16T12:00:00+01:00"

        with self.assertRaisesRegex(ValueError, "UTC"):
            EventMessage.from_dict(message)

    def test_rejects_invalid_json(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            EventMessage.from_json("{")

    def test_rejects_non_finite_json_numbers(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            EventMessage.from_json('{"value": NaN}')

    def test_rejects_missing_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required fields"):
            EventMessage.from_dict({"event_id": "demo-evt-001"})


if __name__ == "__main__":
    unittest.main()
