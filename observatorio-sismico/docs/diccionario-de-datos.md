# Diccionario de datos

Describe cada campo que usa el sistema: el mensaje de Kafka, las tablas de PostgreSQL y la respuesta de la API. La fuente de verdad es el código (`backend/db/schema.sql`, `backend/db/migrations/`, `backend/producer/schema.py`); este documento se contrastó con el catálogo real de la base (`information_schema` y `pg_constraint`). Convenciones: **todo tiempo en UTC**; tiempos de la fuente en **milisegundos Unix**; profundidad en **km**; coordenadas **WGS84 (EPSG:4326)** en grados, orden **longitud, latitud**.

Cada modo tiene su propio esquema con tablas idénticas: `demo`, `live`, `replay` e `historico`. Los nombres de abajo (`event_message`, `event_current`, `quarantine_record`) existen en los cuatro; las restricciones `CHECK` impiden que un esquema admita un modo ajeno.

## 1. Origen: Feature GeoJSON de USGS

| Campo | Tipo | Unidad | ¿Opcional? | Significado y tratamiento |
|---|---|---|---|---|
| `id` | texto | — | no | Identificador estable del evento → `event_id`. Un Feature sin `id` es un registro mal formado: va a cuarentena (`schema_violation`) con clave `invalid:<sha256>` |
| `geometry.coordinates[0]` | número | grados | no | Longitud, −180…180 → `lon` |
| `geometry.coordinates[1]` | número | grados | no | Latitud, −90…90 → `lat` |
| `geometry.coordinates[2]` | número | **km** | sí | Profundidad → `depth_km`. Puede faltar (NULL) o ser negativa; ambos casos se conservan |
| `properties.time` | entero | **ms Unix UTC** | no | **Ocurrencia** → `time_ms` |
| `properties.updated` | entero | **ms Unix UTC** | no | **Versión de la fuente** → `updated_ms` / `current_version_ms` |
| `properties.mag` | número | magnitud (adimensional, tipos mixtos) | **sí** | Puede ser `null` (se conserva NULL, se muestra ND; nunca se sustituye por 0) y puede ser negativa (válida) |
| `properties.magType` | texto | — | sí | Tipo de magnitud (`mb`, `mww`, `ml`, `md`…); se pasa a minúsculas si llega en mayúsculas |
| `properties.place` | texto | — | sí | Descripción del lugar. **No se usa para atribuir país** |
| `properties.type` | texto | — | no | Solo `earthquake` se acepta; `explosion`, `quarry blast`… van a cuarentena con el tipo en el motivo |

## 2. Mensaje de Kafka (`EventMessage`, clave = `event_id`)

| Campo | Tipo | Significado |
|---|---|---|
| `event_id` | texto | Igual que el `id` del Feature; clave Kafka (garantiza orden por evento) |
| `source` | texto | `usgs` (feed live), `usgs-catalog` (histórico cargado), `usgs-history` (reproducción de histórico real), `replay-injected` (caso fabricado para la demostración), `synthetic-demo` (evento ficticio del modo demo) |
| `mode` | `demo` / `live` / `replay` / `historical` | Debe coincidir con el topic y con el esquema; si no, se rechaza (`mode_mismatch`) |
| `synthetic_flag` | booleano | `demo` ⇒ true; `live` ⇒ false; `replay` admite ambos (los casos inyectados son sintéticos) |
| `ingested_at` | instante UTC | **Ingestión**: cuándo lo recibió/preparó el sistema. Distinta de ocurrencia y actualización |
| `replay_at` | instante UTC | **Reproducción**: obligatorio en `replay`, prohibido en los demás modos |
| `updated` | entero (ms) | Versión; debe coincidir con `payload.properties.updated` |
| `payload` | objeto | El Feature original, sin modificar |

Las **cuatro marcas temporales** que nunca se mezclan: ocurrencia (`time`), actualización de la fuente (`updated`), ingestión (`ingested_at`) y reproducción (`replay_at`).

## 3. `event_message`: historial de versiones aceptadas

Grano: **una fila por versión** `(event_id, updated_ms)`. Guarda el original; nunca se sobrescribe.

