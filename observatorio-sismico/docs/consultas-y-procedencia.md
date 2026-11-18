# Registro de consultas y procedencia

Generado por `scripts/procedencia.py` a partir de `data/raw/historico/manifest.json` y `docs/evidencias/memoria-datos.json` (instantánea 2026-11-18T20:53:24+00:00). Complementa al diccionario de datos (`docs/diccionario-de-datos.md`).

## 1. Fuentes

| Fuente | Qué aporta | Acceso | Licencia / condiciones | Dónde queda |
|---|---|---|---|---|
| USGS Earthquake Catalog, **feed** `all_day.geojson` | Eventos de las últimas 24 h, actualizado cada minuto | HTTP GET cada 60 s (`USGS_FEED_URL`) | Datos del Gobierno de EE. UU., dominio público (FUENTES-Y-LICENCIAS.md) | Originales íntegros comprimidos en `data/raw/live/AAAA/MM/DD/HHMMSS.geojson.gz` (retención `RAW_RETENTION_DAYS`) y cada versión aceptada en `<esquema>.event_message.payload` |
| USGS Earthquake Catalog, **API FDSN** `fdsnws/event/1/query` | Histórico 2025, mundo, M ≥ 4, `eventtype=earthquake` | Descarga mensual con `history_download` (12 consultas; sin subdivisiones necesarias) | Igual que el feed | `data/raw/historico/AAAA-MM.geojson` + `manifest.json`; no se versionan en Git (se regeneran con el procedimiento de `data/README.md`) |
| Natural Earth, Admin 0 Countries 1:110M | 177 entidades con `ADM0_A3`, `NAME_ES`, `ADMIN`, `CONTINENT`, `SUBREGION` | Copia entregada: `frontend/public/datos/paises.geojson` | Dominio público; se conserva el reconocimiento | `ref.dim_country` (cargada por el migrador, con la huella del archivo) |

Huella SHA-256 del catálogo (normalizando CRLF→LF): `6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f`. Coincide con la de FUENTES-Y-LICENCIAS.md: sí.

## 2. Histórico 2025: consultas realizadas

Extracción del 2026-11-17. Parámetros comunes: `format=geojson`, `minmagnitude=4`, `eventtype=earthquake`, `orderby=time-asc`, intervalo mensual `[inicio, fin)`.

| Mes | Intervalo (UTC) | Descargado | Reportado por `count` | Features recibidas | Tamaño | Latencia | SHA-256 |
|---|---|---|---:|---:|---:|---:|---|
| 2025-01 | 2025-01-01 → 2025-02-01 | 2026-11-17 22:13:19 | 1,413 | 1,413 | 973 KiB | 879 ms | `2c667a5944ba…` |
| 2025-02 | 2025-02-01 → 2025-03-01 | 2026-11-17 22:13:22 | 1,394 | 1,394 | 960 KiB | 880 ms | `a68d24cf4220…` |
| 2025-03 | 2025-03-01 → 2025-04-01 | 2026-11-17 22:13:25 | 1,178 | 1,178 | 815 KiB | 754 ms | `70513cbcb1fa…` |
| 2025-04 | 2025-04-01 → 2025-05-01 | 2026-11-17 22:13:29 | 1,316 | 1,316 | 911 KiB | 619 ms | `7ced70eb5d4d…` |
| 2025-05 | 2025-05-01 → 2025-06-01 | 2026-11-17 22:13:32 | 1,228 | 1,228 | 850 KiB | 629 ms | `32284cd14e2a…` |
| 2025-06 | 2025-06-01 → 2025-07-01 | 2026-11-17 22:13:35 | 1,156 | 1,156 | 798 KiB | 615 ms | `9b76da36bb8b…` |
| 2025-07 | 2025-07-01 → 2025-08-01 | 2026-11-17 22:13:38 | 2,684 | 2,684 | 1,879 KiB | 660 ms | `541cb6af35d6…` |
| 2025-08 | 2025-08-01 → 2025-09-01 | 2026-11-17 22:13:41 | 2,222 | 2,222 | 1,550 KiB | 1128 ms | `15ca209876ab…` |
| 2025-09 | 2025-09-01 → 2025-10-01 | 2026-11-17 22:13:44 | 1,604 | 1,604 | 1,121 KiB | 833 ms | `c9abb036f503…` |
| 2025-10 | 2025-10-01 → 2025-11-01 | 2026-11-17 22:13:48 | 1,509 | 1,509 | 1,047 KiB | 865 ms | `52fe4818c019…` |
| 2025-11 | 2025-11-01 → 2025-12-01 | 2026-11-17 22:13:51 | 1,321 | 1,321 | 916 KiB | 906 ms | `c4d7ca695c4e…` |
| 2025-12 | 2025-12-01 → 2026-01-01 | 2026-11-17 22:13:54 | 1,277 | 1,277 | 885 KiB | 964 ms | `af58b4238498…` |
| **Total** | | | **18,302** | **18,302** | **12.4 MiB** | | |

