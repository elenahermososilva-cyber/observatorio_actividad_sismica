"""T022 / US2: escenarios negativos con la pila real.

(a) PostgreSQL caído: el consumidor lo registra y NO confirma el offset (el lag se mantiene).
(b) Con la base caída la API responde 503 explícito, nunca features: [].
(c) Al volver la base: el consumidor recupera el lag, la API vuelve a 200 y la relectura no duplica nada.

    python -m unittest tests.integration.test_failure_scenarios -v
"""

import time
import unittest

from tests.integration.stack import (
    DEMO_WINDOW, StackTestCase, api_get, compose, group_state, publish_lines, snapshot, wait_consumer_caught_up, wait_until,
)

from backend.producer.producer import build_demo_message


class FailureScenarioTests(StackTestCase):
    def test_database_outage_blocks_offset_commit_and_api_reports_error(self) -> None:
        wait_consumer_caught_up()
        before = snapshot()
        duplicate_line = build_demo_message().to_json()  # misma versión que ya existe: no cambia el estado

        compose("stop", "postgres")
        try:
            publish_lines([duplicate_line])

            # (a) el consumidor registra el fallo y no confirma
            wait_until(
                lambda: "offset NOT committed" in compose("logs", "consumer", "--no-log-prefix", "--since", "90s"),
                60, what="log 'offset NOT committed' del consumidor",
            )
            time.sleep(5)
            state = group_state()
            self.assertIsNotNone(state)
            self.assertGreaterEqual(state[1], 1, "el offset no debe avanzar mientras PostgreSQL esté caído")

            # (b) la API no presenta el fallo como colección vacía
            status, body = api_get(f"/api/eventos?mode=demo&start={DEMO_WINDOW}")
            self.assertEqual(status, 503)
            self.assertEqual(body["error"]["code"], "database_unavailable")
            self.assertNotIn("features", body)
            salud_status, salud = api_get("/api/salud")
            self.assertEqual(salud_status, 503)
            self.assertEqual(salud["database"], "unavailable")
        finally:
            compose("start", "postgres")

        # (c) recuperación sin duplicados
        wait_until(lambda: api_get("/api/salud")[0] == 200, 90, what="API vuelve a 200")
        wait_consumer_caught_up(90)
        self.assertEqual(snapshot(), before, "el mensaje repetido tras la caída no debe duplicar el estado")
        status, body = api_get(f"/api/eventos?mode=demo&start={DEMO_WINDOW}")
        self.assertEqual(status, 200)
        self.assertEqual([f["id"] for f in body["features"]].count("demo-evt-001"), 1)


if __name__ == "__main__":
    unittest.main()
