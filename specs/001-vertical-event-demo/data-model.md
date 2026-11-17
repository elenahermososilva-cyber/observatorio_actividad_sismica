# Modelo de datos para la primera entrega vertical

Fuente de verdad: `observatorio-sismico/backend/db/schema.sql` (migración 001), `backend/db/migrations/` y `backend/producer/schema.py` (`EventMessage`). Este documento describe ese modelo; si discrepan, manda el código.

> **Actualización (Fase 6).** Las tablas descritas abajo ya no viven en `public`: existen con el mismo DDL en un esquema por modo (`demo`, `live`, `replay`, `historico`) y `event_current` tiene columnas desnormalizadas. Véase la sección «Ampliación de la Fase 6» al final.

## Mensaje de Kafka: `EventMessage`

Es lo que el productor publica (clave Kafka = `event_id`) y el consumidor valida.

| Campo | Significado |
|---|---|
| `event_id` | Identificador estable del evento. |
| `source` | Origen: `synthetic-demo` en esta entrega; `usgs` en live. |
| `mode` | `demo`, `live` o `replay`. Esta entrega solo publica `demo`. |
| `synthetic_flag` | `demo` ⇒ `true`; `live` ⇒ `false`; `replay` admite ambos. |
| `ingested_at` | Instante de ingestión, UTC (ISO 8601). Distinto de la ocurrencia y de la actualización. |
| `updated` | Versión de la fuente: ms Unix UTC. Debe coincidir con `payload.properties.updated`. |
| `payload` | Feature GeoJSON original (Point, `properties.time`, `properties.updated`, `properties.type`…). |

Cuatro marcas temporales que no se mezclan: **ocurrencia** (`payload.properties.time`), **actualización de la fuente** (`updated`), **ingestión** (`ingested_at`) y **reproducción** (Fase 7; no existe aún).

## Tablas PostgreSQL

### `event_message`: historial de versiones aceptadas
Una fila por `(event_id, updated_ms)` (`UNIQUE`). Guarda el payload original (`JSONB`), `source`, `mode`, `ingested_at` y `synthetic_flag`. Una versión antigua que llega tarde también se guarda aquí, pero no pasa a `event_current`.

### `event_current`: estado actual
Una fila por `event_id` (clave primaria). Contiene `message_id`, `current_version_ms` y `last_seen_at`; una clave foránea compuesta `(message_id, event_id, current_version_ms)` hacia `event_message` garantiza que apunta a una versión real del mismo evento. El payload se obtiene uniendo con `event_message`. Solo se reemplaza si la versión nueva es **estrictamente mayor**.

### `quarantine_record`: rechazos durables
`reason` (código + detalle, por ejemplo `invalid_coordinates: latitude must be between -90 and 90`), `original_payload` (texto exacto recibido), `event_id` y `source` si se pudieron recuperar, y la referencia Kafka `(kafka_topic, kafka_partition, kafka_offset)`, única para que reprocesar un offset no duplique la fila.

Motivos actuales: `invalid_json`, `schema_violation`, `invalid_coordinates`, `non_earthquake_type`, `persistence_constraint`.

### `schema_migrations`
Control del migrador (`version`, `name`, `checksum`, `applied_at`).

## Decisión del consumidor (`classify_version`)

| Situación | Decisión | Efecto |
|---|---|---|
| No existe el evento | `NEW` | Inserta historial y estado actual. |
| Misma versión | `DUPLICATE` | Sin cambios. |
| `updated` mayor | `REVISION` | Inserta historial y reemplaza el estado actual. |
| `updated` menor | `STALE` | Inserta en el historial; el estado actual no cambia. |

## Reglas

- Debe existir una sola fila activa por `event_id`.
- Todo rechazo (JSON inválido, esquema, coordenadas, tipo distinto de `earthquake`) queda en `quarantine_record`; nunca se descarta en silencio.
- Un fallo de infraestructura (PostgreSQL caído) **no** escribe en cuarentena: no hay base donde hacerlo. El offset no se confirma y se reintenta el mismo mensaje.
- Una magnitud nula es válida y se conserva como `null`.

## Respuesta de la API (`GET /api/eventos`)

Proyección de `event_current` + `event_message`; no es una tabla. Véase `contracts/api-eventos.md`. `country_id`/`country_name` son `null` hasta que exista la asignación punto-en-polígono (fase posterior).

## Fuera del alcance de la entrega vertical

