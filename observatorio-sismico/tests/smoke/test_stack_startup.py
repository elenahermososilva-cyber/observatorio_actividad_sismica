"""T023 / US3: los cinco servicios obligatorios están levantados y sanos, y solo se publica la API.

    python -m unittest tests.smoke.test_stack_startup -v
"""

import json
import unittest

from tests.integration.stack import StackTestCase, api_get, compose

REQUIRED = {"producer", "kafka", "consumer", "postgres", "api"}


def services() -> dict[str, dict]:
    out = compose("ps", "--all", "--format", "json").strip()
    rows = json.loads(out) if out.startswith("[") else [json.loads(line) for line in out.splitlines() if line.strip()]
    return {row["Service"]: row for row in rows}


class StackStartupTests(StackTestCase):
    def test_exactly_the_five_required_services_exist(self) -> None:
        self.assertEqual(set(services()), REQUIRED)

    def test_all_services_are_running_and_healthy(self) -> None:
        for name, row in services().items():
            self.assertEqual(row["State"], "running", name)
            self.assertEqual(row["Health"], "healthy", name)

    def test_only_the_api_is_published_and_only_on_loopback(self) -> None:
        for name, row in services().items():
            publishers = row.get("Publishers") or []
            published = [p for p in publishers if p.get("PublishedPort")]
            if name == "api":
                self.assertEqual([(p["URL"], p["PublishedPort"]) for p in published][:1], [("127.0.0.1", 8000)])
            else:
                self.assertEqual(published, [], f"{name} no debe publicar puertos en el host")

    def test_api_health_endpoint_reports_database_ok(self) -> None:
        status, body = api_get("/api/salud")
        self.assertEqual(status, 200)
        self.assertEqual((body["status"], body["database"]), ("ok", "ok"))


if __name__ == "__main__":
    unittest.main()
