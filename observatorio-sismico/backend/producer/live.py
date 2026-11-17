"""Productor live: consulta el feed de USGS cada POLL_SECONDS y publica novedades y revisiones.

Cada ciclo:
1. GET con reintentos (usgs.py). Si falla definitivamente se registra el error en `ingest.extraction_log`
   y NO se toca ningún estado válido anterior: las versiones ya publicadas siguen marcadas.
2. Se conserva el original (gzip) solo si el contenido cambió respecto a la última consulta correcta.
3. Se compara cada (id, updated) con `ingest.published_version` y se publican las versiones nuevas o revisadas.
4. Una versión se marca como publicada SOLO después de que Kafka confirme el mensaje (`send_and_wait`, acks=all).
   Si el proceso cae entre ambos pasos, se reenviará y el consumidor lo tolera.

Ausencia en el feed ≠ eliminación: un evento puede salir de la ventana de 24 h sin haber sido borrado por USGS.
Nada se borra de la base por no aparecer en una respuesta.
"""

import asyncio
import logging
import signal
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg

from backend.common.config import get_int, get_str
from backend.db.connection import Database
from backend.producer import raw_store, state
from backend.producer.envelope import build_envelope
from backend.producer.schema import IngestionMode
from backend.producer.usgs import USER_AGENT, FeedError, fetch_feature_collection

log = logging.getLogger("producer.live")
MODE = "live"
SOURCE = "usgs"


@dataclass(frozen=True)
class CycleReport:
    ok: bool
    fetched: int = 0
    published: int = 0
    skipped: int = 0
    malformed: int = 0
    error: str | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_cycle(
    *,
    http: httpx.AsyncClient,
    sender,
    db: Database,
    topic: str,
    url: str,
    raw_dir: Path,
    retention_days: int,
    now=utcnow,
) -> CycleReport:
    started_at = now()
    try:
        result = await fetch_feature_collection(http, url)
    except FeedError as error:
        log.error("USGS query failed: %s", error)
        await db.run(
            lambda conn: state.log_extraction(
                conn, mode=MODE, url=url, started_at=started_at, ok=False, latency_ms=error.latency_ms,
                http_status=error.status, error=str(error)[:500],
            )
        )
        return CycleReport(ok=False, error=str(error))

    features = result.features
    digest = raw_store.content_hash(features)
    previous = await db.run(lambda conn: state.last_ok_content_hash(conn, MODE))
    raw_path: str | None = None
    if digest != previous:
        saved = await asyncio.to_thread(raw_store.save_raw, raw_dir, result.body, started_at)
        raw_path = str(saved)
        await asyncio.to_thread(raw_store.prune, raw_dir, retention_days)

    # La consulta fue correcta: se registra ya (mueve last_ingestion) con independencia de la publicación.
    await db.run(
        lambda conn: state.log_extraction(
            conn, mode=MODE, url=url, started_at=started_at, ok=True, latency_ms=result.latency_ms,
            http_status=result.status, record_count=len(features), response_bytes=len(result.body),
            content_sha256=digest, raw_path=raw_path,
        )
    )

    ingested_at = now()
    envelopes = [
        build_envelope(f, mode=IngestionMode.LIVE, source=SOURCE, synthetic_flag=False, ingested_at=ingested_at)
        for f in features
    ]
    seen = await db.run(lambda conn: state.already_published(conn, MODE, [e.dedupe for e in envelopes]))

    published = skipped = malformed = 0
    for envelope in envelopes:
        if envelope.dedupe in seen:
            skipped += 1
            continue
        await sender.send_and_wait(
            topic, value=envelope.value, key=envelope.key.encode("utf-8") if envelope.key else None
        )
        # Marcar solo tras el ack de Kafka.
        await db.run(lambda conn, e=envelope: state.mark_published(conn, MODE, e.dedupe[0], e.dedupe[1]))
        seen.add(envelope.dedupe)  # un mismo (id, updated) repetido dentro de la respuesta se publica una vez
        published += 1
        malformed += 0 if envelope.well_formed else 1

    log.info(
        "cycle ok: %d features, %d published (%d malformed), %d already published; latency %d ms, %d attempt(s)",
        len(features), published, malformed, skipped, result.latency_ms, result.attempts,
    )
    return CycleReport(True, len(features), published, skipped, malformed)


async def run_live(sender, env: Mapping[str, str], db: Database, stop: asyncio.Event) -> None:
    topic = get_str("KAFKA_TOPIC_LIVE", "sismos.live", env)
    url = get_str("USGS_FEED_URL", env=env)
    interval = get_int("POLL_SECONDS", 60, minimum=10, env=env)  # nunca más rápido que 10 s: cortesía con USGS
    timeout = get_int("HTTP_TIMEOUT_SECONDS", 15, minimum=1, env=env)
    raw_dir = Path(get_str("RAW_DATA_DIR", "/app/data/raw", env)) / "live"
    retention = get_int("RAW_RETENTION_DAYS", 14, minimum=0, env=env)

    async with httpx.AsyncClient(
        timeout=timeout, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, follow_redirects=True
    ) as http:
        while not stop.is_set():
            cycle_started = asyncio.get_running_loop().time()
            try:
                await run_cycle(
                    http=http, sender=sender, db=db, topic=topic, url=url, raw_dir=raw_dir, retention_days=retention
                )
            except (psycopg.Error, OSError) as error:
                log.error("cycle aborted (will retry next interval): %s", error)
            except Exception as error:  # noqa: BLE001 - un ciclo fallido nunca debe parar el productor (p. ej. Kafka caído)
                log.exception("cycle failed (will retry next interval): %s", error)
            remaining = max(1.0, interval - (asyncio.get_running_loop().time() - cycle_started))
            try:
                await asyncio.wait_for(stop.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                pass


def install_stop_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
