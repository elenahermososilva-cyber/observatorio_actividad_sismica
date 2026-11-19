"""Análisis visual de calidad: consulta PostgreSQL real, dibuja los gráficos con matplotlib (pyplot) y escribe
docs/analisis-calidad.md con las cifras y los denominadores de cada indicador.

Se ejecuta en un contenedor efímero de la imagen `api` (tiene psycopg y DATABASE_URL); matplotlib se instala solo en ese
contenedor, no forma parte de la imagen ni de los cinco servicios:

    docker compose run --rm --no-deps -v "${PWD}/scripts:/app/scripts" -v "${PWD}/docs:/app/docs" api \
        sh -c "pip install -q --target /tmp/mpl matplotlib==3.10.9 && PYTHONPATH=/tmp/mpl MPLCONFIGDIR=/tmp/mplcfg python scripts/graficos_calidad.py"

Cada indicador es un cociente con numerador y denominador explícitos. No se calcula una «nota global de calidad»:
mezclaría denominadores distintos (mensajes, versiones, eventos) y sumaría incidencias que pueden solaparse.
"""

import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import psycopg  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "evidencias" / "calidad"
OUT.mkdir(parents=True, exist_ok=True)
DOC = ROOT / "docs" / "analisis-calidad.md"
SETS = [("live", "Feed en vivo"), ("historico", "Histórico 2025"), ("replay", "Reproducción")]
COLORS = {"live": "#176b70", "historico": "#7b3fb6", "replay": "#e8a317"}

plt.rcParams.update({
    "figure.dpi": 130, "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.3, "axes.axisbelow": True,
})


def one(cur, query, *params):
    cur.execute(query, params)
    return cur.fetchone()


def pct(num, den):
    return None if not den else round(100 * num / den, 2)


def fmt(value, digits=1):
    if value is None:
        return "ND"
    text = f"{value:,.{digits}f}" if isinstance(value, float) else f"{value:,}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
    data = {"generado_en": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "conjuntos": {}}
    for schema, _ in SETS:
        d = {}
        d["eventos"], d["con_mag"], d["con_prof"], d["con_tipo_mag"], d["con_lugar"], d["completos"] = one(cur, f"""
            SELECT count(*), count(mag), count(depth_km), count(mag_type), count(*) FILTER (WHERE coalesce(trim(place), '') <> ''),
                   count(*) FILTER (WHERE mag IS NOT NULL AND depth_km IS NOT NULL AND mag_type IS NOT NULL AND coalesce(trim(place), '') <> '')
            FROM {schema}.event_current""")
        d["versiones"], d["versiones_distintas"] = one(cur, f"SELECT count(*), count(DISTINCT (event_id, updated_ms)) FROM {schema}.event_message")
        d["cuarentena"] = one(cur, f"SELECT count(*) FROM {schema}.quarantine_record")[0]
        d["ids_distintos"] = one(cur, f"SELECT count(DISTINCT event_id) FROM {schema}.event_current")[0]
        d["vigente_es_la_ultima"] = one(cur, f"""
            SELECT count(*) FILTER (WHERE c.current_version_ms = m.maxv) FROM {schema}.event_current c
            JOIN (SELECT event_id, max(updated_ms) AS maxv FROM {schema}.event_message GROUP BY 1) m USING (event_id)""")[0]
        d["pais_coherente"] = one(cur, f"""
            SELECT count(*) FILTER (WHERE (country_status = 'assigned') = (country_id IS NOT NULL)) FROM {schema}.event_current""")[0]
        d["sin_pais"] = one(cur, f"SELECT count(*) FROM {schema}.event_current WHERE country_id IS NULL")[0]
        cur.execute(f"SELECT split_part(reason, ':', 1), coalesce(substring(reason from $$type='([^']*)'$$), ''), count(*) "
                    f"FROM {schema}.quarantine_record GROUP BY 1, 2 ORDER BY 3 DESC")
        d["motivos_cuarentena"] = [{"motivo": m, "detalle": t, "n": n} for m, t, n in cur.fetchall()]
        cur.execute(f"SELECT code, count(*) FROM {schema}.event_current, unnest(quality_flags) code GROUP BY 1 ORDER BY 2 DESC")
        d["avisos"] = dict(cur.fetchall())
        d["sin_aviso"] = one(cur, f"SELECT count(*) FROM {schema}.event_current WHERE cardinality(quality_flags) = 0")[0]
        data["conjuntos"][schema] = d

    # Actualidad (solo live): segundos entre la versión de USGS (`updated`) y su ingesta en nuestra base.
    # Solo se mide nuestro retraso cuando el productor estaba funcionando al publicarse la versión: hubo una consulta
    # correcta a USGS en los 120 s anteriores a su `updated`. Las demás se publicaron con el productor parado y se
    # recuperaron de golpe al reanudar (la ventana de 24 h del feed lo permite): se cuentan aparte.
    cur.execute("""
        SELECT extract(epoch FROM m.ingested_at) * 1000 - m.updated_ms,
               EXISTS (SELECT 1 FROM ingest.extraction_log l WHERE l.mode = 'live' AND l.ok
                         AND l.started_at BETWEEN to_timestamp(m.updated_ms / 1000.0) - interval '120 seconds'
                                              AND to_timestamp(m.updated_ms / 1000.0))
        FROM live.event_message m""")
    rows = cur.fetchall()
    delays = sorted(max(0.0, float(r[0]) / 1000) for r in rows if r[1])
    recovered = sum(1 for r in rows if not r[1])
    # Revisiones (solo live): versiones guardadas por evento.
    cur.execute("SELECT count(*) FROM live.event_message GROUP BY event_id")
    versions_per_event = [r[0] for r in cur.fetchall()]

