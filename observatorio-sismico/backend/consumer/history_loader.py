"""Carga el histórico descargado (history_download) en el esquema `historico`.

Reutiliza EXACTAMENTE el procesamiento del consumidor (`handle_record`): misma validación, mismo filtro de tipo
`earthquake` con cuarentena y motivo, mismas reglas de calidad y misma atribución de país. Lo único distinto es el
origen (un archivo en lugar de un topic de Kafka) y el modo (`historical`, escribe solo en `historico`).

- Idempotente: cargarlo dos veces no cambia nada (todo es DUPLICATE). Los eventos repetidos en los extremos de dos
  intervalos se resuelven por versión, como cualquier otro mensaje.
- Referencia al original: el rechazo guarda `file:<archivo>` y la posición dentro del archivo en las columnas
  kafka_topic / kafka_offset de la cuarentena (no hay Kafka aquí; el esquema exige una referencia estable).
- Es una instantánea del catálogo en la fecha de extracción, no un registro de todas las revisiones pasadas.

Uso:
    docker compose run --rm --no-deps consumer python -m backend.consumer.history_loader
"""

import argparse
import asyncio
import json
import logging
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from backend.common.config import database_url, get_str
from backend.common.logging_setup import configure_logging
from backend.consumer.consumer import handle_record
from backend.consumer.geo import CountryIndex
from backend.db.quarantine import KafkaRef
from backend.producer.envelope import build_envelope
from backend.producer.schema import IngestionMode

log = logging.getLogger("history_loader")
MODE = "historical"
SOURCE = "usgs-catalog"


async def load_history(conn: psycopg.AsyncConnection, directory: Path, geo: CountryIndex, *, progress_every: int = 2000) -> dict:
    files = sorted(directory.glob("*.geojson"))
    if not files:
        raise FileNotFoundError(f"no hay histórico en {directory}; descárgalo con history_download")
    loaded_at = datetime.now(timezone.utc)
    decisions: Counter[str] = Counter()
    rejections: Counter[str] = Counter()
    started = time.monotonic()
    processed = 0
    for path in files:
        features = json.loads(path.read_text(encoding="utf-8"))["features"]
        for position, feature in enumerate(features):
            envelope = build_envelope(
                feature, mode=IngestionMode.HISTORICAL, source=SOURCE, synthetic_flag=False, ingested_at=loaded_at
            )
            result = await handle_record(conn, envelope.value, KafkaRef(f"file:{path.name}", 0, position), MODE, geo)
            if result.rejection is not None:
                rejections[result.rejection.reason.value] += 1
            else:
                decisions[result.decision.value.upper()] += 1
            processed += 1
            if processed % progress_every == 0:
                log.info("%d procesados (%.0f/s)...", processed, processed / (time.monotonic() - started))
    elapsed = time.monotonic() - started
    return {
        "files": len(files), "processed": processed, "decisions": dict(decisions), "rejections": dict(rejections),
        "seconds": round(elapsed, 1), "per_second": round(processed / elapsed) if elapsed else None,
    }


async def main_async(args: argparse.Namespace) -> int:
    configure_logging("history_loader")
    # handle_record registra cada NEW en INFO: con 18.000 eventos ahogaría el resumen. Los rechazos (WARNING) se mantienen.
    logging.getLogger("consumer").setLevel(logging.WARNING)
    geo = CountryIndex.from_file(Path(get_str("COUNTRIES_GEOJSON", "/app/data/paises.geojson")))
    async with await psycopg.AsyncConnection.connect(database_url(os.environ), autocommit=True) as conn:
        try:
            report = await load_history(conn, Path(args.dir), geo)
        except FileNotFoundError as error:
            log.error("%s", error)
            return 2
    log.info("carga completa: %s", json.dumps(report, ensure_ascii=False))
    return 0


def main() -> int:
    default_dir = Path(os.environ.get("RAW_DATA_DIR", "/app/data/raw")) / "historico"
    parser = argparse.ArgumentParser(description="Carga el histórico USGS descargado en el esquema `historico`")
    parser.add_argument("--dir", default=str(default_dir))
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
