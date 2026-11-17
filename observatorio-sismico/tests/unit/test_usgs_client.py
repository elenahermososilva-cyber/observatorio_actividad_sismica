"""Cliente USGS (7.1) con transporte simulado: nada sale a internet. Requiere httpx (contenedor)."""

import asyncio
import json
import unittest

try:
    import httpx

    from backend.producer.usgs import FeedError, fetch_count, fetch_feature_collection, retry_after_seconds
except ImportError:
    httpx = None

GOOD = {"type": "FeatureCollection", "metadata": {"generated": 1}, "features": [{"id": "a"}, {"id": "b"}]}


def run(coro):
    return asyncio.run(coro)


@unittest.skipIf(httpx is None, "httpx no disponible")
class FetchFeatureCollectionTests(unittest.TestCase):
    def fetch(self, responses, **kw):
        """`responses`: lista de httpx.Response o excepciones, consumidos en orden. Devuelve (resultado|error, esperas)."""
        queue = list(responses)
        calls, sleeps = [], []

        def handler(request):
            calls.append(request)
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        async def sleep(seconds):
            sleeps.append(seconds)

        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await fetch_feature_collection(client, "https://usgs.test/feed", sleep=sleep, **kw)

        try:
            return run(go()), sleeps, calls
        except FeedError as error:
            return error, sleeps, calls

    @staticmethod
    def ok(data=GOOD):
        return httpx.Response(200, content=json.dumps(data).encode())

    def test_success_on_first_try(self) -> None:
        result, sleeps, calls = self.fetch([self.ok()])
        self.assertEqual((result.status, len(result.features), result.attempts), (200, 2, 1))
        self.assertEqual(sleeps, [])
        self.assertEqual(len(calls), 1)

    def test_retries_5xx_then_succeeds_with_increasing_waits(self) -> None:
        result, sleeps, _ = self.fetch([httpx.Response(503), httpx.Response(500), self.ok()], base=2.0)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(len(sleeps), 2)
        self.assertLess(sleeps[0], sleeps[1])  # espera progresiva

    def test_429_honours_retry_after(self) -> None:
        result, sleeps, _ = self.fetch([httpx.Response(429, headers={"Retry-After": "7"}), self.ok()])
        self.assertEqual(result.attempts, 2)
        self.assertEqual(sleeps, [7.0])

    def test_retry_after_is_capped(self) -> None:
        response = httpx.Response(429, headers={"Retry-After": "99999"})
        self.assertEqual(retry_after_seconds(response, 60.0), 60.0)
        self.assertIsNone(retry_after_seconds(httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), 60))
        self.assertIsNone(retry_after_seconds(httpx.Response(429), 60))

    def test_timeout_and_network_errors_are_retried(self) -> None:
        result, sleeps, _ = self.fetch([httpx.ReadTimeout("slow"), httpx.ConnectError("down"), self.ok()])
        self.assertEqual((result.attempts, len(sleeps)), (3, 2))

    def test_invalid_json_is_retried_then_reported(self) -> None:
        result, _, _ = self.fetch([httpx.Response(200, content=b"<html>maintenance</html>"), self.ok()])
        self.assertEqual(result.attempts, 2)
        error, _, calls = self.fetch([httpx.Response(200, content=b"{broken")] * 3, attempts=3)
        self.assertIsInstance(error, FeedError)
        self.assertIn("invalid JSON", str(error))
        self.assertEqual(len(calls), 3)

    def test_nan_is_rejected_as_invalid_json(self) -> None:
        error, _, _ = self.fetch([httpx.Response(200, content=b'{"features":[{"mag":NaN}]}')] * 2, attempts=2)
        self.assertIsInstance(error, FeedError)
        self.assertIn("invalid JSON", str(error))

    def test_response_without_features_list_is_invalid(self) -> None:
        for body in (b"[]", b'{"features": "no"}', b'{"type": "FeatureCollection"}', b"null"):
            error, _, _ = self.fetch([httpx.Response(200, content=body)] * 2, attempts=2)
            self.assertIsInstance(error, FeedError, body)

    def test_empty_feature_list_is_a_valid_response(self) -> None:
        result, _, _ = self.fetch([self.ok({"type": "FeatureCollection", "features": []})])
        self.assertEqual(result.features, [])

    def test_exhausted_retries_raise_with_status_and_attempts(self) -> None:
        error, sleeps, calls = self.fetch([httpx.Response(503)] * 4, attempts=4)
        self.assertIsInstance(error, FeedError)
        self.assertEqual((error.status, error.attempts, len(calls), len(sleeps)), (503, 4, 4, 3))
        self.assertIn("HTTP 503", str(error))

    def test_non_retryable_4xx_fails_immediately(self) -> None:
        for status in (400, 401, 403, 404):
            error, sleeps, calls = self.fetch([httpx.Response(status)])
            self.assertIsInstance(error, FeedError, status)
            self.assertEqual((error.status, len(calls), sleeps), (status, 1, []))

    def test_timeouts_exhausted_report_no_status(self) -> None:
        error, _, _ = self.fetch([httpx.ReadTimeout("slow")] * 2, attempts=2)
        self.assertIsNone(error.status)
        self.assertIn("timeout", str(error))


@unittest.skipIf(httpx is None, "httpx no disponible")
class FetchCountTests(unittest.TestCase):
    def count(self, responses, attempts=3):
        queue = list(responses)

        async def go():
            async def sleep(_):
                return None

            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: queue.pop(0))) as client:
                return await fetch_count(client, "https://usgs.test/count", {}, attempts=attempts, sleep=sleep)

        return run(go())

    def test_parses_plain_integer(self) -> None:
        self.assertEqual(self.count([httpx.Response(200, text="1342\n")]), 1342)

    def test_retries_server_errors(self) -> None:
        self.assertEqual(self.count([httpx.Response(500), httpx.Response(200, text="7")]), 7)

    def test_non_integer_and_client_errors_raise(self) -> None:
        with self.assertRaises(FeedError):
            self.count([httpx.Response(200, text="many")] * 3)
        with self.assertRaises(FeedError):
            self.count([httpx.Response(400, text="bad")])


if __name__ == "__main__":
    unittest.main()
