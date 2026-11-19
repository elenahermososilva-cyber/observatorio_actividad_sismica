"""Genera docs/consultas-y-procedencia.md a partir de los registros reales (manifest del histórico y memoria-datos.json).

Solo biblioteca estándar; se ejecuta en el anfitrión. Antes hay que haber ejecutado scripts/memoria_datos.py:

    python scripts/procedencia.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "data" / "raw" / "historico" / "manifest.json").read_text(encoding="utf-8"))
datos = json.loads((ROOT / "docs" / "evidencias" / "memoria-datos.json").read_text(encoding="utf-8"))
live = datos["live"]
catalogo = (ROOT / "frontend" / "public" / "datos" / "paises.geojson").read_bytes().replace(b"\r\n", b"\n")

import hashlib

sha_catalogo = hashlib.sha256(catalogo).hexdigest()

rows = []
total_reported = total_received = total_bytes = 0
for month, info in sorted(manifest["months"].items()):
    for q in info["queries"]:
        total_reported += q["count_reported"]
        total_received += q["features_received"]
        total_bytes += q["bytes"]
        rows.append(
            f"| {month} | {q['start'][:10]} → {q['end'][:10]} | {q['retrieved_at'][:19].replace('T', ' ')} | {q['count_reported']:,} | "
            f"{q['features_received']:,} | {q['bytes'] / 1024:,.0f} KiB | {q['latency_ms']} ms | `{q['sha256'][:12]}…` |"
        )
subdivididos = [m for m, i in manifest["months"].items() if i.get("subdivided")]
reciente_path = ROOT / "docs" / "evidencias" / "comparacion-reciente.json"
if reciente_path.exists():
    rec = json.loads(reciente_path.read_text(encoding="utf-8"))
    rec_rows = "\n".join(
        f"| {q['start'][:10]} → {q['end'][:10]} | {q['retrieved_at'][:19].replace('T', ' ')} | {q['count_reported']:,} | "
        f"{q['features_received']:,} | {q['bytes'] / 1024:,.0f} KiB | `{q['sha256'][:12]}…` |"
        for q in rec["procedencia"]["consultas"]
    )
    seccion_reciente = f"""
### 2.1 Catálogo reciente 2026 (comparación equivalente)

Mismos parámetros que el histórico, para la conclusión 4 de la memoria. Se guarda en `data/raw/reciente/` y **no se carga en la base de datos**. Generado por `scripts/comparacion_reciente.py`.

| Intervalo (UTC) | Descargado | Reportado por `count` | Features recibidas | Tamaño | SHA-256 |
|---|---|---:|---:|---:|---|
{rec_rows}

- {rec['reciente']['eventos']:,} eventos M ≥ 4 en {rec['periodo_reciente']['dias']} días completos. Los días más recientes de una descarga pueden completarse después: el manifiesto fija la fecha de la instantánea.
"""
else:
    seccion_reciente = ""

ok = live["consultas"]["ok"]
fallidas = live["consultas"].get("fallidas")
dedup = live["deduplicacion_del_feed"]
gaps = datos["huecos_de_ingesta_live"]
h = datos["analisis_historico_2025"]

doc = f"""# Registro de consultas y procedencia

Generado por `scripts/procedencia.py` a partir de `data/raw/historico/manifest.json` y `docs/evidencias/memoria-datos.json` (instantánea {datos['generado_en']}). Complementa al diccionario de datos (`docs/diccionario-de-datos.md`).

## 1. Fuentes

| Fuente | Qué aporta | Acceso | Licencia / condiciones | Dónde queda |
|---|---|---|---|---|
| USGS Earthquake Catalog, **feed** `all_day.geojson` | Eventos de las últimas 24 h, actualizado cada minuto | HTTP GET cada 60 s (`USGS_FEED_URL`) | Datos del Gobierno de EE. UU., dominio público (docs/curso/FUENTES-Y-LICENCIAS.md) | Originales íntegros comprimidos en `data/raw/live/AAAA/MM/DD/HHMMSS.geojson.gz` (retención `RAW_RETENTION_DAYS`) y cada versión aceptada en `<esquema>.event_message.payload` |
| USGS Earthquake Catalog, **API FDSN** `fdsnws/event/1/query` | Histórico 2025, mundo, M ≥ 4, `eventtype=earthquake` | Descarga mensual con `history_download` (12 consultas; sin subdivisiones necesarias) | Igual que el feed | `data/raw/historico/AAAA-MM.geojson` + `manifest.json`; no se versionan en Git (se regeneran con el procedimiento de `data/README.md`) |
| Natural Earth, Admin 0 Countries 1:110M | 177 entidades con `ADM0_A3`, `NAME_ES`, `ADMIN`, `CONTINENT`, `SUBREGION` | Copia entregada: `frontend/public/datos/paises.geojson` | Dominio público; se conserva el reconocimiento | `ref.dim_country` (cargada por el migrador, con la huella del archivo) |

Huella SHA-256 del catálogo (normalizando CRLF→LF): `{sha_catalogo}`. Coincide con la de docs/curso/FUENTES-Y-LICENCIAS.md: {'sí' if sha_catalogo == '6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f' else 'NO (revisar)'}.

## 2. Histórico 2025: consultas realizadas

