# Contrato de la API para la primera entrega vertical

## GET /api/eventos

**Descripción**: devuelve los eventos activos visibles para la demostración vertical del sistema.

**Resultado esperado**:
- Código HTTP: 200 si la consulta es válida y puede devolver el conjunto de eventos.
- Tipo de contenido: `application/json`.
- Cuerpo: GeoJSON `FeatureCollection` con estructura válida.

**Schema funcional**
```json
{
  "type": "FeatureCollection",
  "metadata": {
    "generated": 1793113200000,
    "last_ingestion": 1793113140000,
    "mode": "demo",
    "count": 1,
    "truncated": false
  },
  "features": [
    {
      "type": "Feature",
      "id": "demo-evt-001",
      "geometry": {
        "type": "Point",
        "coordinates": [-3.7, 40.4, 12]
      },
      "properties": {
        "mag": 3.2,
        "magType": "ml",
        "place": "Evento de prueba sintético",
        "time": 1793109600000,
        "updated": 1793110000000,
        "country_id": "ESP",
        "country_name": "España"
      }
    }
  ]
}
```

**Reglas contractuales**
- Cada evento visible debe aparecer una sola vez.
- La respuesta debe ser `FeatureCollection` y no un array plano.
- `features: []` solo es válido cuando la consulta correcta no devuelve resultados reales.
- Los datos deben reportar `generated`, `last_ingestion`, `mode`, `count` y `truncated` con semántica definida.
- No se aceptan valores no finitos ni representaciones inválidas de coordenadas o magnitudes.

## GET /api/salud

**Descripción**: devuelve el estado del servicio API y la última ingesta conocida.

**Reglas**
- Debe devolver un estado explícito del servicio.
- Debe indicar si la última ingesta de prueba ha sido correcta o si el sistema está degradado.
- No debe depender de secretos ni credenciales para la validación local.

## Tratamiento de errores

**Separación de responsabilidades entre consumidor y API**
- Un fallo de persistencia del consumidor NO se comunica como un `FeatureCollection` vacío. El consumidor debe registrar el error, conservar la carga en cuarentena y no confirmar el offset hasta que la escritura en PostgreSQL quede duradera.
- La API solo puede devolver un error explícito para fallos que pueda observar directamente en su propia consulta o en un estado de salud definido por el contrato. Si no existe un mecanismo de estado definido para el consumidor, la API no debe afirmar que conoce el fallo de persistencia del consumidor.
- La respuesta debe comunicar explícitamente el error o un estado de servicio no disponible.
- La ausencia de datos solo debe representarse como `features: []` cuando la operación fue exitosa y la base realmente no tiene resultados.

## Filtros y ventana temporal (implementado en la Fase 4)

- `start` (ISO8601, **inclusivo**) y `end` (ISO8601, **exclusivo**) filtran por el tiempo de **ocurrencia** (`properties.time`). Sin zona horaria se interpreta UTC.
- Sin parámetros, la ventana es `[ahora - 24 h, ∞)`. El evento sintético `demo-evt-001` ocurre el 2026-10-27T14:00:00Z, así que la verificación de la demo debe pasar una ventana explícita, por ejemplo `GET /api/eventos?start=2026-10-27T00:00:00Z`. No se alteran las fechas del evento para que aparezca.
- `mode` (`demo` | `live` | `replay` | `historico`) elige los datos, aislados por modo en esquemas distintos de PostgreSQL. `historico` es **solo de lectura**: expone la carga única del catálogo 2025 (nunca llega por Kafka ni puede ser `API_DEFAULT_MODE`); lo usa la pestaña «Histórico 2025» del panel con `limit`/`offset`. Si se omite, se usa `API_DEFAULT_MODE` (`live` si no está definida). `metadata.mode` devuelve el modo consultado. Cualquier otro valor (por ejemplo `historical` o `public`) devuelve HTTP 400. Los datos de un modo nunca aparecen en las consultas de otro.
- `start >= end` o una fecha no parseable devuelven HTTP 400.
- `metadata` añade `total` (eventos que cumplen el filtro, aunque se trunque), `start` y `end` (ms Unix; `end` puede ser `null`).
- `metadata.last_ingestion` (ms Unix UTC; `null` si no hay ninguna): en modo `live` es el inicio de la **última consulta correcta a USGS** (`ingest.extraction_log`, `ok = true`), que avanza aunque no haya eventos nuevos y se detiene si el productor falla o USGS no responde; una consulta fallida no la mueve. En `demo` y `replay`, que no consultan a USGS, es la última ingesta de mensajes aceptada en ese modo.
- `country_id` y `country_name` son `null` hasta la asignación punto-en-polígono (Fase 8). `country_name` sale de `ref.dim_country`.

