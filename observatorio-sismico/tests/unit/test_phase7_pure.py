"""Lógica pura de la Fase 7 (sin red, sin base de datos, sin Kafka): corre también en el host."""

import asyncio
import gzip
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.producer.envelope import build_envelope
from backend.producer.history_data import (
    Interval, file_name, iter_unique_features, month_intervals, month_is_reusable, plan_intervals,
    query_params, sha256_file, split_interval,
)
from backend.producer.producer import build_demo_message
from backend.producer.raw_store import content_hash, prune, raw_path_for, read_raw, save_raw
from backend.producer.replay import REVISION_DELTA_MS, build_plan, make_revision, select_events
from backend.producer.schema import EventMessage, IngestionMode

NOW = datetime(2026, 11, 17, 12, 0, 5, tzinfo=timezone.utc)


def feature(event_id="us1", updated=2_000, time_ms=1_000, mag=5.5, kind="earthquake", coords=(10.0, 20.0, 5.0)) -> dict:
    return {
        "type": "Feature", "id": event_id,
        "geometry": {"type": "Point", "coordinates": list(coords)},
        "properties": {"mag": mag, "magType": "mww", "place": "X", "time": time_ms, "updated": updated, "type": kind},
    }


# ---------------------------------------------------------------- replay_at (7.7)
class ReplayAtTests(unittest.TestCase):
    def replay_message(self, **overrides) -> EventMessage:
        base = dict(
            event_id="us1", source="usgs-history", mode=IngestionMode.REPLAY, ingested_at=NOW, updated_ms=2_000,
            payload=feature(), synthetic_flag=False, replay_at=NOW,
        )
        base.update(overrides)
        return EventMessage(**base)

    def test_replay_requires_replay_at(self) -> None:
        with self.assertRaisesRegex(ValueError, "must include replay_at"):
            self.replay_message(replay_at=None)

    def test_replay_at_forbidden_outside_replay_mode(self) -> None:
        demo = build_demo_message()
        with self.assertRaisesRegex(ValueError, "only allowed in replay mode"):
            EventMessage(**{**demo.__dict__, "replay_at": NOW})

    def test_replay_at_must_be_utc(self) -> None:
        with self.assertRaisesRegex(ValueError, "UTC"):
            self.replay_message(replay_at=datetime(2026, 1, 1))
        with self.assertRaisesRegex(ValueError, "UTC"):
            self.replay_message(replay_at=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=2))))

    def test_round_trip_keeps_the_four_timestamps_distinct(self) -> None:
        replay_at = NOW + timedelta(seconds=7)
        message = self.replay_message(replay_at=replay_at)
        restored = EventMessage.from_json(message.to_json())
        self.assertEqual(restored, message)
        value = message.to_dict()
        self.assertEqual(value["replay_at"], "2026-11-17T12:00:12Z")
        self.assertEqual(value["ingested_at"], "2026-11-17T12:00:05Z")
        self.assertEqual(value["updated"], 2_000)
        self.assertEqual(value["payload"]["properties"]["time"], 1_000)  # ocurrencia intacta

    def test_demo_messages_do_not_carry_the_field(self) -> None:
        self.assertNotIn("replay_at", build_demo_message().to_dict())

    def test_non_string_replay_at_is_rejected(self) -> None:
        value = self.replay_message().to_dict()
        value["replay_at"] = 12345
        with self.assertRaises(ValueError):
            EventMessage.from_dict(value)


