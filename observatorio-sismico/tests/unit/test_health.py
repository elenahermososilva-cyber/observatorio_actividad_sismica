import os
import tempfile
import time
import unittest
from pathlib import Path

from backend.common.health import is_healthy, touch


class HeartbeatTests(unittest.TestCase):
    def test_missing_file_is_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(is_healthy(Path(tmp) / "nope"))

    def test_fresh_file_is_healthy_and_old_file_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hb"
            touch(path)
            self.assertTrue(is_healthy(path, max_age=45))
            old = time.time() - 120
            os.utime(path, (old, old))
            self.assertFalse(is_healthy(path, max_age=45))
            touch(path)
            self.assertTrue(is_healthy(path, max_age=45))


if __name__ == "__main__":
    unittest.main()