Histórico, enriquecimiento geográfico, estadísticas. Se añadieron mediante migraciones posteriores sin editar la 001 (el migrador rechaza una migración modificada tras aplicarse).

## Ampliación de la Fase 6

**Esquemas (D2).** `demo`, `live`, `replay` e `historico` contienen `event_message`, `event_current` y `quarantine_record` con DDL idéntico (el test de migraciones lo comprueba columna a columna e índice a índice). El consumidor elige el esquema por topic (`sismos.demo|live|replay`) y rechaza con `mode_mismatch` un mensaje cuyo `mode` no coincida con el de su topic. La API elige el esquema con el parámetro `mode` (lista cerrada, nunca texto libre en SQL). Los datos de la entrega vertical, que estaban en `public`, se movieron a `demo` conservando filas, restricciones e índices. `public` solo conserva `schema_migrations`.

**Migraciones.** 002 esquemas + `ref.dim_country`; 003 tablas base por esquema; 004 columnas de `event_current`; 005 índices; 006 estado de ingesta. Las marcadas `-- @per-schema` se ejecutan una vez por esquema de modo.

**Columnas de `event_current`** (unidades: ms Unix UTC, km, grados WGS84): `time_ms` (ocurrencia), `mag` (`NULL` = ND, nunca 0), `mag_type`, `depth_km` (`NULL` si falta; los valores negativos se conservan), `lon`, `lat`, `place` (descriptivo; no se usa para el país), `event_type`, `ingested_at`, `country_id`, `country_status`. La versión de la fuente sigue siendo `current_version_ms`. El payload original permanece intacto en `event_message`.

**País.** `country_status` ∈ `pending` (sin atribuir aún), `unassigned` («Sin país asignado»: fuera de todo polígono, no es un error) y `assigned`. Una restricción garantiza `assigned ⇔ country_id no nulo` y una clave foránea apunta a `ref.dim_country(country_id)`. Una revisión que reemplaza la versión actual devuelve el país a `pending` porque el epicentro pudo moverse; la Fase 8 lo recalcula.

**Dimensión país.** `ref.dim_country` (ADM0_A3, NAME_ES, ADMIN, CONTINENT, SUBREGION, SHA-256 de origen) se carga al migrar, tras comprobar que `ADM0_A3` es único (177 entidades). La geometría no se guarda: el punto-en-polígono usa el GeoJSON en memoria. No se crea `dim_date`: las ventanas de una hora UTC se obtienen con `time_ms` y `date_trunc`, sin tabla adicional.

**Índices** (justificación en `005_event_current_indexes.sql`): `(time_ms DESC)` para ventanas y orden; `(country_id, time_ms DESC)` para filtro y recuentos por país; `(mag)` parcial sin nulos para `min_mag` (la magnitud nula nunca lo cumple); `(country_status)`.

**Estado de ingesta (D1).** `ingest.published_version (mode, event_id, updated_ms)` marca versiones publicadas tras el ack de Kafka; `ingest.extraction_log` registra cada consulta a USGS (URL, latencia, estado HTTP, nº de registros, hash del contenido, archivo original y error). Solo las consultas `ok` mueven `last_ingestion`. Las escribe el productor live (Fase 7). `response_sha256` es el hash de las `features` (no de los bytes: `metadata.generated` cambia cada minuto) y sirve para no guardar originales idénticos.

## Fase 7: tiempo de reproducción y modos

**`replay_at`** (migración 007, `event_message`): cuarta marca temporal, distinta de la ocurrencia (`payload.properties.time`), la actualización de la fuente (`updated_ms`) y la ingestión (`ingested_at`). Una restricción de base de datos exige `mode = 'replay' ⇔ replay_at no nulo`, de modo que ni un `INSERT` directo puede saltarse la regla. `EventMessage` la valida igual (UTC, obligatoria en replay y prohibida en los demás modos).

**Mensajes por modo.** `live`: `source="usgs"`, `synthetic_flag=false`, `payload` = el Feature original de USGS. `replay`: `source="usgs-history"` (datos reales) o `"replay-injected"` (revisión fabricada, `synthetic_flag=true`), más `replay_at`. El productor empaqueta todo lo que recibe: lo que no cumple el contrato (coordenadas fuera de rango, sin `id`…) se envía igualmente con el payload intacto y el consumidor lo pone en cuarentena con su motivo; el productor nunca descarta en silencio. Un feature sin `id` o `updated` válidos recibe la clave de deduplicación `invalid:<sha256 del contenido>`, así se rechaza una vez y no cada minuto durante las 24 h que permanece en el feed.