# ---------------------------------------------------------------- sobres (7.3)
class EnvelopeTests(unittest.TestCase):
    def build(self, feat, **kw):
        return build_envelope(feat, mode=IngestionMode.LIVE, source="usgs", synthetic_flag=False, ingested_at=NOW, **kw)

    def test_valid_feature_becomes_a_valid_message_keyed_by_event_id(self) -> None:
        env = self.build(feature())
        self.assertTrue(env.well_formed)
        self.assertEqual((env.key, env.dedupe), ("us1", ("us1", 2_000)))
        message = EventMessage.from_json(env.value.decode())
        self.assertEqual((message.mode, message.source, message.synthetic_flag), (IngestionMode.LIVE, "usgs", False))

    def test_non_earthquake_is_still_published_for_the_consumer_to_quarantine(self) -> None:
        env = self.build(feature(kind="quarry blast"))
        self.assertTrue(env.well_formed)  # estructuralmente válido: el filtro de tipo es del consumidor (D3)
        self.assertEqual(json.loads(env.value)["payload"]["properties"]["type"], "quarry blast")

    def test_invalid_coordinates_are_wrapped_not_dropped(self) -> None:
        env = self.build(feature(coords=(10.0, 95.0, 5.0)))
        self.assertFalse(env.well_formed)
        self.assertEqual(env.dedupe, ("us1", 2_000))  # misma clave por versión: se rechaza una vez por versión
        value = json.loads(env.value)
        self.assertEqual(value["payload"]["geometry"]["coordinates"], [10.0, 95.0, 5.0])  # original intacto

    def test_missing_id_gets_stable_content_based_key(self) -> None:
        broken = feature()
        del broken["id"]
        a, b = self.build(broken), self.build(json.loads(json.dumps(broken)))
        self.assertEqual(a.dedupe, b.dedupe)
        self.assertTrue(a.dedupe[0].startswith("invalid:"))
        self.assertIsNone(a.key)
        other = feature(mag=1.0)
        del other["id"]
        self.assertNotEqual(self.build(other).dedupe, a.dedupe)

    def test_missing_updated_is_wrapped(self) -> None:
        broken = feature()
        del broken["properties"]["updated"]
        env = self.build(broken)
        self.assertFalse(env.well_formed)
        self.assertTrue(env.dedupe[0].startswith("invalid:"))

    def test_non_dict_feature_does_not_crash(self) -> None:
        env = self.build("garbage")
        self.assertFalse(env.well_formed)
        self.assertIn("garbage", env.value.decode())

    def test_replay_envelope_carries_replay_at(self) -> None:
        env = build_envelope(
            feature(), mode=IngestionMode.REPLAY, source="usgs-history", synthetic_flag=False,
            ingested_at=NOW, replay_at=NOW,
        )
        self.assertEqual(json.loads(env.value)["replay_at"], "2026-11-17T12:00:05Z")


# ---------------------------------------------------------------- almacén de originales (7.2)
class RawStoreTests(unittest.TestCase):
    def test_hash_ignores_volatile_feed_metadata_and_key_order(self) -> None:
        a = [feature("a"), feature("b")]
        self.assertEqual(content_hash(a), content_hash(json.loads(json.dumps(a))))
        reordered = [{k: f[k] for k in reversed(list(f))} for f in a]
        self.assertEqual(content_hash(a), content_hash(reordered))

    def test_hash_changes_with_new_event_or_revision(self) -> None:
        base = [feature("a")]
        self.assertNotEqual(content_hash(base), content_hash(base + [feature("b")]))
        self.assertNotEqual(content_hash(base), content_hash([feature("a", updated=3_000)]))

    def test_save_and_read_roundtrip_is_byte_exact_and_compressed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            body = json.dumps({"metadata": {"generated": 1}, "features": [feature()]}).encode() * 50
            path = save_raw(Path(tmp), body, NOW)
            self.assertEqual(path, raw_path_for(Path(tmp), NOW))
            self.assertEqual(path.parts[-4:], ("2026", "11", "17", "120005.geojson.gz"))
            self.assertEqual(read_raw(path), body)
            self.assertLess(path.stat().st_size, len(body))
            self.assertEqual(list(Path(tmp).rglob("*.tmp")), [])  # escritura atómica: sin temporales

    def test_prune_removes_only_old_files_and_empty_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = save_raw(Path(tmp), b"{}", datetime(2026, 1, 1, tzinfo=timezone.utc))
            new = save_raw(Path(tmp), b"{}", NOW)
            ancient = time.time() - 40 * 86400
            os.utime(old, (ancient, ancient))
            self.assertEqual(prune(Path(tmp), 14), 1)
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())
            self.assertFalse((Path(tmp) / "2026" / "01").exists())  # carpeta vacía eliminada

    def test_prune_on_missing_directory_is_safe(self) -> None:
        self.assertEqual(prune(Path("/does/not/exist"), 14), 0)


