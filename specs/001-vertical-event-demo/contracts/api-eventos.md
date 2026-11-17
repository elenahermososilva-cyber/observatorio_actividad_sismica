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
- `mode` (`demo` | `live` | `replay`) elige los datos, aislados por modo en esquemas distintos de PostgreSQL. Si se omite, se usa `API_DEFAULT_MODE` (`live` si no está definida; `.env.example` la fija en `demo` mientras no exista ingesta live). `metadata.mode` devuelve el modo consultado. Cualquier otro valor (incluido `historico`) devuelve HTTP 400. Los datos de un modo nunca aparecen en las consultas de otro.
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

## Alcance de la primera entrega

El contrato de esta fase se limita a la demostración vertical del evento sintético y no incluye filtros avanzados, estadísticas históricas ni publicación en Netlify.
