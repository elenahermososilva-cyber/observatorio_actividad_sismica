# Contrato de la API para la primera entrega vertical

## GET /api/eventos

**Descripción**: devuelve los eventos activos visibles para la demostración vertical del sistema.

**Resultado esperado**:
- Código HTTP: 200 si la consulta es válida y puede devolver el conjunto de eventos.
- Tipo de contenido: `application/json`.
- Cuerpo: GeoJSON `FeatureCollection` con estructura válida.
- La entrega de demostración devuelve los terremotos ocurridos en las últimas 24 horas, conforme al contrato base; no implementa filtros adicionales en esta fase.
- Los valores `metadata.generated` y `metadata.last_ingestion`, así como las propiedades temporales `time` y `updated`, se expresan como milisegundos desde la época Unix en UTC. `time` es la ocurrencia del evento; `updated` es la actualización de la fuente. `last_ingestion` es la hora de ingesta más reciente conocida y no sustituye a los tiempos del evento.
- Las coordenadas usan longitud y latitud en grados decimales; la tercera coordenada, cuando esté presente, representa profundidad en kilómetros. La magnitud se expresa junto con su tipo en `magType`.
- En esta entrega las propiedades incluyen `source` y `synthetic_flag` para identificar inequívocamente el evento sintético. Al diferirse el enriquecimiento geográfico, `country_id` y `country_name` se conservan como `null`; no se infiere país desde `place` ni por proximidad.
- `metadata.last_ingestion` es `null` si aún no se ha persistido ningún mensaje.
- El mensaje/estado interno conserva también `replayed_at`, distinto de los tiempos anteriores; es nulo en esta prueba que no usa replay.

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
        "coordinates": [-20, 0, 12]
      },
      "properties": {
        "mag": 3.2,
        "magType": "ml",
        "place": "Evento de prueba sintético",
        "time": 1793109600000,
        "updated": 1793110000000,
        "country_id": null,
        "country_name": null,
        "source": "synthetic-demo",
        "synthetic_flag": true
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
- La consulta exitosa no devuelve errores ni conjuntos truncados en esta demostración de un solo evento; cualquier fallo observable de consulta se comunica con un error HTTP explícito.
- No se aceptan valores no finitos ni representaciones inválidas de coordenadas o magnitudes.

## GET /api/salud

**Descripción**: devuelve el estado observable del servicio API y de sus dependencias de consulta, incluida PostgreSQL si la comprobación está implementada.

**Reglas**
- Debe devolver un estado explícito del servicio.
- No debe afirmar que la última ingesta del consumidor fue correcta o falló, porque esta entrega no define un canal de estado entre consumidor y API.
- No debe depender de secretos ni credenciales para la validación local.

## Tratamiento de errores

**Separación de responsabilidades entre consumidor y API**
- Si falla temporalmente la escritura de un mensaje válido, el consumidor registra el error y no confirma el offset; Kafka permite que el mensaje se vuelva a procesar. Este fallo no se representa como error de respuesta API porque no existe un canal de estado entre el consumidor y la API en esta entrega.
- Si el consumidor rechaza un mensaje inválido o no soportado, debe persistir en cuarentena el motivo y una referencia al payload original antes de confirmar el offset. Si la escritura de cuarentena falla, no confirma el offset.
- La API devuelve un error explícito cuando falla su propia consulta o una dependencia que comprueba directamente. No informa de un fallo del consumidor sin un mecanismo de estado definido por el contrato.
- Los errores HTTP o de consulta no pueden representarse como una respuesta correcta ni como un `FeatureCollection` vacío.
- La ausencia de datos solo debe representarse como `features: []` cuando la operación fue exitosa y la base realmente no tiene resultados.

## Alcance de la primera entrega

El contrato de esta fase se limita a la demostración vertical del evento sintético y no incluye filtros avanzados, estadísticas históricas ni publicación en Netlify.
