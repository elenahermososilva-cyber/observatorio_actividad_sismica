"""Latido de vida para servicios sin puerto HTTP (productor y consumidor).

El servicio ejecuta `heartbeat_loop` en segundo plano y actualiza un archivo cada pocos segundos;
el healthcheck de Docker ejecuta `python -m backend.common.health` y falla si el archivo falta o es antiguo.
Comprueba que el bucle de eventos sigue vivo; no sustituye a las métricas de negocio (lag, última ingesta).
"""

import asyncio
import os
import sys
import time
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("HEARTBEAT_FILE", "/tmp/heartbeat"))
DEFAULT_INTERVAL = 10.0
DEFAULT_MAX_AGE = 45.0


def touch(path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, None)


async def heartbeat_loop(path: Path = DEFAULT_PATH, interval: float = DEFAULT_INTERVAL) -> None:
    while True:
        touch(path)
        await asyncio.sleep(interval)


def is_healthy(path: Path = DEFAULT_PATH, max_age: float = DEFAULT_MAX_AGE, now: float | None = None) -> bool:
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except OSError:
        return False
    return age <= max_age


if __name__ == "__main__":
    sys.exit(0 if is_healthy() else 1)
