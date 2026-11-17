"""Lógica pura del histórico (sin red ni dependencias externas): intervalos, planificación, reutilización y lectura.

La usan `history_download.py` (descarga) y `replay.py` (reproducción). Al no importar httpx se puede probar en el host.
"""

import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_RESULTS = 20_000  # límite de resultados por consulta de USGS
MANIFEST = "manifest.json"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


@dataclass(frozen=True)
class Interval:
    start: datetime  # inclusivo (UTC)
    end: datetime  # nominalmente exclusivo; USGS puede incluir también el extremo

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError("interval start must be before end")

    @property
    def seconds(self) -> int:
        return int((self.end - self.start).total_seconds())


def month_intervals(year: int) -> list[tuple[str, Interval]]:
    out = []
    for month in range(1, 13):
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
        out.append((f"{year}-{month:02d}", Interval(start, end)))
    return out


def split_interval(interval: Interval) -> tuple[Interval, Interval]:
    half = interval.seconds // 2
    if half < 1:
        raise ValueError(f"cannot split an interval shorter than 2 s: {interval}")
    middle = interval.start + timedelta(seconds=half)
    return Interval(interval.start, middle), Interval(middle, interval.end)


def query_params(interval: Interval, min_magnitude: float, **extra) -> dict:
    return {
        "format": "geojson",
        "starttime": interval.start.strftime(TIME_FORMAT),
        "endtime": interval.end.strftime(TIME_FORMAT),
        "minmagnitude": f"{min_magnitude:g}",
        "eventtype": "earthquake",
        "orderby": "time-asc",
        **extra,
    }


async def plan_intervals(
    interval: Interval, count: Callable[[Interval], Awaitable[int]], limit: int = MAX_RESULTS
) -> list[tuple[Interval, int]]:
    """Subdivide hasta que cada intervalo tenga como máximo `limit` resultados. Devuelve (intervalo, count)."""
    total = await count(interval)
    if total <= limit:
        return [(interval, total)]
    first, second = split_interval(interval)
    return await plan_intervals(first, count, limit) + await plan_intervals(second, count, limit)


def file_name(interval: Interval, label: str, whole_month: bool) -> str:
    if whole_month:
        return f"{label}.geojson"
    return f"{label}_{interval.start:%Y%m%dT%H%M%S}_{interval.end:%Y%m%dT%H%M%S}.geojson"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def load_manifest(directory: Path) -> dict:
    path = directory / MANIFEST
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"months": {}}


def month_is_reusable(directory: Path, month: dict | None) -> bool:
    """Un mes se reutiliza solo si está completo y TODOS sus archivos existen con el SHA-256 registrado."""
    if not month or not month.get("complete"):
        return False
    return all(
        (directory / q["file"]).is_file() and sha256_file(directory / q["file"]) == q["sha256"]
        for q in month["queries"]
    )


def iter_unique_features(directory: Path) -> tuple[list[dict], int]:
    """Todos los eventos del histórico deduplicados por `id` (gana el mayor `updated`), ordenados por tiempo.

    Devuelve (eventos, duplicados eliminados)."""
    best: dict[str, dict] = {}
    duplicates = 0
    for path in sorted(directory.glob("*.geojson")):
        for feature in json.loads(path.read_text(encoding="utf-8"))["features"]:
            event_id = feature.get("id")
            if event_id in best:
                duplicates += 1
                if feature["properties"].get("updated", 0) <= best[event_id]["properties"].get("updated", 0):
                    continue
            best[event_id] = feature
    ordered = sorted(best.values(), key=lambda f: (f["properties"].get("time", 0), f["id"]))
    return ordered, duplicates
