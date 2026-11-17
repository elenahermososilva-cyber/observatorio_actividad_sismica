"""Utilidades para tests que usan la pila Docker real. Se ejecutan en el HOST (solo stdlib).

Requisitos: `docker compose up --build -d` hecho desde observatorio-sismico/ y API en 127.0.0.1:8000.
Si la API no responde, los tests se omiten (no fallan) para no romper `unittest discover` sin pila.
"""

import json
import subprocess
import time
import unittest
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = "http://127.0.0.1:8000"
GROUP = "observatorio-consumer"
TOPIC = "sismos.demo"
KAFKA_BIN = "/opt/kafka/bin"
DEMO_WINDOW = "2026-10-27T00:00:00Z"  # el evento demo ocurre el 2026-10-27T14:00:00Z


def compose(*args: str, input: str | None = None, check: bool = True, timeout: int = 120) -> str:
    result = subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT, input=input, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout + ("" if check else result.stderr)


def api_get(path: str, timeout: float = 5.0) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.loads(error.read())


def api_reachable() -> bool:
    try:
        api_get("/api/salud", timeout=2)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def psql(sql: str) -> str:
    out = compose("exec", "-T", "postgres", "psql", "-U", "observatorio", "-d", "observatorio", "-tA", "-c", sql)
    return out.strip()


def group_state() -> tuple[int, int] | None:
    """(suma LOG-END-OFFSET, suma LAG) del grupo del consumidor; None si el grupo aún no existe."""
    out = compose(
        "exec", "-T", "kafka", f"{KAFKA_BIN}/kafka-consumer-groups.sh",
        "--bootstrap-server", "localhost:9092", "--describe", "--group", GROUP,
        check=False,
    )
    end = lag = 0
    found = False
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[0] == GROUP and parts[1] == TOPIC:
            try:
                end += int(parts[4])
                lag += int(parts[5])
                found = True
            except ValueError:
                return None  # offsets '-' → el grupo todavía no ha confirmado nada
    return (end, lag) if found else None


def wait_until(condition: Callable[[], bool], timeout: float = 60.0, interval: float = 1.5, what: str = "condición") -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            if condition():
                return
        except Exception as error:  # noqa: BLE001 - se reintenta hasta el plazo
            last_error = error
        time.sleep(interval)
    raise AssertionError(f"timeout esperando: {what}" + (f" (último error: {last_error})" if last_error else ""))


def publish_lines(lines: list[str]) -> None:
    compose(
        "exec", "-T", "kafka", f"{KAFKA_BIN}/kafka-console-producer.sh",
        "--bootstrap-server", "localhost:9092", "--topic", TOPIC,
        input="\n".join(lines) + "\n",
    )


def wait_consumer_caught_up(timeout: float = 60.0) -> None:
    wait_until(lambda: (s := group_state()) is not None and s[1] == 0, timeout, what="lag del consumidor = 0")


def snapshot() -> dict:
    """Estado observable de la base para comparar antes/después."""
    return {
        "current": int(psql("select count(*) from demo.event_current")),
        "messages": int(psql("select count(*) from demo.event_message where event_id='demo-evt-001'")),
        "version": psql("select current_version_ms from demo.event_current where event_id='demo-evt-001'"),
    }


class StackTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not api_reachable():
            raise unittest.SkipTest("pila no levantada (docker compose up --build -d)")
