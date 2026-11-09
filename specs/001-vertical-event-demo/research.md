# Investigación para la primera entrega vertical

## Decisión 1: alcance del evento de prueba

**Decisión**: La demostración vertical usará un evento sintético con un identificador explícito, por ejemplo `demo-evt-001`, y una marca que lo diferencie claramente de una ingestión live real.

**Rationale**: El enunciado y la FAQ exigen que la primera entrega demuestre el recorrido completo del sistema sin depender todavía de USGS ni de la ingesta histórica. El evento debe poder seguir el flujo completo sin ambigüedad y sin mezclarlo con datos reales.

**Alternativas consideradas**:
- Usar un evento real de USGS en la fase 1: se descarta porque introduce dependencia externa y complica la validación controlada de la arquitectura.
- Usar un evento real pero recortado a un archivo local: se descarta porque la fase 1 debe ser reproducible y claramente separada del sistema completo.

## Decisión 2: modelo de idempotencia

**Decisión**: El consumidor debe deduplicar por `event_id` y por `updated`/versión de origen; la versión actual solo se actualiza si la nueva versión es más reciente, y la confirmación del offset de Kafka debe producirse después de guardar el cambio en PostgreSQL.

**Rationale**: La FAQ define explícitamente este comportamiento y lo exige como criterio esencial del consumidor idempotente. El control de versiones debe ser durable y debe impedir resultados duplicados al reconsumir mensajes.

**Alternativas consideradas**:
- Actualizar siempre el estado con el último mensaje recibido: se descarta porque rompe el criterio de “versión más reciente” y puede revertir el dato con mensajes antiguos.
- Confirmar offset antes de persistir: se descarta porque puede producir pérdida de mensajes o duplicación tras reinicios.

## Decisión 3: separación de errores de persistencia y consulta

**Decisión**: Un fallo transitorio de escritura del consumidor se registra y deja el offset de Kafka sin confirmar para permitir el reintento; no se comunica a través de la API porque esta entrega no define un canal de estado consumidor→API. Un mensaje inválido o no soportado se conserva en cuarentena durable con su motivo y referencia al original antes de confirmar el offset. La API solo devuelve error explícito cuando falla su propia consulta o una dependencia que observa directamente; una respuesta vacía solo es válida tras una consulta exitosa sin resultados.

**Rationale**: La API no puede comunicar estados que no recibe. Mantener el offset sin confirmar evita perder mensajes ante errores transitorios; poner en cuarentena un mensaje rechazado evita descartarlo silenciosamente. La semántica HTTP queda limitada a estados que la API puede observar.

**Alternativas consideradas**:
- Devolver `features: []` cuando falla la escritura o la consulta: se descarta porque confunde “sin datos” con un error.
- Hacer que la API afirme un fallo del consumidor sin un canal definido: se descarta porque atribuye a la API conocimiento que no tiene.
- Confirmar el offset ante un fallo transitorio de escritura: se descarta porque puede perder el mensaje.

## Decisión 4: enfoque de servicio requerido

**Decisión**: Se planifica una composición mínima de cinco servicios separados: productor Python, Kafka, consumidor Python, PostgreSQL y API FastAPI.

**Rationale**: La constitución y el enunciado exigen esta arquitectura obligatoria. El plan no incluye Spark, Flink ni Kubernetes porque no forman parte del alcance mínimo.

**Alternativas consideradas**:
- Reducir la pila a un único proceso Python con base de datos: se descarta porque contradice la arquitectura exigida.
- Añadir más servicios o motores de análisis: se descarta porque no es necesario para la entrega vertical.

## Decisión 5: definición del criterio SC-001

**Decisión**: SC-001 es binario: desde la raíz `observatorio-sismico/`, los cinco servicios están disponibles y el evento sintético aparece exactamente una vez mediante la API. No se fija un límite de tiempo no especificado.

**Rationale**: La especificación no define un tiempo objetivo; el criterio verifica directamente el arranque requerido y el resultado observable sin inventar una métrica.

**Alternativas consideradas**:
- Fijar “menos de 5 minutos” de forma arbitraria: se descarta porque es un valor inventado.
- Mantener “ciclo de demostración razonable”: se descarta porque no es medible.

## Decisión 6: semántica temporal y unidades

**Decisión**: El mensaje y el estado conservan por separado hora de ocurrencia, actualización de fuente, ingesta y reproducción, con tiempos en UTC y unidades documentadas. La forma API usa milisegundos desde la época Unix para `generated`, `last_ingestion`, `time` y `updated`; `replayed_at` es nulo en la demo, que no implementa replay.

**Rationale**: Esta separación evita confundir la antigüedad del evento con cuándo se actualizó o recibió, y mantiene el requisito constitucional sin incluir una función futura de reproducción.

## Hallazgos clave de la investigación

- La primera entrega no debe incluir ingesta live ni histórico.
- El consumidor debe ser idempotente y guardar la última versión válida.
- El contrato de API debe devolver `FeatureCollection` válido para eventos, y `features: []` solo es válido para consultas correctas con ausencia real de datos.
- El consumidor no confirma offsets antes de la escritura durable; los registros rechazados se conservan en cuarentena antes de confirmar y los fallos transitorios quedan disponibles para reintento.
- La API solo comunica errores de consulta o dependencias que puede observar directamente; esta entrega no define un canal de estado del consumidor a la API.
- El origen de la prueba se debe distinguir de la ingestión real y la reproducción del sistema.
- La verificación del hito debe hacerse con un conjunto de pasos manuales de validación, no con números inventados.