## Contrato de errores (T008)

Cuerpo común: `{"error": {"code": "<código>", "message": "<texto>"}}`. Nunca contiene `features`.

| HTTP | `code` | Cuándo |
|---|---|---|
| 200 | — | Consulta correcta. `features: []` solo aquí: la base respondió y no hay eventos. |
| 400 | `invalid_parameter` | Fecha no ISO8601, `start >= end`. |
| 503 | `database_unavailable` | La consulta a PostgreSQL falla o no hay conexión. |
| 500 | `internal_error` | Error inesperado; sin detalles internos en la respuesta. |

`GET /api/salud` devuelve 200 con `{"status":"ok","api":"ok","database":"ok","generated":...,"last_ingestion":...}`. Si la base falla devuelve 503 con `status:"error"`, `database:"unavailable"` y el bloque `error`. No contiene credenciales ni URLs.

La API solo informa de lo que observa en su propia consulta. **No existe un estado del consumidor en el contrato**, así que la API no afirma nada sobre él: un fallo del consumidor se aprecia en sus logs, en el retraso del grupo de Kafka y en que `last_ingestion` deja de avanzar. Si PostgreSQL cae mientras el consumidor procesa, este no confirma el offset y reintenta; no escribe en cuarentena porque no hay base donde hacerlo (la cuarentena es para datos inválidos).

## API completa (Fase 9)

Implementa `CONTRATO-API.md` completo. Todos los parámetros se validan antes de consultar la base: un valor inválido devuelve HTTP 400 sin tocarla.

### `GET /api/eventos`: filtros y paginación

| Parámetro | Significado |
|---|---|
| `start` / `end` | ISO8601; `start` inclusivo, `end` exclusivo, sobre el tiempo de ocurrencia. Sin `start`: últimas 24 h. |
| `min_mag` | Magnitud mínima (número finito entre -10 y 10; `nan`, `inf` y texto dan 400). **Una magnitud nula nunca la cumple.** `0` es un umbral real, no «sin filtro». |
| `country_id` | Código `ADM0_A3` (insensible a mayúsculas) o **`none`** para «Sin país asignado». Un código que no existe en el catálogo da 400 (no un resultado vacío que oculte una errata); un país válido sin eventos da 200 con `features: []`. |
| `mode` | `demo`, `live`, `replay` o `historico` (datos aislados; `historico`, solo lectura). |
| `limit` | Máximo de puntos por respuesta, de 1 a `API_MAX_FEATURES` (5000). Un valor mayor da 400: no se recorta en silencio. Por defecto, el máximo. |
| `offset` | Desplazamiento para paginar (≥ 0). |

Orden estable: ocurrencia descendente y, a igualdad, `id`. Todas las lecturas de una respuesta usan una instantánea (`REPEATABLE READ`), así que `total` y la página son coherentes. Para recorrer varias páginas sin que los eventos nuevos desplacen la ventana, fija `end`.

Campos añadidos a `metadata` (los del contrato se conservan):

| Campo | Significado |
|---|---|
| `total` | Eventos que cumplen los filtros, en **todas** las páginas. |
| `truncated` | `true` si quedan eventos más allá de esta página. El panel no debe calcular estadísticas globales con una respuesta truncada: para eso existe `/api/estadisticas`. |
| `limit`, `offset`, `next_offset` | Paginación; `next_offset` es `null` en la última página. |
| `null_mag_count` | Eventos de magnitud nula **dentro** del resultado (se muestran como ND). |
| `null_mag_excluded` | Con `min_mag`: eventos de magnitud nula que cumplen el resto de filtros y quedan fuera por no poder satisfacerlo. Se contabilizan por separado, como exige el contrato. |
| `filters` | `{min_mag, country_id}` efectivos. |

### `GET /api/estadisticas`

Acepta los mismos `start`, `end`, `min_mag`, `country_id` y `mode` que `/api/eventos` (**misma semántica y mismo SQL**: un test comprueba que el total coincide con el del mapa para cada combinación) y además `group` (`country` por defecto, o `subregion`) y `baseline_year` (2025 por defecto). Se calcula en la base de datos sobre **todos** los eventos filtrados, nunca sobre una página ni una muestra, y siempre desde `event_current`: una revisión o un duplicado no puede contarse dos veces.

Cada sección (`totals`, `hourly`, `groups`, `distributions.magnitude`, `distributions.depth_km`) declara su `period`, sus `filters`, su `unit` y sus registros sin valor (`missing`).

