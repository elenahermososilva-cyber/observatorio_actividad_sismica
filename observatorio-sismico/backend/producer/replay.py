"""Reproducción acelerada de una selección histórica (enunciado §11).

- Lee el histórico descargado (history_download.py), selecciona eventos ordenados por fecha y los publica en el
  topic `sismos.replay` a un ritmo acelerado (uno cada REPLAY_INTERVAL_SECONDS).
- Conserva el tiempo ORIGINAL del evento (`properties.time`, intacto) y añade el de reproducción (`replay_at`).
  No se cambian fechas para que los puntos aparezcan «hoy»: la vista de reproducción consulta el periodo histórico.
- Usa el mismo consumidor que el modo live: el topic decide el esquema aislado (`replay`), nada se mezcla con datos live.
- Inyecta tres casos controlados, claramente etiquetados, para demostrar la idempotencia:
    duplicate  mismo mensaje otra vez                          → el consumidor responde DUPLICATE
    revision   mismo evento con `updated` posterior y otra mag → REVISION (cambia el estado actual)
    stale      la versión original después de la revisión      → STALE (no sustituye a la más reciente)
  Las revisiones inyectadas llevan `synthetic_flag=true` y `source="replay-injected"`: son datos modificados por
  nosotros, no de USGS, y no deben confundirse con datos reales.
"""

import asyncio
import copy
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.common.config import get_int, get_str
from backend.producer.envelope import build_envelope
from backend.producer.history_data import iter_unique_features
from backend.producer.schema import IngestionMode

log = logging.getLogger("producer.replay")

SOURCE_HISTORY = "usgs-history"
SOURCE_INJECTED = "replay-injected"
REVISION_DELTA_MS = 60_000
REVISION_MAG_DELTA = 0.2


@dataclass(frozen=True)
class Planned:
    label: str  # original | duplicate | revision | stale
    feature: dict
    source: str
    synthetic_flag: bool
    expected: str  # decisión esperada del consumidor


def select_events(features: list[dict], start_ms: int, min_mag: float, count: int) -> list[dict]:
    """Primeros `count` terremotos con magnitud >= min_mag desde `start_ms`, por orden de ocurrencia."""
    chosen = []
    for feature in sorted(features, key=lambda f: (f["properties"].get("time", 0), f["id"])):
        props = feature["properties"]
        mag = props.get("mag")
        if (
            props.get("type") == "earthquake"
            and isinstance(mag, (int, float)) and not isinstance(mag, bool) and mag >= min_mag
            and props.get("time", -1) >= start_ms
        ):
            chosen.append(feature)
            if len(chosen) == count:
                break
    return chosen


def make_revision(feature: dict) -> dict:
    """Copia con `updated` posterior y magnitud algo mayor. El tiempo de ocurrencia no cambia."""
    revised = copy.deepcopy(feature)
    props = revised["properties"]
    props["updated"] = props["updated"] + REVISION_DELTA_MS
    props["mag"] = round(props["mag"] + REVISION_MAG_DELTA, 1)
    return revised


def build_plan(events: list[dict], inject_cases: bool = True) -> list[Planned]:
    plan = [Planned("original", f, SOURCE_HISTORY, False, "NEW") for f in events]
    if inject_cases and len(events) >= 2:
        plan.append(Planned("duplicate", events[0], SOURCE_HISTORY, False, "DUPLICATE"))
        plan.append(Planned("revision", make_revision(events[1]), SOURCE_INJECTED, True, "REVISION"))
        plan.append(Planned("stale", events[1], SOURCE_HISTORY, False, "STALE"))
    return plan


def parse_start(value: str) -> int:
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


async def run_replay(sender, env: Mapping[str, str], stop: asyncio.Event) -> int:
    topic = get_str("KAFKA_TOPIC_REPLAY", "sismos.replay", env)
    history = Path(get_str("RAW_DATA_DIR", "/app/data/raw", env)) / "historico"
    start_ms = parse_start(get_str("REPLAY_START", "2025-01-01T00:00:00Z", env))
    count = get_int("REPLAY_COUNT", 10, minimum=1, env=env)
    min_mag = float(get_str("REPLAY_MIN_MAG", "5.0", env))
    interval = float(get_str("REPLAY_INTERVAL_SECONDS", "2", env))
    inject = get_str("REPLAY_INJECT_CASES", "true", env).lower() == "true"

    if not any(history.glob("*.geojson")):
        log.error(
            "no hay histórico en %s; descárgalo antes: docker compose run --rm --no-deps producer "
            "python -m backend.producer.history_download", history,
        )
        return 2
    features, _ = await asyncio.to_thread(iter_unique_features, history)
    events = select_events(features, start_ms, min_mag, count)
    if not events:
        log.error("la selección está vacía (REPLAY_START/REPLAY_MIN_MAG demasiado restrictivos)")
        return 2

    plan = build_plan(events, inject)
    log.info(
        "REPRODUCCIÓN: %d mensajes (%d eventos históricos de %s a %s + casos inyectados), uno cada %.1fs → %s",
        len(plan), len(events), _fmt(events[0]), _fmt(events[-1]), interval, topic,
    )
    for index, item in enumerate(plan, 1):
        if stop.is_set():
            break
        now = datetime.now(timezone.utc)
        envelope = build_envelope(
            item.feature, mode=IngestionMode.REPLAY, source=item.source, synthetic_flag=item.synthetic_flag,
            ingested_at=now, replay_at=now,
        )
        await sender.send_and_wait(topic, value=envelope.value, key=envelope.key.encode("utf-8") if envelope.key else None)
        props = item.feature["properties"]
        log.info(
            "[%d/%d] %-9s %s M%s ocurrió %s UTC · reproducido %s · esperado: %s",
            index, len(plan), item.label, item.feature["id"], props.get("mag"),
            datetime.fromtimestamp(props["time"] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            now.strftime("%H:%M:%S"), item.expected,
        )
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    log.info("reproducción completa")
    return 0


def _fmt(feature: dict) -> str:
    return datetime.fromtimestamp(feature["properties"]["time"] / 1000, timezone.utc).strftime("%Y-%m-%d")