| Columna | Tipo | Nulos | Significado |
|---|---|---|---|
| `message_id` | bigint (identidad) | no | Clave primaria interna |
| `event_id` | texto | no | Identificador del evento (no vacío) |
| `updated_ms` | bigint ≥ 0 | no | Versión de la fuente (ms Unix UTC) |
| `source` | texto | no | Ver §2 |
| `mode` | texto | no | `demo`/`live`/`replay`/`historical`; el esquema solo admite el suyo |
| `ingested_at` | timestamptz | no | Ingestión |
| `synthetic_flag` | boolean | no | Dato sintético |
| `payload` | jsonb (objeto) | no | Feature original íntegro |
| `replay_at` | timestamptz | sí | `mode = 'replay'` ⇔ no nulo (restricción de base de datos) |

Restricciones: `UNIQUE (event_id, updated_ms)` (impide que un reenvío aumente el recuento), `UNIQUE (message_id, event_id, updated_ms)` (destino de la clave foránea de `event_current`). Índice: `ingested_at`.

## 4. `event_current`: estado actual (hecho evento)

Grano: **una fila por `event_id`**. Se reemplaza solo si llega una versión estrictamente mayor.

| Columna | Tipo | Nulos | Unidad | Origen / transformación |
|---|---|---|---|---|
| `event_id` | texto | no | — | Clave primaria |
| `message_id` | bigint | no | — | Versión vigente; clave foránea compuesta `(message_id, event_id, current_version_ms)` → `event_message` |
| `current_version_ms` | bigint | no | ms | `updated` de la versión vigente |
| `last_seen_at` | timestamptz | no | UTC | Última vez que se vio el evento |
| `time_ms` | bigint | no | ms Unix UTC | `properties.time` (ocurrencia) |
| `mag` | double | **sí** | magnitud | `properties.mag`; NULL = ND |
| `mag_type` | texto | sí | — | `magType` en minúsculas |
| `depth_km` | double | sí | km | `coordinates[2]` |
| `lon` / `lat` | double | no | grados | `coordinates[0]` / `[1]`; `CHECK` de rango |
| `place` | texto | sí | — | `properties.place` sin espacios sobrantes (vacío → NULL) |
| `event_type` | texto | no | — | Siempre `earthquake` (lo demás no entra) |
| `ingested_at` | timestamptz | no | UTC | Ingestión de la versión vigente |
| `country_id` | texto | sí | — | `ADM0_A3` de `ref.dim_country` por **punto en polígono**; NULL si no hay país |
| `country_status` | texto | no | — | `pending` (sin evaluar), `unassigned` («Sin país asignado») o `assigned`; `assigned ⇔ country_id` no nulo |
| `quality_flags` | texto[] | sí | — | NULL = no evaluado; `{}` = evaluado sin avisos; ver §8 |

Índices: `(time_ms DESC)` (ventanas y orden), `(country_id, time_ms DESC)` (filtro y recuentos por país), `(mag)` parcial `WHERE mag IS NOT NULL` (`min_mag`), `(country_status)`.

## 5. `quarantine_record`: rechazos durables

| Columna | Tipo | Nulos | Significado |
|---|---|---|---|
| `quarantine_id` | bigint (identidad) | no | Clave primaria |
| `event_id` | texto | sí | Si se pudo recuperar |
| `source` | texto | sí | Si se pudo recuperar |
| `reason` | texto | no | `<código>: <detalle>`; códigos: `invalid_json`, `schema_violation`, `invalid_coordinates`, `non_earthquake_type`, `mode_mismatch`, `persistence_constraint` |
| `original_payload` | texto | no | Texto exacto recibido |
| `created_at` | timestamptz | no | Cuándo se rechazó |
| `kafka_topic`, `kafka_partition`, `kafka_offset` | texto, int, bigint | sí (todos o ninguno) | Referencia al original; única por offset, de modo que reprocesar no duplica. En carga por lotes, `file:<archivo>` + posición |

## 6. Esquema `ingest`: estado de la ingesta

**`ingest.published_version`** — versiones ya publicadas a Kafka (marcadas **tras** el ack): `mode`, `event_id`, `updated_ms`, `published_at`; clave `(mode, event_id, updated_ms)`.

**`ingest.extraction_log`** — una fila por consulta a USGS:

