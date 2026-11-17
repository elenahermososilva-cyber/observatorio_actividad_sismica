"""Descarga del histórico de USGS (API FDSN) por intervalos, con registro de procedencia.

Uso (una vez; después se reutilizan los archivos):
    docker compose run --rm --no-deps producer python -m backend.producer.history_download [--year 2025] [--min-magnitude 4]

Reglas del enunciado §4.2:
- El año se divide en meses. Antes de descargar cada intervalo se consulta `count`; si supera el máximo de
  20.000 resultados se subdivide por la mitad, recursivamente. NUNCA se trunca en silencio.
- Un intervalo cuya respuesta alcance el máximo se considera truncado y se subdivide igualmente.
- Los extremos temporales de la fuente pueden incluirse en dos intervalos: al leer el histórico se deduplica por `id`
  conservando la versión con mayor `updated`.
- Se guardan los originales sin modificar y un `manifest.json` con cada consulta (URL, fecha de extracción, nº de
  registros, SHA-256, archivo). Reutilizable: un mes ya descargado y verificado no se vuelve a pedir.
- El histórico es una instantánea del catálogo en la fecha de extracción, no un registro de todas sus revisiones.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.common.logging_setup import configure_logging
from backend.producer.history_data import (
    MANIFEST, MAX_RESULTS, Interval, file_name, iter_unique_features, load_manifest, month_intervals,
    month_is_reusable, plan_intervals, query_params, sha256_file, split_interval, write_atomic,
)
from backend.producer.usgs import USER_AGENT, FeedError, fetch_count, fetch_feature_collection

log = logging.getLogger("history")

FDSN_QUERY = "https://earthquake.usgs.gov/fdsnws/event/1/query"
FDSN_COUNT = "https://earthquake.usgs.gov/fdsnws/event/1/count"


async def download_year(
    client: httpx.AsyncClient,
    directory: Path,
    year: int,
    min_magnitude: float,
    *,
    pause: float = 1.0,
    sleep=asyncio.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(directory)
    manifest["dataset"] = {
        "source": "USGS FDSN Event Web Service", "query_url": FDSN_QUERY, "year": year,
        "min_magnitude": min_magnitude, "event_type": "earthquake", "scope": "world", "format": "geojson",
        "max_results_per_query": MAX_RESULTS,
    }
    manifest.setdefault("months", {})

    for label, month in month_intervals(year):
        if month_is_reusable(directory, manifest["months"].get(label)):
            log.info("%s: reutilizado (archivos verificados por SHA-256), no se vuelve a descargar", label)
            continue

        async def count(interval: Interval) -> int:
            await sleep(pause)
            params = {k: v for k, v in query_params(interval, min_magnitude).items() if k not in ("format", "orderby")}
            return await fetch_count(client, FDSN_COUNT, params)

        plan = await plan_intervals(month, count)
        queries = []
        for interval, expected in plan:
            pending = [(interval, expected)]
            while pending:  # un intervalo cuya respuesta toque el máximo se trata como truncado y se subdivide
                current, current_count = pending.pop(0)
                await sleep(pause)
                params = query_params(current, min_magnitude)
                result = await fetch_feature_collection(client, FDSN_QUERY, params)
                if len(result.features) >= MAX_RESULTS:
                    log.warning("%s: %d resultados alcanzan el máximo; se subdivide en lugar de truncar", label, len(result.features))
                    first, second = split_interval(current)
                    pending[:0] = [(first, -1), (second, -1)]
                    continue
                name = file_name(current, label, whole_month=(current == month))
                write_atomic(directory / name, result.body)
                queries.append({
                    "url": str(httpx.URL(FDSN_QUERY, params=params)),
                    "start": current.start.isoformat(), "end": current.end.isoformat(),
                    "retrieved_at": now().isoformat(),
                    "count_reported": current_count if current_count >= 0 else None,
                    "features_received": len(result.features),
                    "bytes": len(result.body), "sha256": hashlib.sha256(result.body).hexdigest(),
                    "latency_ms": result.latency_ms, "file": name,
                })
                if current_count >= 0 and current_count != len(result.features):
                    log.warning("%s: el catálogo cambió entre count (%d) y descarga (%d)", label, current_count, len(result.features))
                log.info("%s: %s → %d eventos (%d bytes)", label, name, len(result.features), len(result.body))
        manifest["months"][label] = {"complete": True, "subdivided": len(queries) > 1, "queries": queries}
        write_atomic(directory / MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))

    unique, duplicates = iter_unique_features(directory)
    manifest["summary"] = {
        "queries": sum(len(m["queries"]) for m in manifest["months"].values()),
        "features_received": sum(q["features_received"] for m in manifest["months"].values() for q in m["queries"]),
        "unique_events": len(unique), "duplicates_removed": duplicates,
        "completed_at": now().isoformat(),
        "note": "Instantánea del catálogo USGS en la fecha de extracción; no incluye revisiones pasadas.",
    }
    write_atomic(directory / MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
    return manifest


async def main_async(args: argparse.Namespace) -> int:
    configure_logging("history")
    directory = Path(args.out)
    async with httpx.AsyncClient(
        timeout=args.timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        try:
            manifest = await download_year(client, directory, args.year, args.min_magnitude, pause=args.pause)
        except FeedError as error:
            log.error("descarga interrumpida: %s (los meses completos se conservan; reejecuta para continuar)", error)
            return 1
    summary = manifest["summary"]
    log.info(
        "listo: %d consultas, %d eventos recibidos, %d únicos tras deduplicar (%d duplicados). Manifiesto: %s",
        summary["queries"], summary["features_received"], summary["unique_events"], summary["duplicates_removed"],
        directory / MANIFEST,
    )
    return 0


def main() -> int:
    default_out = Path(os.environ.get("RAW_DATA_DIR", "/app/data/raw")) / "historico"
    parser = argparse.ArgumentParser(description="Descarga mensual del catálogo USGS")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--min-magnitude", type=float, default=4.0)
    parser.add_argument("--out", default=str(default_out))
    parser.add_argument("--pause", type=float, default=1.0, help="segundos entre peticiones (cortesía con USGS)")
    parser.add_argument("--timeout", type=float, default=120.0)
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
