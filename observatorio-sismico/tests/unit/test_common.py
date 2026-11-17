import asyncio
import tempfile
import unittest
from itertools import islice
from pathlib import Path

from backend.common.backoff import backoff_delays, retry_async, retry_sync
from backend.common.config import ConfigError, get_int, get_list, get_str
from backend.db.migrate import discover_migrations


class BackoffTests(unittest.TestCase):
    def test_delays_grow_exponentially_and_are_capped(self) -> None:
        delays = list(islice(backoff_delays(1, 2, 10, jitter=0), 6))
        self.assertEqual(delays, [1, 2, 4, 8, 10, 10])

    def test_jitter_never_exceeds_cap_or_goes_below_floor(self) -> None:
        for rng_value in (0.0, 0.5, 0.999):
            delays = list(islice(backoff_delays(1, 2, 8, jitter=0.2, rng=lambda v=rng_value: v), 8))
            self.assertTrue(all(0.8 <= d <= 8 for d in delays))

    def test_invalid_parameters_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            next(backoff_delays(base=0))
        with self.assertRaises(ValueError):
            next(backoff_delays(base=5, maximum=1))

    def test_retry_sync_succeeds_after_transient_failures(self) -> None:
        calls, slept = [], []

        def flaky() -> str:
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError("down")
            return "ok"

        result = retry_sync(flaky, retry_on=(ConnectionError,), sleep=slept.append)
        self.assertEqual(result, "ok")
        self.assertEqual(len(slept), 2)

    def test_retry_sync_raises_after_max_attempts(self) -> None:
        def always_fail() -> None:
            raise ConnectionError("down")

        with self.assertRaises(ConnectionError):
            retry_sync(always_fail, retry_on=(ConnectionError,), attempts=3, sleep=lambda _: None)

    def test_retry_does_not_catch_unlisted_exceptions(self) -> None:
        def bug() -> None:
            raise KeyError("x")

        with self.assertRaises(KeyError):
            retry_sync(bug, retry_on=(ConnectionError,), sleep=lambda _: None)

    def test_retry_async(self) -> None:
        calls = []

        async def flaky() -> int:
            calls.append(1)
            if len(calls) < 2:
                raise TimeoutError
            return 7

        async def no_sleep(_: float) -> None:
            return None

        result = asyncio.run(retry_async(flaky, retry_on=(TimeoutError,), sleep=no_sleep))
        self.assertEqual(result, 7)


class ConfigTests(unittest.TestCase):
    def test_get_str_default_and_required(self) -> None:
        self.assertEqual(get_str("A", "x", env={}), "x")
        self.assertEqual(get_str("A", "x", env={"A": " y "}), "y")
        with self.assertRaises(ConfigError):
            get_str("A", env={})

    def test_get_int_validates(self) -> None:
        self.assertEqual(get_int("N", 60, env={}), 60)
        self.assertEqual(get_int("N", env={"N": "15"}, minimum=1), 15)
        with self.assertRaises(ConfigError):
            get_int("N", env={"N": "abc"})
        with self.assertRaises(ConfigError):
            get_int("N", env={"N": "0"}, minimum=1)

    def test_get_list(self) -> None:
        self.assertEqual(get_list("L", env={"L": "a, b,,c"}), ["a", "b", "c"])
        self.assertEqual(get_list("L", env={}), [])


class MigrationDiscoveryTests(unittest.TestCase):
    def test_real_repository_migrations_are_consistent(self) -> None:
        migrations = discover_migrations()
        self.assertEqual(migrations[0].version, 1)
        self.assertIn("event_current", migrations[0].sql)

    def test_gap_in_numbering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "schema.sql"
            base.write_text("SELECT 1;")
            mig = Path(tmp) / "migrations"
            mig.mkdir()
            (mig / "003_gap.sql").write_text("SELECT 1;")
            with self.assertRaises(ValueError):
                discover_migrations(base, mig)

    def test_invalid_file_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "schema.sql"
            base.write_text("SELECT 1;")
            mig = Path(tmp) / "migrations"
            mig.mkdir()
            (mig / "extra.sql").write_text("SELECT 1;")
            with self.assertRaises(ValueError):
                discover_migrations(base, mig)

    def test_consecutive_migrations_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "schema.sql"
            base.write_text("SELECT 1;")
            mig = Path(tmp) / "migrations"
            mig.mkdir()
            (mig / "002_a.sql").write_text("SELECT 2;")
            (mig / "003_b.sql").write_text("SELECT 3;")
            self.assertEqual([m.version for m in discover_migrations(base, mig)], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