| Columna | Significado |
|---|---|
| `extraction_id` | Clave |
| `mode`, `source_url` | Modo y URL consultada |
| `started_at` | Inicio de la consulta (UTC) |
| `latency_ms`, `http_status` | Latencia y código HTTP (nulos si no hubo respuesta) |
| `ok` | Consulta correcta; **solo las correctas mueven `last_ingestion`** |
| `record_count` | Features recibidas |
| `response_bytes`, `response_sha256` | Tamaño y hash del **contenido** (`features`), no de los bytes: `metadata.generated` cambia cada minuto |
| `raw_path` | Archivo original (gzip) si se guardó; NULL si la respuesta era idéntica a otra ya guardada |
| `error` | Obligatorio si `ok` es falso; nulo si es verdadero |

## 7. `ref.dim_country`: dimensión país (Natural Earth)

| Columna | Origen | Significado |
|---|---|---|
| `country_id` | `ADM0_A3` | Clave (única; **no se asume que sea ISO oficial**) |
| `name_es` | `NAME_ES` | Nombre en español |
| `admin` | `ADMIN` | Nombre administrativo |
| `continent` | `CONTINENT` | Continente |
| `subregion` | `SUBREGION` | Subregión (agrupación alternativa en el análisis) |
| `source_sha256` | — | Huella SHA-256 del archivo de origen (normalizando CRLF→LF) |
| `loaded_at` | — | Cuándo se cargó |

177 entidades, 177 `ADM0_A3` distintos. La geometría no se guarda: el punto-en-polígono usa el GeoJSON en memoria (`backend/consumer/geo.py`).

## 8. Códigos de `quality_flags`

| Código | Tipo | Significado |
|---|---|---|
| `gap_mag_missing` | hueco | Magnitud ausente (NULL, ND) |
| `gap_mag_type_missing` | hueco | Hay magnitud pero no su tipo |
| `gap_depth_missing` | hueco | Profundidad ausente |
| `gap_place_missing` | hueco | Sin descripción del lugar |
| `anomaly_mag_negative` | anomalía | Magnitud negativa: válida, se conserva |
| `anomaly_mag_out_of_range` | anomalía | Magnitud fuera de [−2, 10] |
| `anomaly_depth_negative` | anomalía | Profundidad negativa: se conserva |
| `anomaly_depth_very_large` | anomalía | Profundidad > 800 km |
| `anomaly_time_in_future` | anomalía | Ocurrencia posterior a la ingestión (más allá de la tolerancia de reloj) |
| `anomaly_updated_before_time` | anomalía | Actualización anterior a la ocurrencia |
| `fixed_place_trimmed` | transformación | Se quitaron espacios sobrantes de `place` |
| `fixed_place_blank_to_null` | transformación | `place` vacío → NULL |
| `fixed_mag_type_lowercased` | transformación | `magType` pasado a minúsculas |
| `country_boundary_ambiguous` | geografía | El punto cae sobre una frontera que cumple varios países (se elige el menor `ADM0_A3`) |

Los avisos señalan; solo las transformaciones `fixed_*` cambian el dato, y el original permanece intacto en `event_message.payload`.

## 9. Respuesta de la API

**`GET /api/eventos`** — FeatureCollection. Cada Feature: `id`, `geometry.coordinates = [lon, lat, depth_km|null]`, `properties`: `mag` (número o `null`), `magType`, `place`, `time` (ms), `updated` (ms), `country_id`, `country_name` (`null` = sin país asignado). `metadata`: `generated`, `last_ingestion`, `mode`, `count`, `truncated`, `total`, `limit`, `offset`, `next_offset`, `null_mag_count`, `null_mag_excluded`, `start`, `end`, `filters`.

**`GET /api/estadisticas`** — `totals`, `hourly` (hora UTC fija, con ceros), `groups` (por país o subregión, con «Sin país asignado»), `distributions` (magnitud cada 0,5; profundidad cada 10 km; registros sin valor), `historical_comparison` (últimas 24 h frente a la media diaria de 2025 con 365 días, más mediana, mínimo y máximo). Cada sección declara periodo, filtros, unidad y registros sin valor.

**`GET /api/salud`** — `status` (`ok`/`stale`/`error`), `database`, `last_ingestion`, `stale`, `stale_after_seconds`, `seconds_since_last_ingestion`, `stale_reason`.

Detalle de parámetros y errores: `specs/001-vertical-event-demo/contracts/api-eventos.md` y `CONTRATO-API.md`. Registro de consultas y procedencia: `docs/consultas-y-procedencia.md`.
