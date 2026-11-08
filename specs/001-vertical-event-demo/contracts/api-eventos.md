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

## Alcance de la primera entrega

El contrato de esta fase se limita a la demostración vertical del evento sintético y no incluye filtros avanzados, estadísticas históricas ni publicación en Netlify.
