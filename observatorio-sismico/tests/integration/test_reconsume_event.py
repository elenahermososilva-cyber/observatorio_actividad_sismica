"""T018 / US2: releer el topic completo (reinicio del consumidor + offsets al principio) no duplica el estado.

    python -m unittest tests.integration.test_reconsume_event -v
"""

import unittest

from tests.integration.stack import (
    GROUP, KAFKA_BIN, StackTestCase, TOPIC, compose, group_state, snapshot, wait_consumer_caught_up, wait_until,
)


class ReconsumeTests(StackTestCase):
    def test_rereading_the_whole_topic_does_not_duplicate_visible_state(self) -> None:
        wait_consumer_caught_up()
        before = snapshot()
        self.assertEqual(before["current"] >= 1, True, "se necesita al menos un evento persistido")

        compose("stop", "consumer")
        try:
            compose(
                "exec", "-T", "kafka", f"{KAFKA_BIN}/kafka-consumer-groups.sh",
                "--bootstrap-server", "localhost:9092", "--group", GROUP, "--topic", TOPIC,
                "--reset-offsets", "--to-earliest", "--execute",
            )
            state = group_state()
            self.assertIsNotNone(state)
            self.assertGreater(state[1], 0, "tras el reset debe haber mensajes por releer")
        finally:
            compose("start", "consumer")

        wait_consumer_caught_up(90)  # lag 0 ⇒ todos los mensajes fueron reprocesados y confirmados
        after = snapshot()
        self.assertEqual(after, before, "la relectura no debe cambiar ni el estado actual ni el historial")

    def test_restart_without_reset_reprocesses_nothing(self) -> None:
        wait_consumer_caught_up()
        before = snapshot()
        compose("restart", "consumer")
        wait_until(lambda: (s := group_state()) is not None and s[1] == 0, 60, what="consumidor reiniciado al día")
        self.assertEqual(snapshot(), before)


if __name__ == "__main__":
    unittest.main()
