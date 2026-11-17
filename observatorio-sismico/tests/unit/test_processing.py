import json
import unittest

from backend.consumer.processing import Rejection, RejectionReason, parse_message
from backend.producer.producer import build_demo_message
from backend.producer.schema import EventMessage


def valid_dict() -> dict:
    return build_demo_message().to_dict()


def encode(value: object) -> bytes:
    return json.dumps(value).encode()


class ParseMessageTests(unittest.TestCase):
    def reason(self, raw: bytes) -> RejectionReason:
        result = parse_message(raw)
        self.assertIsInstance(result, Rejection)
        return result.reason

    def test_valid_message_is_parsed(self) -> None:
        result = parse_message(encode(valid_dict()))
        self.assertIsInstance(result, EventMessage)
        self.assertEqual(result.event_id, "demo-evt-001")

    def test_garbage_is_invalid_json(self) -> None:
        self.assertEqual(self.reason(b"{not json"), RejectionReason.INVALID_JSON)

    def test_non_utf8_is_invalid_json(self) -> None:
        self.assertEqual(self.reason(b"\xff\xfe\x00"), RejectionReason.INVALID_JSON)

    def test_nan_is_invalid_json(self) -> None:
        raw = encode(valid_dict()).replace(b"3.2", b"NaN")
        self.assertEqual(self.reason(raw), RejectionReason.INVALID_JSON)

    def test_missing_fields_is_schema_violation_and_keeps_identity(self) -> None:
        value = valid_dict()
        del value["ingested_at"]
        result = parse_message(encode(value))
        self.assertEqual(result.reason, RejectionReason.SCHEMA_VIOLATION)
        self.assertEqual(result.event_id, "demo-evt-001")
        self.assertEqual(result.source, "synthetic-demo")

    def test_json_array_is_schema_violation(self) -> None:
        self.assertEqual(self.reason(b"[1,2,3]"), RejectionReason.SCHEMA_VIOLATION)

    def test_latitude_out_of_range_is_invalid_coordinates(self) -> None:
        value = valid_dict()
        value["payload"]["geometry"]["coordinates"] = [-3.7, 95.0, 10]
        result = parse_message(encode(value))
        self.assertEqual(result.reason, RejectionReason.INVALID_COORDINATES)
        self.assertEqual(result.event_id, "demo-evt-001")

    def test_non_point_geometry_is_invalid_coordinates(self) -> None:
        value = valid_dict()
        value["payload"]["geometry"] = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
        self.assertEqual(self.reason(encode(value)), RejectionReason.INVALID_COORDINATES)

    def test_non_earthquake_type_is_rejected_with_type_in_detail(self) -> None:
        value = valid_dict()
        value["payload"]["properties"]["type"] = "quarry blast"
        result = parse_message(encode(value))
        self.assertEqual(result.reason, RejectionReason.NON_EARTHQUAKE_TYPE)
        self.assertIn("quarry blast", result.detail)
        self.assertEqual(result.event_id, "demo-evt-001")

    def test_missing_type_is_rejected(self) -> None:
        value = valid_dict()
        del value["payload"]["properties"]["type"]
        self.assertEqual(self.reason(encode(value)), RejectionReason.NON_EARTHQUAKE_TYPE)

    def test_null_magnitude_is_accepted(self) -> None:
        value = valid_dict()
        value["payload"]["properties"]["mag"] = None
        self.assertIsInstance(parse_message(encode(value)), EventMessage)

    def test_rejection_text_includes_reason_code(self) -> None:
        self.assertTrue(parse_message(b"x").text.startswith("invalid_json: "))


if __name__ == "__main__":
    unittest.main()
