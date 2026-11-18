"""Mediciones de complejidad, tiempo y memoria (ENUNCIADO §10), con tres o más tamaños de entrada.

Tres operaciones:
  A. Búsqueda de versiones por identificador: lista (secuencial) vs diccionario (hash) en Python, y PostgreSQL sin índice
     (Seq Scan) vs con el índice único (event_id, updated_ms) que usa el proyecto.
  B. Integración geográfica (punto en polígono): recorrido de los 177 polígonos por cada punto vs STRtree (el índice
     que usa el consumidor).
  C. Agregación por ventanas de una hora UTC: PostgreSQL sin índice vs con índice sobre `time_ms`, y agregar en la base
     vs traer las filas y agregar en Python.

DATOS SINTÉTICOS: todos los datos de esta prueba (identificadores `syn-N`, puntos aleatorios, tiempos repartidos en un
año) se generan aquí, se guardan solo en una base TEMPORAL llamada `bench_synthetic_*` que se elimina al terminar y NUNCA
se mezclan con los esquemas reales (demo, live, replay, historico). Las semillas son fijas.

    docker compose run --rm --no-deps -v "${PWD}/scripts:/app/scripts" -v "${PWD}/docs/evidencias:/app/docs/evidencias" \\
        -e EVIDENCE_DIR=/app/docs/evidencias -e PYTHONPATH=/app api python scripts/medir_complejidad.py

Escribe docs/evidencias/complejidad.json y complejidad.md. Ajustes opcionales: BENCH_QUICK=1 reduce los tamaños.
"""

import json
import os
import platform
import random
import statistics
import time
import tracemalloc
import uuid
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from backend.consumer.geo import CountryIndex

DB_URL = os.environ["DATABASE_URL"]
OUT = Path(os.environ.get("EVIDENCE_DIR", "/app/docs/evidencias"))
COUNTRIES = Path(os.environ.get("COUNTRIES_GEOJSON", "/app/data/paises.geojson"))
QUICK = os.environ.get("BENCH_QUICK") == "1"
REPEATS = 5
HOUR_MS = 3_600_000
YEAR_START = 1_735_689_600_000
YEAR_MS = 365 * 24 * HOUR_MS


def med(fn, repeats=REPEATS):
    runs = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        runs.append(time.perf_counter() - t0)
    return statistics.median(runs)


def peak_mib(fn):
    tracemalloc.start()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / 2**20


def equipment(conn):
    cpu = next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), platform.processor())
    mem = next((int(l.split()[1]) / 1024 for l in open("/proc/meminfo") if l.startswith("MemTotal")), None)
    import shapely
    return {
        "nota": "Mediciones dentro de un contenedor Docker (Docker Desktop sobre WSL2); el equipo anfitrión se documenta en la memoria.",
        "cpu_visible_en_contenedor": cpu, "nucleos_visibles": os.cpu_count(), "ram_visible_mib": round(mem) if mem else None,
        "python": platform.python_version(), "shapely": shapely.__version__,
        "postgresql": conn.execute("SHOW server_version").fetchone()[0],
        "repeticiones_por_medida": REPEATS, "estadistico": "mediana",
    }