live = data["conjuntos"]["live"]
in_2min = sum(1 for s in delays if s <= 120)
late = [s for s in delays if s > 3600]
data["actualidad_live"] = {
    "versiones": len(delays), "mediana_s": round(statistics.median(delays), 1) if delays else None,
    "p95_s": round(delays[int(0.95 * (len(delays) - 1))], 1) if delays else None,
    "en_2_min": in_2min, "mas_de_1_h": len(late), "recuperadas_tras_parada": recovered,
}
data["revisiones_live"] = {
    "eventos": len(versions_per_event), "con_revision": sum(1 for v in versions_per_event if v > 1),
    "max_versiones": max(versions_per_event, default=0),
}

# --------------------------------------------------------------------------------- indicadores (numerador / denominador)
def indicators(schema):
    d = data["conjuntos"][schema]
    rows = {
        "Completitud": (d["completos"], d["eventos"], "eventos con magnitud, profundidad, tipo de magnitud y lugar / eventos"),
        "Validez": (d["versiones"], d["versiones"] + d["cuarentena"], "versiones aceptadas / versiones aceptadas + rechazadas (cuarentena)"),
        "Unicidad": (d["versiones_distintas"], d["versiones"], "pares (event_id, updated) distintos / versiones guardadas"),
        "Consistencia": (d["vigente_es_la_ultima"], d["eventos"], "eventos cuya versión vigente es la más reciente recibida / eventos"),
    }
    if schema == "live":
        rows["Actualidad"] = (in_2min, len(delays), "versiones guardadas ≤ 2 min después de su `updated` / versiones publicadas con el productor en marcha")
    return rows


table = {schema: indicators(schema) for schema, _ in SETS}
dims = ["Completitud", "Validez", "Unicidad", "Consistencia", "Actualidad"]

# --------------------------------------------------------------------------------- gráfico 1: indicadores por conjunto
fig, ax = plt.subplots(figsize=(9, 4.2))
width = 0.26
for i, (schema, label) in enumerate(SETS):
    values = [pct(*table[schema][dim][:2]) if dim in table[schema] else None for dim in dims]
    xs = [k + (i - 1) * width for k in range(len(dims))]
    bars = ax.bar(xs, [v or 0 for v in values], width, label=label, color=COLORS[schema])
    for x, v in zip(xs, values):
        ax.text(x, (v or 0) + 1.2, "ND" if v is None else f"{v:.1f}".replace(".", ","), ha="center", fontsize=7.5,
                color="#64748b" if v is None else "#132b40")
ax.set_xticks(range(len(dims)), dims)
ax.set_ylim(0, 112)
ax.set_ylabel("% (cada barra tiene su propio denominador)")
ax.set_title("Indicadores de calidad por conjunto de datos")
ax.legend(loc="lower left", fontsize=8, ncols=3)
fig.text(0.01, 0.005, "Actualidad solo aplica al feed en vivo (ND en los demás). Exactitud no se mide: comprobar que un valor es numérico "
         "no demuestra que sea exacto.", fontsize=7, color="#42596b")
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(OUT / "01-indicadores-por-conjunto.png")
plt.close(fig)

