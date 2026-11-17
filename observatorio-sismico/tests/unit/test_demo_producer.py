import asyncio
import unittest
from datetime import datetime, timezone

from backend.producer.producer import (
    DEMO_EVENT_ID,
    DEMO_UPDATED_MS,
    build_demo_message,
    publish,
    run_demo,
)
from backend.producer.schema import EventMessage, IngestionMode


class FakeSender:
    def __init__(self, fail_on: int | None = None) -> None:
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.fail_on = fail_on

    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> None:
        if self.fail_on is not None and len(self.sent) == self.fail_on:
            raise ConnectionError("no ack")
        self.sent.append((topic, value, key))


class DemoMessageTests(unittest.TestCase):
    def test_demo_message_is_synthetic_and_stable(self) -> None:
        a = build_demo_message(datetime(2026, 1, 1, tzinfo=timezone.utc))
        b = build_demo_message(datetime(2027, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(a.event_id, DEMO_EVENT_ID)
        self.assertEqual(a.mode, IngestionMode.DEMO)
        self.assertTrue(a.synthetic_flag)
        self.assertEqual(a.source, "synthetic-demo")
        self.assertEqual(a.updated_ms, b.updated_ms)  # misma versión aunque cambie ingested_at
        self.assertEqual(a.payload, b.payload)

    def test_revision_changes_only_version_and_magnitude(self) -> None:
        rev = build_demo_message(updated_ms=DEMO_UPDATED_MS + 1000, mag=3.5)
        self.assertEqual(rev.updated_ms, DEMO_UPDATED_MS + 1000)
        self.assertEqual(rev.payload["properties"]["mag"], 3.5)


class PublishTests(unittest.TestCase):
    def test_publish_uses_event_id_as_key_and_valid_json(self) -> None:
        sender = FakeSender()
        asyncio.run(publish(sender, "sismos.demo", build_demo_message()))
        topic, value, key = sender.sent[0]
        self.assertEqual(topic, "sismos.demo")
        self.assertEqual(key, b"demo-evt-001")
        restored = EventMessage.from_json(value.decode())
        self.assertEqual(restored.event_id, DEMO_EVENT_ID)

    def test_duplicates_resend_identical_version(self) -> None:
        sender = FakeSender()
        total = asyncio.run(run_demo(sender, "sismos.demo", duplicates=2))
        self.assertEqual(total, 3)
        versions = {EventMessage.from_json(v.decode()).updated_ms for _, v, _ in sender.sent}
        self.assertEqual(versions, {DEMO_UPDATED_MS})

    def test_missing_ack_propagates(self) -> None:
        sender = FakeSender(fail_on=0)
        with self.assertRaises(ConnectionError):
            asyncio.run(run_demo(sender, "sismos.demo", duplicates=0))


if __name__ == "__main__":
    unittest.main()
