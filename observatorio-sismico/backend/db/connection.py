"""Conexión PostgreSQL asíncrona única y reutilizable, con reconexión y espera progresiva.

Compartida por consumidor y productor. Solo se reintentan fallos de infraestructura (base caída o conexión
perdida); los errores de datos o de programación se propagan. Las operaciones son idempotentes, así que repetir
una tras perder la conexión a mitad no puede duplicar efectos.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import psycopg

from backend.common.backoff import backoff_delays

log = logging.getLogger("db")
T = TypeVar("T")

DB_ERRORS_TO_RETRY = (psycopg.OperationalError, psycopg.InterfaceError)


class Database:
    def __init__(self, url: str, *, hint: str = "") -> None:
        self._url = url
        self._hint = hint  # texto de contexto para el log, p. ej. "offset NOT committed"
        self._conn: psycopg.AsyncConnection | None = None

    async def run(self, operation: Callable[[psycopg.AsyncConnection], Awaitable[T]]) -> T:
        delays = backoff_delays(1.0, 2.0, 30.0)
        while True:
            try:
                if self._conn is None or self._conn.closed:
                    self._conn = await psycopg.AsyncConnection.connect(
                        self._url, autocommit=True, connect_timeout=5
                    )
                return await operation(self._conn)
            except DB_ERRORS_TO_RETRY as error:
                delay = next(delays)
                context = f"; {self._hint}" if self._hint else ""
                log.error("database unavailable (%s)%s, retrying in %.1fs", error, context, delay)
                await self.close()
                await asyncio.sleep(delay)

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:  # noqa: BLE001 - cierre best-effort de una conexión ya rota
                pass
            self._conn = None
