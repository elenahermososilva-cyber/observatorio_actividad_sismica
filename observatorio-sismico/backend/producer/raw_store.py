"""Conservación de las respuestas originales de USGS, con deduplicación y retención.

- El feed `all_day.geojson` incluye `metadata.generated`, que cambia en cada consulta aunque no haya novedades.
  Por eso el hash de contenido se calcula sobre las `features` y NO sobre los bytes: dos respuestas con los mismos
  eventos tienen el mismo hash y solo se guarda la primera (se evita acumular copias idénticas).
- Los originales se guardan comprimidos (gzip) e íntegros, tal como llegaron.
- La retención borra los archivos más antiguos que N días; el registro de consultas (ingest.extraction_log) no se borra.
"""

import gzip
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path


def content_hash(features: list) -> str:
    canonical = json.dumps(features, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def raw_path_for(directory: Path, fetched_at: datetime) -> Path:
    return directory / f"{fetched_at:%Y}" / f"{fetched_at:%m}" / f"{fetched_at:%d}" / f"{fetched_at:%H%M%S}.geojson.gz"


def save_raw(directory: Path, body: bytes, fetched_at: datetime) -> Path:
    """Escritura atómica (archivo temporal + rename): nunca queda un original a medias."""
    path = raw_path_for(directory, fetched_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(gzip.compress(body, compresslevel=6))
    os.replace(temp, path)
    return path


def read_raw(path: Path) -> bytes:
    return gzip.decompress(path.read_bytes())


def prune(directory: Path, days: int, now: float | None = None) -> int:
    """Borra originales (.geojson.gz) con más de `days` días y los directorios vacíos. Devuelve cuántos borró."""
    if days < 0 or not directory.is_dir():
        return 0
    limit = (time.time() if now is None else now) - days * 86400
    removed = 0
    for path in directory.rglob("*.geojson.gz"):
        if path.stat().st_mtime < limit:
            path.unlink()
            removed += 1
    for folder in sorted((p for p in directory.rglob("*") if p.is_dir()), reverse=True):
        try:
            folder.rmdir()  # solo prospera si está vacío
        except OSError:
            pass
    return removed
