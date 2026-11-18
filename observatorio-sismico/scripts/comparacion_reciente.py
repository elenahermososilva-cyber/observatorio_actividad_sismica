"""Comparación equivalente: periodo reciente de 2026 (catálogo FDSN) frente al histórico 2025.

Responde a la pregunta del enunciado («¿dónde se registra actividad y cómo se compara con un periodo histórico
equivalente?») con una muestra de varias semanas, no con un único día del feed. Mismos filtros que el histórico:
mundo, M ≥ 4, `eventtype=earthquake`, misma fuente (API FDSN de USGS) y misma regla de país (punto en polígono,
`backend.consumer.geo.CountryIndex`).

Solo lectura sobre PostgreSQL (el histórico 2025 ya cargado y el feed live); no escribe en la base. Guarda los
originales descargados en data/raw/reciente/ (con manifest.json) y el resultado en
docs/evidencias/comparacion-reciente.json. Se ejecuta en la imagen `api`:

    docker compose run --rm --no-deps -v "${PWD}/scripts:/app/scripts" -v "${PWD}/data/raw:/app/data/raw" \
        -v "${PWD}/docs/evidencias:/app/docs/evidencias" -e PYTHONPATH=/app api python scripts/comparacion_reciente.py

Variables opcionales: RECIENTE_START (por defecto 2026-10-01), RECIENTE_END (exclusivo, por defecto 2026-11-18),
RECIENTE_CORTE (fecha que separa el tramo «maduro» del más reciente; por defecto 2026-10-29).

Segunda instantánea (para medir cuánto se completa el catálogo con el tiempo): RECIENTE_SNAPSHOT=reciente-2
descarga el mismo periodo en data/raw/reciente-2/ y compara su serie diaria con la de data/raw/reciente/.
"""

import asyncio
import hashlib
import json
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import psycopg

from backend.consumer.geo import CountryIndex
from backend.producer.history_data import Interval, query_params, write_atomic
from backend.producer.usgs import USER_AGENT, fetch_count, fetch_feature_collection

FDSN_QUERY = "https://earthquake.usgs.gov/fdsnws/event/1/query"
FDSN_COUNT = "https://earthquake.usgs.gov/fdsnws/event/1/count"
MIN_MAG = 4.0
DAY_MS = 86_400_000
SNAPSHOT = os.environ.get("RECIENTE_SNAPSHOT", "reciente")
RAW_ROOT = Path(os.environ.get("RAW_DATA_DIR", "/app/data/raw"))
RAW = RAW_ROOT / SNAPSHOT
OUT = Path(f"/app/docs/evidencias/comparacion-{SNAPSHOT}.json")
COUNTRIES = Path(os.environ.get("COUNTRIES_GEOJSON", "/app/data/paises.geojson"))
START = datetime.fromisoformat(os.environ.get("RECIENTE_START", "2026-10-01T00:00:00+00:00"))
END = datetime.fromisoformat(os.environ.get("RECIENTE_END", "2026-11-18T00:00:00+00:00"))
CUT = datetime.fromisoformat(os.environ.get("RECIENTE_CORTE", "2026-10-29T00:00:00+00:00"))
NO_COUNTRY = "Sin país asignado"


def month_chunks(start: datetime, end: datetime) -> list[Interval]:
    out, cur = [], start
    while cur < end:
        nxt = datetime(cur.year + (cur.month == 12), cur.month % 12 + 1, 1, tzinfo=timezone.utc)
        out.append(Interval(cur, min(nxt, end)))
        cur = min(nxt, end)
    return out