# --------------------------------------------------------------------------------- gráfico 2: completitud por campo
fields = [("con_mag", "Magnitud"), ("con_prof", "Profundidad"), ("con_tipo_mag", "Tipo de magnitud"), ("con_lugar", "Lugar (place)")]
fig, ax = plt.subplots(figsize=(8, 3.4))
for i, schema in enumerate(["live", "historico"]):
    d = data["conjuntos"][schema]
    values = [pct(d[key], d["eventos"]) for key, _ in fields]
    ys = [k + (i - 0.5) * 0.38 for k in range(len(fields))]
    ax.barh(ys, values, 0.36, color=COLORS[schema], label=f"{dict(SETS)[schema]} (n = {fmt(d['eventos'])})")
    for y, v, (key, _) in zip(ys, values, fields):
        missing = d["eventos"] - d[key]
        ax.text(v + 0.3, y, f"{v:.2f} %".replace(".", ",") + (f"  ({missing} nulos)" if missing else ""), va="center", fontsize=8)
ax.set_yticks(range(len(fields)), [label for _, label in fields])
ax.set_xlim(0, 118)
ax.invert_yaxis()
ax.set_xlabel("% de eventos con el campo informado (los nulos se conservan, nunca se rellenan)")
ax.set_title("Completitud por campo")
ax.legend(fontsize=8, loc="lower right")
fig.tight_layout()
fig.savefig(OUT / "02-completitud-por-campo.png")
plt.close(fig)

# --------------------------------------------------------------------------------- gráfico 3: motivos de cuarentena
fig, ax = plt.subplots(figsize=(8, 3.2))
labels, counts, colors = [], [], []
for schema, label in SETS:
    for item in data["conjuntos"][schema]["motivos_cuarentena"]:
        detail = f" · {item['detalle']}" if item["detalle"] else ""
        labels.append(f"{label}: {item['motivo']}{detail}")
        counts.append(item["n"])
        colors.append(COLORS[schema])
if labels:
    ax.barh(labels, counts, color=colors)
    for y, n in enumerate(counts):
        ax.text(n + 0.1, y, str(n), va="center", fontsize=9)
    ax.invert_yaxis()
else:
    ax.text(0.5, 0.5, "Sin rechazos", ha="center", transform=ax.transAxes)
ax.set_xlabel("Registros en cuarentena (con motivo, payload original y referencia Kafka)")
ax.set_title("Rechazos por motivo y conjunto (ninguno se descarta en silencio)")
fig.tight_layout()
fig.savefig(OUT / "03-cuarentena-por-motivo.png")
plt.close(fig)

# --------------------------------------------------------------------------------- gráfico 4: retraso de ingesta (live)
fig, axes = plt.subplots(1, 2, figsize=(10, 3.4), gridspec_kw={"width_ratios": [1.5, 1]})
normal = [s for s in delays if s <= 600]
axes[0].hist(normal, bins=range(0, 610, 15), color=COLORS["live"], edgecolor="white")
axes[0].axvline(60, color="#e35b37", ls="--", lw=1)
axes[0].text(62, axes[0].get_ylim()[1] * 0.9, "sondeo de 60 s", color="#e35b37", fontsize=8)
axes[0].set_xlabel("Segundos entre la versión en USGS y su ingesta (≤ 10 min)")
axes[0].set_ylabel("Versiones")
axes[0].set_title("Actualidad del feed en vivo")
buckets = [("≤ 2 min", sum(1 for s in delays if s <= 120)), ("2–10 min", sum(1 for s in delays if 120 < s <= 600)),
           ("10 min–1 h", sum(1 for s in delays if 600 < s <= 3600)), ("> 1 h", len(late))]
axes[1].bar([b for b, _ in buckets], [n for _, n in buckets], color=["#176b70", "#e8a317", "#e35b37", "#7b3fb6"])
for k, (_, n) in enumerate(buckets):
    axes[1].text(k, n, str(n), ha="center", va="bottom", fontsize=9)
axes[1].set_title(f"Con el productor en marcha (n = {len(delays)})")
axes[1].set_ylabel("Versiones")
fig.text(0.01, 0.01, f"Aparte: {recovered} versiones publicadas por USGS mientras el productor estaba parado, recuperadas al reanudar "
         "gracias a la ventana de 24 h del feed (no son retraso del funcionamiento normal).", fontsize=7, color="#42596b")