Extracción del {manifest['months']['2025-01']['queries'][0]['retrieved_at'][:10]}. Parámetros comunes: `format=geojson`, `minmagnitude=4`, `eventtype=earthquake`, `orderby=time-asc`, intervalo mensual `[inicio, fin)`.

| Mes | Intervalo (UTC) | Descargado | Reportado por `count` | Features recibidas | Tamaño | Latencia | SHA-256 |
|---|---|---|---:|---:|---:|---:|---|
{chr(10).join(rows)}
| **Total** | | | **{total_reported:,}** | **{total_received:,}** | **{total_bytes / 1024 / 1024:.1f} MiB** | | |

- Comprobación del límite de 20.000: **ninguna consulta lo alcanza** (la mayor trae {max(q['features_received'] for i in manifest['months'].values() for q in i['queries']):,}); intervalos subdivididos: {', '.join(subdivididos) if subdivididos else 'ninguno'}. Nunca se trunca en silencio: se pide antes `count` y, si se acercara al límite, se subdivide.
- El número recibido coincide con el reportado en las 12 consultas: {'sí' if total_reported == total_received else 'NO'}.
- Deduplicación entre intervalos (los extremos pueden repetirse): {h['eventos']:,} eventos únicos de {datos['calidad']['antes_historico_original']['features_leidas']:,} leídos → {datos['calidad']['antes_historico_original']['duplicados_entre_intervalos']} duplicados.
- Es una **instantánea** del catálogo en la fecha de extracción, no un registro de todas sus revisiones pasadas.
{seccion_reciente}
## 3. Feed en vivo: registro de consultas (`ingest.extraction_log`)

| Concepto | Valor |
|---|---|
| Consultas correctas | {ok['n']} (primera {ok['primera'][:19].replace('T', ' ')} UTC, última {ok['ultima'][:19].replace('T', ' ')} UTC) |
| Consultas fallidas | {fallidas['n'] if fallidas else 0} |
| Latencia (ms) | media {ok['latencia_media_ms']}, p95 {ok['latencia_p95_ms']}, máx {ok['latencia_max_ms']} |
| Apariciones de features en las respuestas | {dedup['apariciones_de_features_en_respuestas']:,} (cada respuesta repite toda la ventana de 24 h) |
| Versiones publicadas a Kafka (incluye rechazadas) | {dedup['versiones_publicadas']:,} |
| Publicaciones evitadas por la marca de «ya publicado» | **{dedup['porcentaje_suprimido']} %** |
| Originales guardados | {live['originales_guardados']['archivos_distintos']} archivos distintos; {live['originales_guardados']['respuestas_sin_copia_por_ser_identicas']} respuestas idénticas no se guardaron de nuevo |

Huecos de ingesta live (más de 5 min entre consultas correctas):

| Desde (UTC) | Hasta (UTC) | Horas | ¿Recuperable con el feed de 24 h? |
|---|---|---:|---|
{chr(10).join(f"| {g['desde'][:19].replace('T', ' ')} | {g['hasta'][:19].replace('T', ' ')} | {g['horas']} | {'sí' if g['recuperable_con_el_feed_24h'] else 'NO: usar el catálogo FDSN para el intervalo'} |" for g in gaps) if gaps else '| (ninguno) | | | |'}

## 4. Linaje de un dato

```
USGS feed/API ──► original íntegro (gzip, data/raw)  ──► productor ──► sobre Kafka (clave = event_id, source, mode, ingested_at)
      ──► consumidor ──► validación ──► event_message.payload (original sin modificar, una fila por versión)
                                    └─► quarantine_record (rechazos con motivo y referencia Kafka)
      ──► event_current (estado actual + columnas derivadas: país por punto-en-polígono, quality_flags)
      ──► API (/api/eventos, /api/estadisticas, /api/salud) ──► panel Angular
```

Cada paso conserva el anterior: del panel se puede llegar al `event_id`, de ahí a `event_message.payload` (el Feature original) y al archivo `data/raw/...` donde apareció (`ingest.extraction_log.raw_path`, `response_sha256`).

## 5. Cómo se obtuvo cada cifra de la memoria

| Cifras | Procedimiento |
|---|---|
| Análisis, calidad antes/después, actualidad, revisiones | `scripts/memoria_datos.py` → `docs/evidencias/memoria-datos.json` |
| Comparación equivalente con el catálogo reciente (conclusión 4) | `scripts/comparacion_reciente.py` → `docs/evidencias/comparacion-reciente.json` |
| Complejidad, tiempo y memoria | `scripts/medir_complejidad.py` → `docs/evidencias/complejidad.{{json,md}}` (datos sintéticos, base temporal) |
| Latencia de la API | `scripts/medir_api.py` → `docs/evidencias/api-latencia.json` |
| Pruebas de aceptación | `tests/acceptance/` → `docs/evidencias/aceptacion-s11.{{md,json}}` y `pila-real.md` |
| Panel y túnel | `tests/e2e/` → `docs/evidencias/panel*.{{md,json}}` y `analisis/*.png` |
"""
(ROOT / "docs" / "consultas-y-procedencia.md").write_text(doc, encoding="utf-8")
print("escrito docs/consultas-y-procedencia.md")
