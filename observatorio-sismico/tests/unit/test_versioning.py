import unittest

from backend.consumer.versioning import (
    EventVersion,
    VersionDecision,
    classify_version,
)


class ClassifyVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.initial = EventVersion("usgs-evt-1", 1_000)

    def test_event_without_current_version_is_new(self) -> None:
        incoming = EventVersion("usgs-evt-1", 1_000)

        self.assertEqual(classify_version(incoming, None), VersionDecision.NEW)

    def test_same_version_is_duplicate(self) -> None:
        incoming = EventVersion("usgs-evt-1", 1_000)

        self.assertEqual(
            classify_version(incoming, self.initial),
            VersionDecision.DUPLICATE,
        )

    def test_later_version_is_revision(self) -> None:
        incoming = EventVersion("usgs-evt-1", 1_200)

        self.assertEqual(
            classify_version(incoming, self.initial),
            VersionDecision.REVISION,
        )

    def test_older_version_is_stale(self) -> None:
        incoming = EventVersion("usgs-evt-1", 800)

        self.assertEqual(
            classify_version(incoming, self.initial),
            VersionDecision.STALE,
        )

    def test_replay_sequence_keeps_the_latest_version(self) -> None:
        versions = [
            EventVersion("usgs-evt-1", 1_000),
            EventVersion("usgs-evt-1", 1_000),
            EventVersion("usgs-evt-1", 1_200),
            EventVersion("usgs-evt-1", 1_000),
        ]
        current = None
        decisions = []

        for incoming in versions:
            decision = classify_version(incoming, current)
            decisions.append(decision)
            if decision in (VersionDecision.NEW, VersionDecision.REVISION):
                current = incoming

        self.assertEqual(
            decisions,
            [
                VersionDecision.NEW,
                VersionDecision.DUPLICATE,
                VersionDecision.REVISION,
                VersionDecision.STALE,
            ],
        )
        self.assertEqual(current, EventVersion("usgs-evt-1", 1_200))

    def test_versions_for_different_events_cannot_be_compared(self) -> None:
        incoming = EventVersion("usgs-evt-2", 1_200)

        with self.assertRaises(ValueError):
            classify_version(incoming, self.initial)


class EventVersionValidationTests(unittest.TestCase):
    def test_rejects_empty_event_id(self) -> None:
        with self.assertRaises(ValueError):
            EventVersion("  ", 1_000)

    def test_rejects_non_string_event_id(self) -> None:
        with self.assertRaises(TypeError):
            EventVersion(None, 1_000)  # type: ignore[arg-type]

    def test_rejects_non_integer_timestamp(self) -> None:
        with self.assertRaises(TypeError):
            EventVersion("usgs-evt-1", 1_000.0)  # type: ignore[arg-type]

    def test_rejects_boolean_timestamp(self) -> None:
        with self.assertRaises(TypeError):
            EventVersion("usgs-evt-1", True)

    def test_rejects_negative_timestamp(self) -> None:
        with self.assertRaises(ValueError):
            EventVersion("usgs-evt-1", -1)


if __name__ == "__main__":
    unittest.main()