# --------------------------------------------------------------------------------------------- A. búsqueda de versiones
def bench_version_lookup(admin_conninfo):
    sizes = [1_000, 10_000, 100_000] if QUICK else [1_000, 10_000, 100_000, 1_000_000]
    rng = random.Random(7)
    rows = []
    name = f"bench_synthetic_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(admin_conninfo, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    conninfo = make_conninfo(admin_conninfo, dbname=name)
    try:
        with psycopg.connect(conninfo, autocommit=True) as conn:
            for n in sizes:
                ids = [f"syn-{i}" for i in range(n)]
                # mitad aciertos en posición aleatoria (caso medio) y mitad fallos (peor caso: se recorre todo)
                lookups = [rng.choice(ids) for _ in range(100)] + [f"syn-missing-{i}" for i in range(100)]
                entries = [(event_id, 1_700_000_000_000 + i) for i, event_id in enumerate(ids)]
                as_dict = {k: v for k, v in entries}

                def list_scan(entries=entries, lookups=lookups):
                    for key in lookups:
                        for event_id, _ in entries:
                            if event_id == key:
                                break

                def dict_lookup(as_dict=as_dict, lookups=lookups):
                    for key in lookups:
                        as_dict.get(key)

                def build_list():
                    return [(f"syn-{i}", 1_700_000_000_000 + i) for i in range(n)]

                def build_dict():
                    return {f"syn-{i}": 1_700_000_000_000 + i for i in range(n)}

                t_list = med(list_scan, 3 if n >= 1_000_000 else REPEATS) / len(lookups)
                t_dict = med(dict_lookup) / len(lookups)

                conn.execute("DROP TABLE IF EXISTS versions_noidx, versions_idx")
                for table in ("versions_noidx", "versions_idx"):
                    conn.execute(f"CREATE TABLE {table} (event_id text NOT NULL, updated_ms bigint NOT NULL, mag double precision)")
                    conn.execute(f"INSERT INTO {table} SELECT 'syn-' || g, 1700000000000 + g, 4.0 FROM generate_series(0, {n - 1}) g")
                conn.execute("ALTER TABLE versions_idx ADD CONSTRAINT uq_versions UNIQUE (event_id, updated_ms)")
                conn.execute("ANALYZE versions_noidx")
                conn.execute("ANALYZE versions_idx")

                def explain(table, key):
                    plan = conn.execute(
                        f"EXPLAIN (ANALYZE, FORMAT JSON) SELECT 1 FROM {table} WHERE event_id = %s", (key,)
                    ).fetchone()[0][0]
                    return plan["Execution Time"], plan["Plan"]["Node Type"]

                def sql_time(table):
                    times = [explain(table, k)[0] for k in lookups[:20] + lookups[100:120]]
                    return statistics.median(times) / 1000, explain(table, lookups[0])[1]

                t_noidx, plan_noidx = sql_time("versions_noidx")
                t_idx, plan_idx = sql_time("versions_idx")
                size = lambda rel: conn.execute("SELECT pg_relation_size(%s)", (rel,)).fetchone()[0] / 2**20
                rows.append({
                    "n": n,
                    "lista_secuencial_s_por_busqueda": t_list, "diccionario_s_por_busqueda": t_dict,
                    "postgres_sin_indice_s": t_noidx, "plan_sin_indice": plan_noidx,
                    "postgres_con_indice_s": t_idx, "plan_con_indice": plan_idx,
                    "memoria_lista_mib": round(peak_mib(build_list), 2), "memoria_diccionario_mib": round(peak_mib(build_dict), 2),
                    "tabla_mib": round(size("versions_noidx"), 2), "indice_unico_mib": round(size("uq_versions"), 2),
                })
                print("A", n, rows[-1])
    finally:
        with psycopg.connect(admin_conninfo, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    return rows


# --------------------------------------------------------------------------------------------- B. integración geográfica
def geo_memory():
    """Memoria de las estructuras geográficas. tracemalloc no ve GEOS (código C), así que se mide el RSS del proceso, y en
    procesos nuevos y separados: en uno ya usado, Python reutiliza páginas liberadas y el aumento sale 0."""
    import subprocess
    import sys
    code = '''
import json, sys
from pathlib import Path
def rss():
    return next(int(l.split()[1]) for l in open('/proc/self/status') if l.startswith('VmRSS')) / 1024
from shapely import make_valid
from shapely.geometry import shape
from backend.consumer.geo import CountryIndex
features = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))['features']
before = rss()
if sys.argv[1] == 'lista':
    keep = []
    for f in features:
        g = shape(f['geometry'])
        keep.append(g if g.is_valid else make_valid(g))
else:
    keep = CountryIndex(features)
print(round(rss() - before, 1))
'''
    out = {}
    for kind, label in (("lista", "lista_de_177_poligonos_mib"), ("strtree", "indice_strtree_con_sus_geometrias_mib")):
        run = subprocess.run([sys.executable, "-c", code, kind, str(COUNTRIES)], capture_output=True, text=True, check=True,
                             env={**os.environ, "PYTHONPATH": "/app"})
        out[label] = float(run.stdout.strip().splitlines()[-1])
    out["catalogo_geojson_mib"] = round(COUNTRIES.stat().st_size / 2**20, 2)
    return out


def bench_geo():
    from shapely.geometry import Point, shape
    from shapely import make_valid
    features = json.loads(COUNTRIES.read_text(encoding="utf-8"))["features"]
    polygons = []
    for f in features:
        g = shape(f["geometry"])
        polygons.append(g if g.is_valid else make_valid(g))
    index = CountryIndex(features)
    memoria = geo_memory()
    ids = [f["properties"]["ADM0_A3"] for f in features]
    rng = random.Random(11)
    naive_sizes = [1_000, 5_000, 20_000] if not QUICK else [500, 1_000, 2_000]
    indexed_extra = [] if QUICK else [100_000, 500_000]
    rows = []
    for n in naive_sizes + indexed_extra:
        points = [(rng.uniform(-180, 180), rng.uniform(-90, 90)) for _ in range(n)]  # SINTÉTICOS (uniformes en lon/lat)

        def indexed(points=points):
            for lon, lat in points:
                index.locate(lon, lat)

        def naive(points=points):
            for lon, lat in points:
                p = Point(lon, lat)
                hits = [ids[i] for i, g in enumerate(polygons) if g.covers(p)]
                if hits:
                    min(hits)

        t_idx = med(indexed, 3)
        row = {"n_puntos": n, "strtree_s": t_idx, "strtree_puntos_por_s": round(n / t_idx)}
        if n in naive_sizes:
            row["recorrido_de_177_poligonos_s"] = med(naive, 1 if n >= 20_000 else 3)
            row["recorrido_puntos_por_s"] = round(n / row["recorrido_de_177_poligonos_s"])
            row["aceleracion"] = round(row["recorrido_de_177_poligonos_s"] / t_idx, 1)
        rows.append(row)
        print("B", row)
    # coherencia: ambos métodos dan el mismo país en una muestra
    sample = [(rng.uniform(-180, 180), rng.uniform(-90, 90)) for _ in range(2_000)]
    mismatch = 0
    for lon, lat in sample:
        p = Point(lon, lat)
        hits = sorted(ids[i] for i, g in enumerate(polygons) if g.covers(p))
        expected = hits[0] if hits else None
        if expected != index.locate(lon, lat).country_id:
            mismatch += 1
    return {"filas": rows, "discrepancias_en_muestra_de_2000": mismatch, "poligonos": len(polygons), "memoria": memoria}


# --------------------------------------------------------------------------------------------- C. agregación por ventanas
def bench_windows(admin_conninfo):
    sizes = [10_000, 100_000, 1_000_000] if not QUICK else [10_000, 100_000]
    rows = []
    name = f"bench_synthetic_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(admin_conninfo, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    conninfo = make_conninfo(admin_conninfo, dbname=name)
    window_start, window_end = YEAR_START + 200 * 24 * HOUR_MS, YEAR_START + 201 * 24 * HOUR_MS  # un día cualquiera
    try:
        with psycopg.connect(conninfo, autocommit=True) as conn:
            for n in sizes:
                conn.execute("DROP TABLE IF EXISTS ev")
                conn.execute("CREATE TABLE ev (event_id text NOT NULL, time_ms bigint NOT NULL, mag double precision)")
                conn.execute(
                    f"INSERT INTO ev SELECT 'syn-' || g, {YEAR_START} + (random() * {YEAR_MS})::bigint, 4 + random() * 4 "
                    f"FROM generate_series(1, {n}) g")
                conn.execute("ANALYZE ev")

                def run(label, sql, params=()):
                    plan = conn.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}", params).fetchone()[0][0]
                    return plan["Execution Time"] / 1000, plan["Plan"]

                def node_types(plan):
                    out = [plan["Node Type"]]
                    for child in plan.get("Plans", []):
                        out += node_types(child)
                    return out

                q_window = "SELECT time_ms / 3600000 AS h, count(*) FROM ev WHERE time_ms >= %s AND time_ms < %s GROUP BY 1"
                q_year = "SELECT time_ms / 3600000 AS h, count(*) FROM ev GROUP BY 1"
                t_window_noidx = statistics.median(run("w", q_window, (window_start, window_end))[0] for _ in range(REPEATS))
                plan_noidx = [x for x in node_types(run("w", q_window, (window_start, window_end))[1]) if "Scan" in x]
                t_year = statistics.median(run("y", q_year)[0] for _ in range(3))
                conn.execute("CREATE INDEX ix_ev_time ON ev (time_ms DESC)")
                conn.execute("ANALYZE ev")
                t_window_idx = statistics.median(run("w", q_window, (window_start, window_end))[0] for _ in range(REPEATS))
                plan_idx = [x for x in node_types(run("w", q_window, (window_start, window_end))[1]) if "Scan" in x]
                t_year_idx = statistics.median(run("y", q_year)[0] for _ in range(3))

                def python_side():
                    buckets = {}
                    for (t,) in conn.execute("SELECT time_ms FROM ev").fetchall():  # fetchall: se materializan todas las filas
                        buckets[t // HOUR_MS] = buckets.get(t // HOUR_MS, 0) + 1
                    return buckets

                def sql_side():
                    return conn.execute(q_year).fetchall()

                # la agregación se valida: ambos caminos dan los mismos recuentos
                assert dict(sql_side()) == python_side()
                rows.append({
                    "n": n,
                    "ventana_24h_sin_indice_s": t_window_noidx, "plan_sin_indice": plan_noidx,
                    "ventana_24h_con_indice_s": t_window_idx, "plan_con_indice": plan_idx,
                    "todo_el_año_sin_indice_s": t_year, "todo_el_año_con_indice_s": t_year_idx,
                    "agregar_en_postgres_s": med(sql_side, 3), "agregar_en_python_s": med(python_side, 3),
                    "python_pico_mib": round(peak_mib(python_side), 2), "postgres_pico_python_mib": round(peak_mib(sql_side), 3),
                    "tabla_mib": round(conn.execute("SELECT pg_relation_size('ev')").fetchone()[0] / 2**20, 1),
                    "indice_mib": round(conn.execute("SELECT pg_relation_size('ix_ev_time')").fetchone()[0] / 2**20, 1),
                })
                print("C", n, rows[-1])
    finally:
        with psycopg.connect(admin_conninfo, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    return rows


# --------------------------------------------------------------------------------------------- resumen en Markdown
def fmt_s(v):
    if v is None:
        return "—"
    if v < 1e-3:
        return f"{v * 1e6:.2f} µs"
    return f"{v * 1000:.3f} ms" if v < 1 else f"{v:.2f} s"


def markdown(data):
    L = ["# Mediciones de complejidad (datos SINTÉTICOS, base temporal; no mezclados con datos reales)", "",
         f"Generado: {data['generado_en']}. Equipo: {json.dumps(data['equipo'], ensure_ascii=False)}", ""]
    L += ["## A. Búsqueda de versiones por identificador (tiempo por búsqueda, mitad aciertos y mitad fallos)", "",
          "| N | Lista (secuencial) | Diccionario | PostgreSQL sin índice | PostgreSQL con índice único | Memoria lista | Memoria dict | Tabla | Índice |",
          "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in data["A_busqueda_de_versiones"]:
        L.append(f"| {r['n']:,} | {fmt_s(r['lista_secuencial_s_por_busqueda'])} | {fmt_s(r['diccionario_s_por_busqueda'])} | "
                 f"{fmt_s(r['postgres_sin_indice_s'])} ({r['plan_sin_indice']}) | {fmt_s(r['postgres_con_indice_s'])} ({r['plan_con_indice']}) | "
                 f"{r['memoria_lista_mib']} MiB | {r['memoria_diccionario_mib']} MiB | {r['tabla_mib']} MiB | {r['indice_unico_mib']} MiB |")
    L += ["", "## B. Integración geográfica (punto en polígono, 177 polígonos)", "",
          "| Puntos | Recorrido de 177 polígonos | STRtree | Aceleración | STRtree puntos/s |", "|---:|---:|---:|---:|---:|"]
    for r in data["B_integracion_geografica"]["filas"]:
        L.append(f"| {r['n_puntos']:,} | {fmt_s(r.get('recorrido_de_177_poligonos_s'))} | {fmt_s(r['strtree_s'])} | "
                 f"{r.get('aceleracion', '—')}{'×' if 'aceleracion' in r else ''} | {r['strtree_puntos_por_s']:,} |")
    L += ["", f"Discrepancias entre ambos métodos en 2.000 puntos: {data['B_integracion_geografica']['discrepancias_en_muestra_de_2000']}.",
          f"Memoria (RSS del proceso): {json.dumps(data['B_integracion_geografica']['memoria'], ensure_ascii=False)}", "",
          "## C. Agregación por ventanas de una hora UTC", "",
          "| N eventos | Ventana 24 h sin índice | Ventana 24 h con índice | Año completo sin índice | Año completo con índice | Agregar en PostgreSQL | Agregar en Python | Pico Python | Tabla | Índice |",
          "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in data["C_agregacion_por_ventanas"]:
        L.append(f"| {r['n']:,} | {fmt_s(r['ventana_24h_sin_indice_s'])} {r['plan_sin_indice']} | {fmt_s(r['ventana_24h_con_indice_s'])} {r['plan_con_indice']} | "
                 f"{fmt_s(r['todo_el_año_sin_indice_s'])} | {fmt_s(r['todo_el_año_con_indice_s'])} | {fmt_s(r['agregar_en_postgres_s'])} | "
                 f"{fmt_s(r['agregar_en_python_s'])} | {r['python_pico_mib']} MiB | {r['tabla_mib']} MiB | {r['indice_mib']} MiB |")
    return "\n".join(L) + "\n"


def main() -> None:
    from datetime import datetime, timezone
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        eq = equipment(conn)
    data = {"generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"), "equipo": eq, "datos": "SINTÉTICOS",
            "A_busqueda_de_versiones": bench_version_lookup(DB_URL),
            "B_integracion_geografica": bench_geo(),
            "C_agregacion_por_ventanas": bench_windows(DB_URL)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "complejidad.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "complejidad.md").write_text(markdown(data), encoding="utf-8")
    print("\n" + markdown(data))


if __name__ == "__main__":
    main()