- Comprobación del límite de 20.000: **ninguna consulta lo alcanza** (la mayor trae 2,684); intervalos subdivididos: ninguno. Nunca se trunca en silencio: se pide antes `count` y, si se acercara al límite, se subdivide.
- El número recibido coincide con el reportado en las 12 consultas: sí.
- Deduplicación entre intervalos (los extremos pueden repetirse): 18,302 eventos únicos de 18,302 leídos → 0 duplicados.
- Es una **instantánea** del catálogo en la fecha de extracción, no un registro de todas sus revisiones pasadas.

### 2.1 Catálogo reciente 2026 (comparación equivalente)

Mismos parámetros que el histórico, para la conclusión 4 de la memoria. Se guarda en `data/raw/reciente/` y **no se carga en la base de datos**. Generado por `scripts/comparacion_reciente.py`.

| Intervalo (UTC) | Descargado | Reportado por `count` | Features recibidas | Tamaño | SHA-256 |
|---|---|---:|---:|---:|---|
| 2026-10-01 → 2026-11-01 | 2026-11-18 22:29:26 | 1,592 | 1,592 | 1,095 KiB | `1a8f9f7f2804…` |
| 2026-11-01 → 2026-11-18 | 2026-11-18 22:29:29 | 435 | 435 | 300 KiB | `c871ee19e4c9…` |

- 2,027 eventos M ≥ 4 en 48 días completos. Los días más recientes de una descarga pueden completarse después: el manifiesto fija la fecha de la instantánea.

## 3. Feed en vivo: registro de consultas (`ingest.extraction_log`)

| Concepto | Valor |
|---|---|
| Consultas correctas | 189 (primera 2026-11-17 22:15:14 UTC, última 2026-11-18 20:52:56 UTC) |
| Consultas fallidas | 0 |
| Latencia (ms) | media 123.7, p95 154.6, máx 564 |
| Apariciones de features en las respuestas | 35,621 (cada respuesta repite toda la ventana de 24 h) |
| Versiones publicadas a Kafka (incluye rechazadas) | 471 |
| Publicaciones evitadas por la marca de «ya publicado» | **98.68 %** |
| Originales guardados | 90 archivos distintos; 99 respuestas idénticas no se guardaron de nuevo |

Huecos de ingesta live (más de 5 min entre consultas correctas):

| Desde (UTC) | Hasta (UTC) | Horas | ¿Recuperable con el feed de 24 h? |
|---|---|---:|---|
| 2026-11-17 22:19:34 | 2026-11-18 17:49:50 | 19.5 | sí |

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
| Complejidad, tiempo y memoria | `scripts/medir_complejidad.py` → `docs/evidencias/complejidad.{json,md}` (datos sintéticos, base temporal) |
| Latencia de la API | `scripts/medir_api.py` → `docs/evidencias/api-latencia.json` |
| Pruebas de aceptación | `tests/acceptance/` → `docs/evidencias/aceptacion-s11.{md,json}` y `pila-real.md` |
| Panel y túnel | `tests/e2e/` → `docs/evidencias/panel*.{md,json}` y `analisis/*.png` |