def read_snapshot(directory: Path) -> tuple[list[dict], dict]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    best: dict[str, dict] = {}
    for query in manifest["queries"]:
        for f in json.loads((directory / query["file"]).read_text(encoding="utf-8"))["features"]:
            if f["properties"].get("type") != "earthquake":
                continue
            old = best.get(f["id"])
            if old is None or (f["properties"].get("updated") or 0) > (old["properties"].get("updated") or 0):
                best[f["id"]] = f
    start_ms, end_ms = int(START.timestamp() * 1000), int(END.timestamp() * 1000)
    features = [f for f in best.values() if start_ms <= f["properties"]["time"] < end_ms and (f["properties"].get("mag") or -9) >= MIN_MAG]
    return features, manifest


async def download() -> tuple[list[dict], dict]:
    """Descarga (o reutiliza) los intervalos mensuales del periodo, con manifiesto. Nunca trunca en silencio."""
    RAW.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    period_key = f"{START.isoformat()}/{END.isoformat()}"
    if manifest.get("period") != period_key:
        manifest = {"period": period_key, "queries": []}
    if not manifest["queries"]:
        async with httpx.AsyncClient(timeout=60, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            for chunk in month_chunks(START, END):
                params = query_params(chunk, MIN_MAG)
                expected = await fetch_count(client, FDSN_COUNT, {k: v for k, v in params.items() if k not in ("format", "orderby")})
                if expected >= 20_000:
                    raise SystemExit(f"{chunk}: {expected} resultados ≥ 20.000; habría que subdividir")
                await asyncio.sleep(1)
                result = await fetch_feature_collection(client, FDSN_QUERY, params)
                name = f"{chunk.start:%Y-%m-%d}_{chunk.end:%Y-%m-%d}.geojson"
                write_atomic(RAW / name, result.body)
                manifest["queries"].append({
                    "url": str(httpx.URL(FDSN_QUERY, params=params)), "start": chunk.start.isoformat(),
                    "end": chunk.end.isoformat(), "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "count_reported": expected, "features_received": len(result.features), "bytes": len(result.body),
                    "sha256": hashlib.sha256(result.body).hexdigest(), "file": name, "latency_ms": result.latency_ms,
                })
                await asyncio.sleep(1)
        manifest["note"] = "Instantánea del catálogo USGS en la fecha de extracción; los días más recientes pueden completarse después."
        write_atomic(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
    return read_snapshot(RAW)


def describe(counts: list[int]) -> dict:
    s = sorted(counts)
    q = statistics.quantiles(s, n=4) if len(s) > 1 else [s[0]] * 3
    return {"dias": len(s), "eventos": sum(s), "media": round(statistics.mean(s), 2), "mediana": statistics.median(s),
            "q1": q[0], "q3": q[2], "min": s[0], "max": s[-1]}


def percentile_rank(value: float, population: list[float]) -> float:
    below = sum(1 for p in population if p < value)
    equal = sum(1 for p in population if p == value)
    return round(100 * (below + 0.5 * equal) / len(population), 1)


def windows(daily: list[int], length: int) -> list[int]:
    """Sumas de todas las ventanas de `length` días consecutivos (paso de un día)."""
    acc, out = sum(daily[:length]), []
    out.append(acc)
    for i in range(length, len(daily)):
        acc += daily[i] - daily[i - length]
        out.append(acc)
    return out


def main() -> None:
    features, manifest = asyncio.run(download())
    index = CountryIndex.from_file(COUNTRIES)
    catalog = {f["properties"]["ADM0_A3"]: f["properties"] for f in json.loads(COUNTRIES.read_text(encoding="utf-8"))["features"]}

    n_days = (END - START).days
    start_ms = int(START.timestamp() * 1000)
    daily = [0] * n_days
    by_sub, by_country, depth = Counter(), Counter(), Counter()
    ambiguous = 0
    for f in features:
        lon, lat, dep = f["geometry"]["coordinates"][:3]
        daily[(f["properties"]["time"] - start_ms) // DAY_MS] += 1
        att = index.locate(lon, lat)
        ambiguous += att.ambiguous
        sub = catalog[att.country_id]["SUBREGION"] if att.country_id else NO_COUNTRY
        by_sub[sub] += 1
        by_country[catalog[att.country_id]["NAME_ES"] if att.country_id else NO_COUNTRY] += 1
        depth["<70" if dep is not None and dep < 70 else "70-300" if dep is not None and dep < 300 else ">=300" if dep is not None else "ND"] += 1

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        y0 = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        rows = conn.execute(
            "SELECT (e.time_ms - %s) / %s AS d, coalesce(c.subregion, %s) AS sub, e.mag "
            "FROM historico.event_current e LEFT JOIN ref.dim_country c USING (country_id) WHERE e.mag >= %s",
            (y0, DAY_MS, NO_COUNTRY, MIN_MAG)).fetchall()
        hist_daily = [0] * 365
        hist_band = {"M4.0-4.4": [0] * 365, "M>=4.5": [0] * 365}
        hist_sub_daily: dict[str, list[int]] = defaultdict(lambda: [0] * 365)
        for d, sub, mag in rows:
            hist_daily[d] += 1
            hist_band["M4.0-4.4" if mag < 4.5 else "M>=4.5"][d] += 1
            hist_sub_daily[sub][d] += 1
        hist_depth = dict(conn.execute(
            "SELECT CASE WHEN depth_km < 70 THEN '<70' WHEN depth_km < 300 THEN '70-300' ELSE '>=300' END, count(*) "
            "FROM historico.event_current WHERE mag >= %s GROUP BY 1", (MIN_MAG,)).fetchall())
        # Mismo periodo del calendario en 2025 (estacionalidad descartada, pero es la comparación más directa).
        same_start = (datetime(2025, START.month, START.day, tzinfo=timezone.utc) - datetime(2025, 1, 1, tzinfo=timezone.utc)).days
        # Feed live frente al catálogo en los días UTC completos que cubre el feed.
        live_days = []
        for day in ("2026-11-17",):
            d0 = int(datetime.fromisoformat(day + "T00:00:00+00:00").timestamp() * 1000)
            live = {r[0]: r[1] for r in conn.execute(
                "SELECT event_id, mag FROM live.event_current WHERE time_ms >= %s AND time_ms < %s AND mag >= %s",
                (d0, d0 + DAY_MS, MIN_MAG))}
            live_all = {r[0]: r[1] for r in conn.execute(
                "SELECT event_id, mag FROM live.event_current WHERE time_ms >= %s AND time_ms < %s", (d0, d0 + DAY_MS))}
            cat = {f["id"]: f["properties"]["mag"] for f in features if d0 <= f["properties"]["time"] < d0 + DAY_MS}
            ids_cat = {f["id"]: f["properties"].get("ids", "") for f in features if d0 <= f["properties"]["time"] < d0 + DAY_MS}
            # USGS puede cambiar el id preferido: se considera el mismo evento si el id live aparece en `ids` del catálogo.
            matched = {c for c in cat if c in live_all or any(f",{l}," in ids_cat[c] for l in live_all)}
            live_days.append({
                "dia": day, "feed_live_M4": len(live), "catalogo_M4": len(cat),
                "catalogo_M4_vistos_en_el_feed": len(matched),
                "catalogo_M4_vistos_en_el_feed_con_M_menor_de_4": sum(1 for c in matched if c in live_all and live_all[c] is not None and live_all[c] < MIN_MAG),
                "catalogo_M4_nunca_vistos_en_el_feed": len(cat) - len(matched),
                "feed_M4_que_el_catalogo_no_tiene_como_M4": sum(1 for l in live if l not in cat),
            })

    n = len(features)
    hist_total = sum(hist_daily)

    # Subperiodos (tramo «maduro» frente al más reciente) y bandas de magnitud, cada uno frente a las ventanas
    # de 2025 de su misma duración. Separa un posible efecto de publicación tardía de la actividad real.
    band_daily = {"M4.0-4.4": [0] * n_days, "M>=4.5": [0] * n_days}
    for f in features:
        band_daily["M4.0-4.4" if f["properties"]["mag"] < 4.5 else "M>=4.5"][(f["properties"]["time"] - start_ms) // DAY_MS] += 1
    cut = (CUT - START).days
    subperiods = {}
    for label, a, b in ((f"{START:%Y-%m-%d} a {CUT - timedelta(days=1):%Y-%m-%d}", 0, cut),
                        (f"{CUT:%Y-%m-%d} a {END - timedelta(days=1):%Y-%m-%d}", cut, n_days),
                        ("periodo completo", 0, n_days)):
        length = b - a
        entry = {"dias": length}
        for band, series, hist in (("todas", daily, hist_daily), ("M4.0-4.4", band_daily["M4.0-4.4"], hist_band["M4.0-4.4"]),
                                   ("M>=4.5", band_daily["M>=4.5"], hist_band["M>=4.5"])):
            total = sum(series[a:b])
            w = windows(hist, length)
            entry[band] = {"total": total, "media_dia": round(total / length, 1), "media_dia_2025": round(sum(hist) / 365, 1),
                           "ventanas_2025": {"min": min(w), "mediana": statistics.median(w), "max": max(w)},
                           "percentil_en_2025": percentile_rank(total, w)}
        subperiods[label] = entry

    # Mayores eventos y peso de la secuencia principal (radio de 300 km alrededor del mayor evento).
    largest = sorted(features, key=lambda f: -f["properties"]["mag"])[:5]
    main_lon, main_lat = largest[0]["geometry"]["coordinates"][:2]

    def near_main(f):
        lon, lat = f["geometry"]["coordinates"][:2]
        return ((lon - main_lon) * cos_lat) ** 2 + (lat - main_lat) ** 2 <= (300 / 111.2) ** 2

    import math
    cos_lat = math.cos(math.radians(main_lat))
    rest = [f for f in features if not near_main(f)]
    rest_no_country = sum(1 for f in rest if index.locate(*f["geometry"]["coordinates"][:2]).country_id is None)
    main_sequence = {
        "mayores_eventos": [{"id": f["id"], "time": datetime.fromtimestamp(f["properties"]["time"] / 1000, timezone.utc).isoformat(timespec="seconds"),
                             "mag": f["properties"]["mag"], "magType": f["properties"]["magType"], "place": f["properties"]["place"]} for f in largest],
        "eventos_a_menos_de_300_km_del_mayor": n - len(rest),
        "sin_pais_excluyendo_esa_zona": {"sin_pais": rest_no_country, "eventos": len(rest), "pct": round(100 * rest_no_country / len(rest), 1)},
    }

    # Comparación con una instantánea anterior del mismo periodo: cuánto se ha completado el catálogo.
    snapshot_change = None
    if SNAPSHOT != "reciente" and (RAW_ROOT / "reciente" / "manifest.json").exists():
        old, old_manifest = read_snapshot(RAW_ROOT / "reciente")
        old_daily = [0] * n_days
        for f in old:
            old_daily[(f["properties"]["time"] - start_ms) // DAY_MS] += 1
        snapshot_change = {
            "instantanea_anterior": old_manifest["queries"][0]["retrieved_at"],
            "instantanea_actual": manifest["queries"][0]["retrieved_at"],
            "eventos_anterior": len(old), "eventos_actual": n,
            "por_dia": [{"dia": f"{START + timedelta(days=i):%Y-%m-%d}", "antes": old_daily[i], "ahora": daily[i], "diferencia": daily[i] - old_daily[i]}
                        for i in range(n_days) if daily[i] != old_daily[i]],
        }
    hist_windows = windows(hist_daily, n_days)
    recent_total = sum(daily)
    # Días finales: ¿se ve el efecto de publicación tardía? (media de los 7 últimos días frente al resto)
    tail, head = daily[-7:], daily[:-7]
    subregions = []
    for sub, count in by_sub.most_common():
        h = hist_sub_daily.get(sub, [0] * 365)
        w = windows(h, n_days)
        subregions.append({
            "subregion": sub, "reciente": count, "pct_reciente": round(100 * count / n, 1),
            "pct_2025": round(100 * sum(h) / hist_total, 1),
            "esperado_con_la_tasa_media_2025": round(sum(h) / 365 * n_days, 1),
            "ventanas_2025_misma_duracion": {"min": min(w), "mediana": statistics.median(w), "max": max(w)},
            "percentil_en_2025": percentile_rank(count, w),
        })
    for sub in hist_sub_daily:
        if sub not in by_sub:
            w = windows(hist_sub_daily[sub], n_days)
            subregions.append({"subregion": sub, "reciente": 0, "pct_reciente": 0.0, "pct_2025": round(100 * sum(hist_sub_daily[sub]) / hist_total, 1),
                               "esperado_con_la_tasa_media_2025": round(sum(hist_sub_daily[sub]) / 365 * n_days, 1),
                               "ventanas_2025_misma_duracion": {"min": min(w), "mediana": statistics.median(w), "max": max(w)},
                               "percentil_en_2025": percentile_rank(0, w)})

    out = {
        "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filtros": {"fuente": "USGS FDSN event (misma API que el histórico)", "ambito": "mundo", "min_mag": MIN_MAG,
                    "tipo": "earthquake", "pais": "punto en polígono (CountryIndex, Natural Earth 1:110M)"},
        "periodo_reciente": {"inicio": START.isoformat(), "fin_exclusivo": END.isoformat(), "dias": n_days},
        "procedencia": {"directorio": f"data/raw/{SNAPSHOT}", "consultas": manifest["queries"]},
        "reciente": {**describe(daily), "serie_diaria": daily, "puntos_ambiguos_en_frontera": ambiguous,
                     "profundidad": dict(depth), "top_paises": by_country.most_common(10)},
        "historico_2025": {**describe(hist_daily), "profundidad": hist_depth},
        "mismo_periodo_2025": describe(hist_daily[same_start:same_start + n_days]),
        "ventanas_2025_misma_duracion": {
            "n_ventanas": len(hist_windows), "min": min(hist_windows), "mediana": statistics.median(hist_windows),
            "max": max(hist_windows), "percentil_del_total_reciente": percentile_rank(recent_total, hist_windows),
            "nota": "Distribución de los totales de todas las ventanas de 2025 con la misma duración que el periodo reciente (paso de un día). Tiene en cuenta que las réplicas agrupan eventos: compara el total reciente con lo que 2025 produjo realmente en periodos iguales.",
        },
        "efecto_cola_final": {"media_ultimos_7_dias": round(statistics.mean(tail), 2), "media_resto": round(statistics.mean(head), 2),
                              "nota": "Si los últimos días tienen menos eventos, puede deberse a publicación tardía: el catálogo de los días recientes aún puede completarse."},
        "subperiodos_y_bandas": subperiods,
        "secuencia_principal": main_sequence,
        "subregiones": subregions,
        "feed_live_vs_catalogo": live_days,
        "cambio_entre_instantaneas": snapshot_change,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("periodo_reciente", "reciente", "historico_2025", "mismo_periodo_2025",
                                          "ventanas_2025_misma_duracion", "efecto_cola_final", "subperiodos_y_bandas",
                                          "secuencia_principal", "feed_live_vs_catalogo", "cambio_entre_instantaneas")},
                     indent=1, ensure_ascii=False))
    for s in subregions:
        print(f"{s['subregion'][:28]:28s} {s['reciente']:5d} ({s['pct_reciente']:5.1f} % vs {s['pct_2025']:5.1f} %)  esperado {s['esperado_con_la_tasa_media_2025']:7.1f}  ventanas2025 {s['ventanas_2025_misma_duracion']}  pct {s['percentil_en_2025']}")


if __name__ == "__main__":
    main()