fig.tight_layout(rect=(0, 0.04, 1, 1))
fig.savefig(OUT / "04-actualidad-live.png")
plt.close(fig)

# --------------------------------------------------------------------------------- gráfico 5: avisos y revisiones
fig, axes = plt.subplots(1, 2, figsize=(10, 3.4))
flags = live["avisos"]
if flags:
    names = list(flags)
    axes[0].barh(names, [flags[n] for n in names], color=COLORS["live"])
    for y, n in enumerate(flags.values()):
        axes[0].text(n + 0.05, y, str(n), va="center", fontsize=9)
    axes[0].invert_yaxis()
axes[0].set_title(f"Avisos de calidad en vivo ({fmt(live['sin_aviso'])} de {fmt(live['eventos'])} sin aviso)")
axes[0].set_xlabel("Eventos señalados (se conservan)")
counts = {}
for v in versions_per_event:
    counts[v] = counts.get(v, 0) + 1
axes[1].bar([str(k) for k in sorted(counts)], [counts[k] for k in sorted(counts)], color=COLORS["live"])
for k, key in enumerate(sorted(counts)):
    axes[1].text(k, counts[key], str(counts[key]), ha="center", va="bottom", fontsize=9)
axes[1].set_xlabel("Versiones guardadas por evento")
axes[1].set_ylabel("Eventos")
axes[1].set_title("Revisiones en el feed en vivo")
fig.tight_layout()
fig.savefig(OUT / "05-avisos-y-revisiones.png")
plt.close(fig)