| Sección | Contenido |
|---|---|
| `totals` | `events` y `missing` (magnitud y profundidad). |
| `hourly` | Serie por **hora UTC fija** según el tiempo de ocurrencia, con ceros explícitos (`zero_filled`). Con más de 2.000 horas solo devuelve las que tienen eventos (`zero_filled: false`). El primer y el último intervalo pueden ser parciales si `start`/`end` no están alineados a la hora. |
| `groups` | `hourly`: recuentos por hora y país (o subregión); `totals`: ranking. Incluye **«Sin país asignado»** (`key: null`) como grupo propio, distinto de `pending` (aún sin atribuir). |
| `distributions` | Histogramas de magnitud (intervalos de 0,5) y profundidad (10 km), `[from, to)`, solo intervalos con eventos; `with_value` y `missing` suman el total. Las magnitudes y profundidades negativas se incluyen. |
| `historical_comparison` | Últimas 24 h frente a la media diaria del año de referencia. Ver abajo. |

**Comparación histórica.** Cuenta los terremotos de las 24 h anteriores a `end` (o a «ahora») en el modo consultado y los compara con el histórico del año `baseline_year`, **con los mismos filtros** de país y un umbral de magnitud común: `max(min_mag, 4)`, porque el histórico solo contiene M ≥ 4 (con `min_mag < 4` se compara a 4 y se indica). El denominador son **todos los días del año** (365 o 366), incluidos los que no tuvieron eventos; además de `mean_per_day` se devuelven `median_per_day`, `min_per_day` y `max_per_day` calculados sobre los mismos días, porque una jornada extrema (en 2025, 645 eventos el día de la secuencia de réplicas de Kamchatka) desplaza la media: en 2025 la media es 50,1 y la mediana 43. Si el histórico no está cargado, `baseline` es `{"available": false, "reason": "historico_not_loaded"}` y `ratio_vs_daily_mean` es `null`: nunca una media de cero. `caveats` recoge las salvedades que pide el enunciado (el periodo reciente puede estar incompleto por retrasos; el histórico es una instantánea; la cobertura y los tipos de magnitud varían; no es una predicción ni una evaluación de riesgo).

### `GET /api/salud`

Parámetro opcional `mode` (por defecto `API_DEFAULT_MODE`). Respuesta:

| Campo | Significado |
|---|---|
| `status` | `ok`, `stale` (HTTP 200: la API y la base funcionan pero los datos live ya no se actualizan) o `error` (HTTP 503: la base no responde). |
| `database` | `ok` o `unavailable`. |
| `last_ingestion` | Última consulta correcta a USGS (live) o última ingesta aceptada (demo/replay). |
| `stale` | `true`/`false` en live; `null` en demo y replay, que no esperan una ingesta continua. |
| `stale_after_seconds`, `seconds_since_last_ingestion`, `stale_reason` | Umbral (`STALE_AFTER_SECONDS`, 300 por defecto), antigüedad y motivo (`no_successful_query` o `last_successful_query_too_old`). Una consulta fallida no refresca la frescura. |

### CORS

`CORS_ORIGINS` (lista de **orígenes exactos** separados por comas) se lee al arrancar. Por defecto, `http://localhost:4200`. Un comodín `*` o un origen mal formado (sin esquema, con ruta) detiene el arranque; una barra final se elimina avisando en el log. Solo se permiten los métodos `GET` y `OPTIONS` y la cabecera `ngrok-skip-browser-warning`; no hay cookies ni credenciales. El preflight lo atiende `CORSMiddleware`; un origen no listado recibe 400 y ninguna cabecera `Access-Control-Allow-Origin`. Las respuestas de error (400, 503) también llevan CORS para que el panel pueda leerlas. Una excepción no controlada (500) la genera una capa anterior al middleware y no lleva cabeceras CORS: es un fallo de programación, no un estado normal.

**Para autorizar Netlify cuando exista su URL:** añádela en `.env` y recrea la API (no hace falta reconstruir la imagen):

```bash
CORS_ORIGINS=http://localhost:4200,https://mi-sitio.netlify.app
docker compose up -d --force-recreate api
```

CORS no es autenticación: solo indica al navegador qué páginas pueden leer la respuesta. La API es de solo consulta y pública.

### Superficie expuesta

Solo existen `GET /api/eventos`, `GET /api/estadisticas` y `GET /api/salud` (más el preflight `OPTIONS`). No hay documentación interactiva, ni rutas de administración, ni acceso a la base de datos o al broker; cualquier otra ruta da 404 y cualquier otro método 405. Un fallo de base de datos devuelve 503 en los tres endpoints, nunca un resultado vacío.
