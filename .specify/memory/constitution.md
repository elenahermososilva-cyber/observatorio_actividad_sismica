<!--
Informe de impacto de sincronización
- Cambio de versión: 1.0.0 -> 1.0.0
- Principios modificados: I. Límites de arquitectura y servicios, II. Semántica de datos, III. Idempotencia del consumidor y cuarentena, IV. Atribución geoespacial, V. Corrección del contrato API/frontend y manejo de secretos
- Secciones añadidas: ninguna; esta revisión refuerza políticas existentes con requisitos específicos del proyecto
- Secciones eliminadas: ninguna
- Elementos diferidos: TODO(RATIFICATION_DATE): la fecha original de adopción no está registrada en este repositorio; confirmar antes de la ratificación formal.
-->

# Constitución del observatorio de actividad sísmica

## Principios básicos

### I. Arquitectura y límites de servicio obligatorios
El proyecto DEBE implementar el pipeline de datos requerido como cinco servicios separados de Docker Compose: productor en Python, Kafka, consumidor en Python, PostgreSQL y API FastAPI. Cada servicio DEBE estar aislado por responsabilidad y por configuración de ejecución, y el sistema NO DEBE depender de Spark, Flink, Kubernetes ni otros marcos de procesamiento distribuido para cumplir los requisitos del proyecto. Angular DEBE seguir siendo una SPA que presenta resultados procesados desde la API y NO DEBE asumir el papel del pipeline de datos ni la fuente de verdad. La aplicación DEBE poder desplegarse ejecutando `docker compose up --build -d` para los servicios backend requeridos, mientras que Angular sigue siendo un frontend publicado por separado como SPA.

### II. Procedencia, semántica temporal y unidades explícitas
Todos los registros sísmicos DEBEN preservar la distinción entre la ocurrencia del evento, la hora de actualización de la fuente, la hora de ingestión y la hora de reproducción. Las marcas temporales DEBEN representarse en UTC y convertirse explícitamente; los valores de la fuente en milisegundos desde la época Unix DEBEN transformarse documentando sus unidades, y el pipeline NO DEBE confundir la hora de ocurrencia con la hora de actualización ni con la hora en que se recibió el mensaje. La magnitud, la profundidad y los valores de coordenadas DEBEN mantenerse en sus unidades explícitas de origen y DEBEN documentarse y validarse antes del análisis. Un registro no se considera válido solo porque haya sido recibido; solo lo es si se comprenden y conservan su semántica temporal, sus dominios de valores y sus metadatos de origen.

### III. Idempotencia del consumidor, seguimiento duradero de versiones y cuarentena
El consumidor DEBE ser idempotente: la entrega repetida del mismo mensaje NO DEBE crear registros duplicados del estado actual, y el pipeline DEBE conservar solo la versión más reciente aceptada para el estado actual de cada evento. El consumidor DEBE comparar el identificador observado del evento y la versión de actualización de la fuente antes de escribir; si la versión recibida es anterior a la actual, DEBE ignorarse; si es más reciente, DEBE reemplazar el registro actual. Los offsets de Kafka DEBEN confirmarse solo después de que la escritura correspondiente en PostgreSQL y la actualización del estado de versión se hayan comprometido de forma duradera. Los registros rechazados DEBEN conservarse en un almacén de cuarentena duradero con el motivo del rechazo y una referencia o puntero a la carga original para que el fallo pueda auditarse y reproducirse sin pérdida.

### IV. Integridad de la atribución geoespacial
La asignación de país DEBE derivarse mediante análisis de punto dentro de polígono sobre el catálogo Natural Earth, usando coordenadas geográficas en un sistema compatible y sin utilizar el campo libre `place` ni heurísticas de proximidad como fuente de verdad. El proyecto DEBE mantener un estado diferenciado para los eventos sin país válido y DEBE registrar esa condición explícitamente en lugar de inventar una aproximación por país más cercano. El pipeline DEBE documentar cómo se manejan los casos límite, los polígonos múltiples, los puntos sobre fronteras y la ausencia de cobertura para que la regla de atribución sea reproducible y auditable.

### V. Corrección de la API, confianza del frontend y disciplina de secretos
El frontend DEBE consultar la API del proyecto para obtener los datos procesados y NO DEBE tratar errores HTTP, respuestas parciales, cargas truncadas ni páginas HTML de aviso como si fueran resultados válidos. La aplicación DEBE distinguir entre una respuesta correcta, un servicio no disponible, un conjunto de datos obsoleto y una solicitud fallida, y la interfaz NO DEBE presentar un error o una respuesta parcial como si fuera una respuesta completa y válida. Los secretos NUNCA DEBEN almacenarse en el código, confirmarse en Git, integrarse en el frontend ni colocarse en archivos de configuración públicos. Las credenciales para acceso externo, como túneles, DEBEN mantenerse fuera del repositorio y fuera de los activos visibles para el navegador.

## Restricciones adicionales
El proyecto DEBE documentar y probar los contratos entre servicios, incluyendo idempotencia, comportamiento tras reinicios, reproducción, manejo de errores y supuestos de despliegue. El pipeline DEBE conservar la carga original cruda junto con el estado derivado y los metadatos de cuarentena, y DEBE rechazar tipos de evento malformados o no soportados sin descartarlos silenciosamente. El consumidor DEBE aplicar el filtro de terremotos y conservar el motivo de rechazo para los registros excluidos. El proyecto DEBE declarar los límites del alcance mínimo, incluyendo el hecho de que que un dato desaparezca de las últimas 24 horas no implica necesariamente que el evento haya sido eliminado por la fuente. La comparación histórica DEBE usar filtros equivalentes y ventanas temporales consistentes, y el proyecto DEBE registrar la fuente de datos, el periodo, el alcance y el denominador utilizados para cualquier métrica o conclusión.

## Flujo de trabajo de desarrollo
La implementación y la revisión DEBEN preservar los principios de gobierno del proyecto y no optimizar solo por rapidez. Los contratos de servicio, las reglas de validación de datos, los supuestos de almacenamiento y los límites de despliegue DEBEN documentarse antes o durante la implementación, y la revisión DEBE verificar que siguen siendo coherentes con el sistema de origen, la arquitectura del proyecto y la evidencia de calidad del conjunto de datos. El proyecto DEBE mantener un registro claro de decisiones de diseño, supuestos y resultados de validación para que las reproducciones, la recuperación tras reinicios y la revisión de calidad sigan siendo trazables tras cambios en la base de código o en el entorno de ejecución.

## Gobierno
Esta Constitución rige el diseño, la implementación, la revisión y la entrega del proyecto observatorio de actividad sísmica. Cualquier modificación de contratos de datos, límites de servicio, supuestos de despliegue o reglas de calidad DEBE preservar los requisitos del proyecto en reproducibilidad, trazabilidad, seguridad y corrección. El proyecto NO DEBE debilitar las reglas de idempotencia, cuarentena, atribución geográfica ni integridad de la API para cumplir un objetivo de entrega a corto plazo.

**Versión**: 1.0.0 | **Ratificada**: TODO(RATIFICATION_DATE): la fecha original de adopción no está registrada en este repositorio; confirmar antes de la ratificación formal. | **Última modificación**: 2026-11-08