# ---------------------------------------------------------------- histórico (7.5)
class HistoryPlanningTests(unittest.TestCase):
    def test_year_is_split_into_twelve_contiguous_months(self) -> None:
        months = month_intervals(2025)
        self.assertEqual([m[0] for m in months][:2], ["2025-01", "2025-02"])
        self.assertEqual(len(months), 12)
        self.assertEqual(months[0][1].start, datetime(2025, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(months[-1][1].end, datetime(2026, 1, 1, tzinfo=timezone.utc))
        for (_, a), (_, b) in zip(months, months[1:]):
            self.assertEqual(a.end, b.start)  # sin huecos ni solapes nominales

    def test_split_halves_the_interval_exactly(self) -> None:
        interval = Interval(datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 2, 1, tzinfo=timezone.utc))
        first, second = split_interval(interval)
        self.assertEqual((first.start, second.end), (interval.start, interval.end))
        self.assertEqual(first.end, second.start)
        self.assertEqual(first.seconds + second.seconds, interval.seconds)
        with self.assertRaises(ValueError):
            split_interval(Interval(interval.start, interval.start + timedelta(seconds=1)))

    def test_interval_must_be_ordered(self) -> None:
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            Interval(now, now)

    def test_no_subdivision_when_count_fits(self) -> None:
        month = month_intervals(2025)[0][1]

        async def count(_):
            return 1_300

        plan = asyncio.run(plan_intervals(month, count))
        self.assertEqual(plan, [(month, 1_300)])

    def test_over_limit_is_subdivided_until_every_part_fits_and_nothing_is_lost(self) -> None:
        month = month_intervals(2025)[0][1]
        events_per_second = 25_000 / month.seconds  # 25.000 eventos repartidos uniformemente: no cabe en una consulta

        async def count(interval):
            return round(events_per_second * interval.seconds)

        plan = asyncio.run(plan_intervals(month, count))
        self.assertGreater(len(plan), 1)
        self.assertTrue(all(c <= 20_000 for _, c in plan))
        self.assertEqual(plan[0][0].start, month.start)
        self.assertEqual(plan[-1][0].end, month.end)
        for (a, _), (b, _) in zip(plan, plan[1:]):
            self.assertEqual(a.end, b.start)  # cobertura continua: ningún tramo queda sin pedir
        self.assertAlmostEqual(sum(c for _, c in plan), 25_000, delta=len(plan))

    def test_query_parameters_follow_the_enunciado(self) -> None:
        interval = month_intervals(2025)[0][1]
        params = query_params(interval, 4.0)
        self.assertEqual(params["starttime"], "2025-01-01T00:00:00")
        self.assertEqual(params["endtime"], "2025-02-01T00:00:00")
        self.assertEqual((params["minmagnitude"], params["eventtype"], params["orderby"]), ("4", "earthquake", "time-asc"))
        self.assertEqual(params["format"], "geojson")

    def test_file_names(self) -> None:
        label, month = month_intervals(2025)[0]
        self.assertEqual(file_name(month, label, whole_month=True), "2025-01.geojson")
        first, _ = split_interval(month)
        self.assertEqual(file_name(first, label, whole_month=False), "2025-01_20250101T000000_20250116T120000.geojson")


class HistoryReadingTests(unittest.TestCase):
    def write(self, directory: Path, name: str, features: list) -> bytes:
        body = json.dumps({"type": "FeatureCollection", "features": features}).encode()
        (directory / name).write_bytes(body)
        return body

    def test_boundary_duplicates_are_removed_keeping_the_latest_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.write(d, "2025-01.geojson", [feature("a", updated=100, time_ms=10), feature("edge", updated=100, time_ms=50)])
            self.write(d, "2025-02.geojson", [feature("edge", updated=900, time_ms=50, mag=6.0), feature("b", time_ms=70)])
            unique, duplicates = iter_unique_features(d)
        self.assertEqual([f["id"] for f in unique], ["a", "edge", "b"])  # ordenados por tiempo de ocurrencia
        self.assertEqual(duplicates, 1)
        self.assertEqual(next(f for f in unique if f["id"] == "edge")["properties"]["updated"], 900)

    def test_older_duplicate_never_replaces_newer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.write(d, "2025-01.geojson", [feature("e", updated=900)])
            self.write(d, "2025-02.geojson", [feature("e", updated=100)])
            unique, _ = iter_unique_features(d)
        self.assertEqual(unique[0]["properties"]["updated"], 900)

    def test_month_is_reused_only_when_complete_and_checksums_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            body = self.write(d, "2025-01.geojson", [feature()])
            import hashlib

            month = {"complete": True, "queries": [{"file": "2025-01.geojson", "sha256": hashlib.sha256(body).hexdigest()}]}
            self.assertTrue(month_is_reusable(d, month))
            self.assertFalse(month_is_reusable(d, {**month, "complete": False}))
            self.assertFalse(month_is_reusable(d, None))
            (d / "2025-01.geojson").write_bytes(b"corrupted")  # archivo alterado: se vuelve a descargar
            self.assertFalse(month_is_reusable(d, month))
            (d / "2025-01.geojson").unlink()
            self.assertFalse(month_is_reusable(d, month))
            self.assertEqual(sha256_file(self._tmp_file(d)), hashlib.sha256(b"x").hexdigest())

    @staticmethod
    def _tmp_file(directory: Path) -> Path:
        path = directory / "x.bin"
        path.write_bytes(b"x")
        return path


# ---------------------------------------------------------------- replay (7.6)
class ReplayPlanTests(unittest.TestCase):
    def events(self):
        return [
            feature("old", time_ms=100, mag=7.0),
            feature("small", time_ms=200, mag=4.1),
            feature("e1", time_ms=300, mag=5.2),
            feature("blast", time_ms=350, mag=6.0, kind="explosion"),
            feature("nomag", time_ms=360, mag=None),
            feature("e2", time_ms=400, mag=6.1),
            feature("e3", time_ms=500, mag=5.0),
            feature("e4", time_ms=600, mag=5.9),
        ]

    def test_selection_is_ordered_filtered_and_limited(self) -> None:
        chosen = select_events(list(reversed(self.events())), start_ms=150, min_mag=5.0, count=3)
        self.assertEqual([f["id"] for f in chosen], ["e1", "e2", "e3"])  # sin explosión, sin ND, sin M<5, ordenados

    def test_selection_with_fewer_events_than_requested(self) -> None:
        self.assertEqual(len(select_events(self.events(), 0, 9.0, 5)), 0)
        self.assertEqual(len(select_events(self.events(), 0, 5.0, 100)), 5)

    def test_revision_changes_version_and_magnitude_but_not_occurrence_or_original(self) -> None:
        original = feature("e2", updated=5_000, time_ms=400, mag=6.1)
        revised = make_revision(original)
        self.assertEqual(revised["properties"]["updated"], 5_000 + REVISION_DELTA_MS)
        self.assertEqual(revised["properties"]["mag"], 6.3)
        self.assertEqual(revised["properties"]["time"], 400)
        self.assertEqual(original["properties"]["updated"], 5_000)  # no muta la copia original

    def test_plan_appends_duplicate_revision_and_stale_with_expected_outcomes(self) -> None:
        events = select_events(self.events(), 0, 5.0, 3)
        plan = build_plan(events)
        self.assertEqual([p.label for p in plan], ["original"] * 3 + ["duplicate", "revision", "stale"])
        self.assertEqual([p.expected for p in plan], ["NEW"] * 3 + ["DUPLICATE", "REVISION", "STALE"])
        duplicate, revision, stale = plan[3:]
        self.assertEqual(duplicate.feature, events[0])
        self.assertEqual(revision.feature["id"], events[1]["id"])
        self.assertGreater(revision.feature["properties"]["updated"], events[1]["properties"]["updated"])
        self.assertEqual(stale.feature, events[1])

    def test_injected_revision_is_labelled_synthetic_and_real_data_is_not(self) -> None:
        plan = build_plan(select_events(self.events(), 0, 5.0, 3))
        for item in plan:
            if item.label == "revision":
                self.assertTrue(item.synthetic_flag)
                self.assertEqual(item.source, "replay-injected")
            else:
                self.assertFalse(item.synthetic_flag)
                self.assertEqual(item.source, "usgs-history")

    def test_no_injection_when_disabled_or_too_few_events(self) -> None:
        events = select_events(self.events(), 0, 5.0, 3)
        self.assertEqual(len(build_plan(events, inject_cases=False)), 3)
        self.assertEqual(len(build_plan(events[:1])), 1)


if __name__ == "__main__":
    unittest.main()
