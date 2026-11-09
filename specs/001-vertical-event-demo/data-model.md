# Modelo de datos para la primera entrega vertical

## Entidad 1: `event_message`

Representa el mensaje publicado por el productor. Es el contenido que llega por Kafka y se marca como prueba.

**Campos clave**
- `event_id`: identificador único del evento de prueba o del evento real; debe ser estable.
- `source`: origen del dato, por ejemplo `synthetic-demo` o `usgs`.
- `mode`: modo de ingestión, en esta entrega `test` o `demo`.
- `time`: hora de ocurrencia del evento, en UTC y milisegundos enteros desde la época Unix.
- `updated`: hora/versión de actualización indicada por la fuente, distinta de la ocurrencia y en milisegundos enteros desde la época Unix.
- `ingested_at`: hora en que el sistema recibió el mensaje, como fecha-hora UTC con zona horaria.
- `replayed_at`: hora de reproducción como fecha-hora UTC con zona horaria cuando el mensaje procede de una reproducción; es nula para la prueba normal de esta entrega. No implica implementar replay.
- `payload`: estructura original del evento serializada o en JSON.
- `synthetic_flag`: indicador booleano para distinguir la prueba sintética del flujo real.

**Reglas de validación**
- Un `event_id` debe ser único por evento físico.
- La versión debe compararse con el estado actual antes de guardar.
- Un mismo `event_id` con una versión repetida debe ignorarse como duplicado.
- Si se recibe un valor `updated` anterior al ya persistido, no debe reemplazar el estado actual.
- Los tiempos `time`, `updated`, `ingested_at` y `replayed_at` no se deben intercambiar; los tiempos disponibles se conservan en UTC con sus unidades documentadas.
- Si falla temporalmente la escritura de un mensaje válido, se registra el error y no se confirma su offset; Kafka conserva la posibilidad de reintento.
- Si el mensaje se rechaza por inválido o no soportado, el motivo y la referencia al payload original se guardan duraderamente en cuarentena antes de confirmar el offset. Si falla la escritura de cuarentena, no se confirma el offset.

**Representación de la primera entrega**: `event_message` conserva el sobre original serializado como JSON y usa la clave `(event_id, source_updated_ms)` para reconocer versiones repetidas. `event_current` mantiene una sola fila por `event_id`; su versión solo cambia cuando `source_updated_ms` es mayor. `time` y `updated` se guardan como milisegundos Unix UTC, mientras que `ingested_at` y `replayed_at` son `TIMESTAMPTZ` UTC. `quarantine_record` contiene el motivo, una referencia Kafka (tema, partición y offset) y el mensaje original para permitir auditoría.

## Entidad 2: `event_current`

Representa la versión actual y válida del evento en PostgreSQL.

**Campos clave**
- `event_id`: clave principal del evento actual.
- `current_version`: versión más reciente aceptada, en milisegundos Unix UTC.
- `status`: estado de la versión actual aceptada.
- `last_seen_at`: última vez que se procesó una versión aceptada.
- `payload`: contenido del evento en estado útil y validado.
- `source`: fuente de origen para trazabilidad.
- `event_time`: hora de ocurrencia del evento.
- `source_updated_at`: hora/versión de actualización de la fuente, en milisegundos Unix UTC.
- `ingested_at`: hora de ingesta.
- `replayed_at`: hora de reproducción, nula cuando no aplique.

**Reglas de validación**
- Debe existir una sola fila activa por `event_id`.
- La actualización solo cambia el valor si la nueva versión es más reciente.
- Si no hay un dato válido, el evento no debe aparecer como resultado activo.
- Las cuatro marcas temporales conservan semánticas distintas y se guardan en UTC con unidades explícitas.

## Entidad 3: `quarantine_record`

Representa un registro rechazado o no válido para auditoría y posible reanálisis. No se usa como sustituto de un reintento cuando falla temporalmente una escritura normal en PostgreSQL.

**Campos clave**
- `quarantine_id`: identificador del registro rechazado.
- `event_id`: identificador si existe, o un valor nulo si no se puede reconstruir.
- `reason`: motivo explícito del rechazo.
- `original_payload`: contenido completo del mensaje original.
- `created_at`: instante en que se registró la cuarentena.
- `source`: origen del mensaje rechazado.

**Reglas de validación**
- El motivo del rechazo debe conservarse de forma permanente.
- Debe existir una referencia o puntero al payload original para reanálisis.
- El sistema no debe descartar el dato sin dejar constancia.

## Entidad 4: `api_event_response`

Es una representación contractualmente válida de la respuesta de la API. No es un almacenamiento de negocio, sino la forma visible de los eventos consultados.

**Campos clave**
- `type`: `FeatureCollection`.
- `metadata.generated`: momento de generación de la respuesta.
- `metadata.last_ingestion`: última ingestión correcta relevante al sistema.
- `metadata.mode`: `demo` o `live`.
- `metadata.count`: número de eventos visibles.
- `metadata.truncated`: indica si la respuesta se ha recortado.
- `features`: array de `Feature` con coordenadas y propiedades del evento.

**Reglas de validación**
- No se aceptan `NaN`, `Infinity` ni valores no definidos para coordenadas o magnitudes.
- Si se devuelve `features: []`, debe ser porque la consulta fue exitosa y no hubo resultados.
- Si falla la consulta de la API, la respuesta no debe presentarse como una colección vacía válida. Un fallo de escritura del consumidor se registra en el consumidor y no se infiere desde la API sin un mecanismo explícito de estado.

## Relaciones clave

- `event_message` puede producir `event_current` si se acepta y se valida.
- `event_message` puede producir `quarantine_record` si se rechaza.
- `event_current` alimenta la representación final que se expone en la API.
- La API no debe inventar datos ni inferir un estado válido si la capa de persistencia ha fallado.

## Restricciones de diseño

- La primera entrega no requiere histórico ni enriquecimiento geográfico.
- El mismo evento puede llegar dos veces con la misma versión y no debe duplicarse.
- La respuesta API debe encajar con `FeatureCollection` del contrato con una sola instancia visible del evento activo.
- La verificación debe conservar la distinción entre “sin resultados” y “fallo del sistema”.
