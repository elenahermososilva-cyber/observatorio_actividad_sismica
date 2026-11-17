"""T011 / US1: el evento sintético recorre productor → Kafka → consumidor → PostgreSQL → API y aparece UNA vez.

Ejecutar en el host con la pila levantada, desde observatorio-sismico/:
    python -m unittest tests.integration.test_vertical_demo -v
"""

import unittest

from tests.integration.stack import (
    DEMO_WINDOW, StackTestCase, api_get, compose, group_state, psql, wait_consumer_caught_up, wait_until,
)


class VerticalDemoTests(StackTestCase):
    def test_synthetic_event_flows_end_to_end_and_appears_exactly_once(self) -> None:
        before = group_state()
        end_before = before[0] if before else 0
        compose("restart", "producer")  # el productor publica demo-evt-001 al arrancar (+ duplicados si DEMO_DUPLICATES>0)
        wait_until(lambda: (s := group_state()) is not None and s[0] > end_before, 60, what="productor publica en Kafka")
        wait_consumer_caught_up()

        status, body = api_get(f"/api/eventos?mode=demo&start={DEMO_WINDOW}")
        self.assertEqual(status, 200)
        self.assertEqual(body["type"], "FeatureCollection")
        ids = [feature["id"] for feature in body["features"]]
        self.assertEqual(ids.count("demo-evt-001"), 1, f"debe aparecer exactamente una vez: {ids}")
        self.assertEqual(body["metadata"]["count"], len(body["features"]))
        self.assertEqual(body["metadata"]["mode"], "demo")
        self.assertIsInstance(body["metadata"]["last_ingestion"], int)

        feature = next(f for f in body["features"] if f["id"] == "demo-evt-001")
        self.assertEqual(feature["geometry"]["coordinates"][:2], [-3.7, 40.4])
        self.assertEqual(feature["properties"]["time"], 1_793_109_600_000)

    def test_database_holds_one_current_row_and_marks_event_as_synthetic(self) -> None:
        wait_consumer_caught_up()
        self.assertEqual(psql("select count(*) from demo.event_current where event_id='demo-evt-001'"), "1")
        row = psql("select mode, synthetic_flag, source from demo.event_message where event_id='demo-evt-001' limit 1")
        self.assertEqual(row, "demo|t|synthetic-demo")

    def test_every_published_version_is_stored_once_despite_repeated_messages(self) -> None:
        wait_consumer_caught_up()
        duplicates = psql(
            "select count(*) from (select event_id, updated_ms from demo.event_message "
            "group by 1,2 having count(*) > 1) d"
        )
        self.assertEqual(duplicates, "0")


if __name__ == "__main__":
    unittest.main()
