"""Latencia real de la API sobre los datos reales (sin datos sintéticos). Solo biblioteca estándar; se ejecuta en el anfitrión.

    python scripts/medir_api.py [url-base]        # por defecto http://127.0.0.1:8000

Mide, para cada petición, 30 repeticiones de extremo a extremo (cliente → API → PostgreSQL → respuesta) y resume mediana,
p95 y tamaño de la respuesta. Escribe docs/evidencias/api-latencia.json.
"""

import json
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parents[1] / "docs" / "evidencias" / "api-latencia.json"
REPEATS = 30
CASES = {
    "salud": "/api/salud?mode=live",
    "eventos_live_24h": "/api/eventos?mode=live",
    "eventos_live_todo_min_mag_4": "/api/eventos?mode=live&start=2026-11-01T00:00:00Z&min_mag=4",
    "eventos_live_pais_USA": "/api/eventos?mode=live&start=2026-11-01T00:00:00Z&country_id=USA",
    "estadisticas_live_24h": "/api/estadisticas?mode=live",
    "estadisticas_live_min_mag_4": "/api/estadisticas?mode=live&min_mag=4&start=2026-11-17T00:00:00Z",
    "estadisticas_replay_2025": "/api/estadisticas?mode=replay&start=2025-01-01T00:00:00Z&end=2025-02-01T00:00:00Z",
}


def fetch(path: str) -> tuple[float, int, int]:
    request = urllib.request.Request(BASE + path, headers={"ngrok-skip-browser-warning": "1"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    return time.perf_counter() - t0, response.status, len(body)


results = {}
for name, path in CASES.items():
    fetch(path)  # calentamiento (planes, caché de conexión)
    times, size, status = [], 0, 0
    for _ in range(REPEATS):
        elapsed, status, size = fetch(path)
        times.append(elapsed * 1000)
    times.sort()
    results[name] = {"ruta": path, "estado_http": status, "bytes": size, "mediana_ms": round(statistics.median(times), 1),
                     "p95_ms": round(times[int(0.95 * len(times)) - 1], 1), "max_ms": round(times[-1], 1), "repeticiones": REPEATS}
    print(f"{name:34s} {results[name]['mediana_ms']:8.1f} ms (p95 {results[name]['p95_ms']} ms, {size:,} bytes)")
OUT.write_text(json.dumps({"generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"), "base": BASE,
                           "nota": "extremo a extremo en el mismo equipo, sin pasar por el túnel", "resultados": results},
                          indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