(ROOT / "docs" / "evidencias" / "calidad" / "calidad-datos.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=float), encoding="utf-8")

# --------------------------------------------------------------------------------- documento
def ind_rows():
    lines = []
    for dim in dims:
        cells = []
        for schema, _ in SETS:
            if dim in table[schema]:
                num, den, _ = table[schema][dim]
                cells.append(f"{fmt(pct(num, den), 2)} % ({fmt(num)} / {fmt(den)})")
            else:
                cells.append("ND (no aplica)")
        definition = next(table[s][dim][2] for s, _ in SETS if dim in table[s])
        lines.append(f"| **{dim}** | {definition} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


reasons = "\n".join(
    f"| {label} | `{item['motivo']}` | {item['detalle'] or '—'} | {item['n']} |"
    for schema, label in SETS for item in data["conjuntos"][schema]["motivos_cuarentena"]
) or "| — | — | — | 0 |"
a = data["actualidad_live"]
r = data["revisiones_live"]
h = data["conjuntos"]["historico"]
rp = data["conjuntos"]["replay"]
doc = f"""# Análisis de calidad de los datos (visual)

Generado por `scripts/graficos_calidad.py` contra PostgreSQL real el {data['generado_en'].replace('T', ' ')} UTC
(cifras en `docs/evidencias/calidad/calidad-datos.json`). Complementa a la memoria (§3), que contiene la comparación
**antes/después** con los archivos originales, las reglas aplicadas y ejemplos reales; aquí se resume en gráficos el
estado actual de cada conjunto. Las cifras del feed en vivo cambian con el tiempo: es una instantánea.

Para regenerarlo (matplotlib se instala solo en el contenedor efímero, no en la imagen):

```bash
docker compose run --rm --no-deps -v "${{PWD}}/scripts:/app/scripts" -v "${{PWD}}/docs:/app/docs" api \\
    sh -c "pip install -q --target /tmp/mpl matplotlib==3.10.9 && PYTHONPATH=/tmp/mpl MPLCONFIGDIR=/tmp/mplcfg python scripts/graficos_calidad.py"
```

## 1. Indicadores por dimensión y conjunto

Cada celda es un cociente con su numerador y su denominador. **No se calcula una nota global**: mezclaría denominadores
distintos (eventos, versiones) y sumaría incidencias que pueden solaparse, que es justo lo que la guía de entrega pide evitar.

| Dimensión | Definición (numerador / denominador) | Feed en vivo | Histórico 2025 | Reproducción |
|---|---|---:|---:|---:|
{ind_rows()}
| **Exactitud** | No medible con los datos disponibles | ND | ND | ND |

![Indicadores por conjunto](evidencias/calidad/01-indicadores-por-conjunto.png)

**Lectura.** Unicidad y consistencia son del 100 % en los tres conjuntos porque las garantiza la base de datos
(`UNIQUE (event_id, updated_ms)` y la guardia del upsert), no porque se hayan limpiado a mano. La validez del feed en vivo
es la única por debajo del 100 %: son los no-terremotos que la regla de tipo manda a cuarentena. **Exactitud** no se puede
medir: comprobar que una magnitud es numérica y está en rango no demuestra que sea correcta (memoria §3.7); lo único
contrastable es la atribución de país, que se verifica en la memoria §3.6.

## 2. Completitud por campo

![Completitud por campo](evidencias/calidad/02-completitud-por-campo.png)

| Campo | Feed en vivo (n = {fmt(live['eventos'])}) | Histórico 2025 (n = {fmt(h['eventos'])}) | Decisión |
|---|---:|---:|---|
| Magnitud | {fmt(live['con_mag'])} | {fmt(h['con_mag'])} | Un nulo se conserva como `null` (ND): no se sustituye por 0, que alteraría medias y umbrales |
| Profundidad | {fmt(live['con_prof'])} | {fmt(h['con_prof'])} | Igual: ND en el panel y fuera del histograma, con el recuento de ausentes declarado |
| Tipo de magnitud | {fmt(live['con_tipo_mag'])} | {fmt(h['con_tipo_mag'])} | Se conserva tal cual (normalizado a minúsculas si llega en mayúsculas) |
| Lugar | {fmt(live['con_lugar'])} | {fmt(h['con_lugar'])} | Se recortan espacios; nunca se usa para asignar país |

## 3. Rechazos (cuarentena)

![Rechazos por motivo](evidencias/calidad/03-cuarentena-por-motivo.png)

| Conjunto | Motivo | Detalle | Registros |
|---|---|---|---:|
{reasons}

Cada rechazo conserva el motivo, el payload original y la referencia Kafka (topic, partición, offset); ninguno aparece en
el mapa ni en las estadísticas. Histórico: {h['cuarentena']} rechazos (catálogo ya filtrado por `eventtype=earthquake`).
Reproducción: {rp['cuarentena']} (sus casos controlados de duplicado y versión antigua no son errores: se resuelven como
`DUPLICATE` y `STALE` y no se guardan). Los registros artificialmente dañados viven en las pruebas, no en estos conjuntos.

## 4. Actualidad del feed en vivo

![Actualidad del feed en vivo](evidencias/calidad/04-actualidad-live.png)

Se mide sobre las {fmt(a['versiones'])} versiones que USGS publicó **con el productor en marcha** (hubo una consulta correcta en
los 120 s anteriores): **{fmt(a['en_2_min'])} ({fmt(pct(a['en_2_min'], a['versiones']), 1)} %) entraron en la base menos de 2 minutos después**
(mediana {fmt(a['mediana_s'], 0)} s, p95 {fmt(a['p95_s'], 0)} s). El reparto se concentra por debajo de 120 s porque el productor consulta
el feed cada minuto. Aparte quedan {fmt(a['recuperadas_tras_parada'])} versiones publicadas mientras el productor estaba parado
(arranques y el hueco de ingesta de la memoria §2.3): se recuperaron al reanudar gracias a la ventana de 24 h del feed, y
contarlas como retraso confundiría una parada con lentitud del sistema.
Esto mide **nuestro** retraso; el retraso de publicación de USGS (ocurrencia → primera versión) se analiza en la memoria §3.5.

## 5. Avisos de calidad y revisiones

![Avisos y revisiones](evidencias/calidad/05-avisos-y-revisiones.png)

Los avisos (`quality_flags`) **no rechazan** el evento: señalan valores válidos pero llamativos (magnitud o profundidad
negativas, que son posibles en sismología) o transformaciones aplicadas (espacios recortados). En el feed en vivo,
{fmt(live['sin_aviso'])} de {fmt(live['eventos'])} eventos no tienen ningún aviso; en el histórico, {fmt(h['sin_aviso'])} de {fmt(h['eventos'])}.

Revisiones: {fmt(r['con_revision'])} de {fmt(r['eventos'])} eventos en vivo tienen más de una versión (máximo {r['max_versiones']}). Cada versión se guarda en
`event_message` y solo la más reciente pasa a `event_current`; una versión antigua que llegue tarde no la sustituye.
"""
DOC.write_text(doc, encoding="utf-8")
print("escrito", DOC.relative_to(ROOT), "y", len(list(OUT.glob("*.png"))), "gráficos")
