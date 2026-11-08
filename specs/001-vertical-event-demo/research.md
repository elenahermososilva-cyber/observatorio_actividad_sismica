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

**Decisión**: La API no debe convertir un error de persistencia del consumidor en una respuesta vacía válida. La respuesta de la API debe diferenciar entre “sin eventos” y “fallo del servicio” y debe definir el mecanismo de error explícito del backend.

**Rationale**: El contrato de la API y la especificación exigen que una respuesta vacía no se presente como éxito cuando hay un fallo de consulta o persistencia. Debe existir una forma explícita de comunicar la falla.

**Alternativas consideradas**:
- Devolver `features: []` siempre cuando el consumidor falla: se descarta porque se confunde “sin datos” con “error”.
- Devolver un 500 sin payload útil: se descarta como mecanismo insuficiente si el contrato requiere una respuesta definida.

## Decisión 4: enfoque de servicio requerido

**Decisión**: Se planifica una composición mínima de cinco servicios separados: productor Python, Kafka, consumidor Python, PostgreSQL y API FastAPI.

**Rationale**: La constitución y el enunciado exigen esta arquitectura obligatoria. El plan no incluye Spark, Flink ni Kubernetes porque no forman parte del alcance mínimo.

**Alternativas consideradas**:
- Reducir la pila a un único proceso Python con base de datos: se descarta porque contradice la arquitectura exigida.
- Añadir más servicios o motores de análisis: se descarta porque no es necesario para la entrega vertical.

## Decisión 5: definición del criterio SC-001

**Decisión**: El criterio SC-001 queda identificado como un punto de decisión de alcance para el usuario, no como una métrica inventada. La validación del hito debe definirse en una sesión de demostración con paso a paso, pero sin fijar un valor numérico arbitrario.

**Rationale**: La especificación no define un tiempo objetivo ni un número de pasos medibles. En esta fase de diseño, ese criterio debe mantenerse como una condición de prueba de aceptación, no como un hecho cuantificado sin acuerdo.

**Alternativas consideradas**:
- Fijar “menos de 5 minutos” de forma arbitraria: se descarta porque es un valor inventado.
- Ignorar el criterio: se descarta porque la especificación lo incluye y debe quedar visible para revisarse.

## Hallazgos clave de la investigación

- La primera entrega no debe incluir ingesta live ni histórico.
- El consumidor debe ser idempotente y guardar la última versión válida.
- El contrato de API debe devolver `FeatureCollection` válido para eventos, y `features: []` solo es válido para consultas correctas con ausencia real de datos.
- El origen de la prueba se debe distinguir de la ingestión real y la reproducción del sistema.
- La verificación del hito debe hacerse con un conjunto de pasos manuales de validación, no con números inventados.
