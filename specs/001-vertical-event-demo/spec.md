# Especificación de la funcionalidad: Primera entrega vertical del observatorio de actividad sísmica

**Rama de la funcionalidad**: `[001-vertical-event-demo]`

**Creado**: 2026-11-08

**Estado**: Borrador

**Entrada**: Descripción del usuario: "Define la especificación de la primera entrega vertical del proyecto “Observatorio de actividad sísmica”. Basa los requisitos en: - @ENUNCIADO.md - @FAQ-ALUMNADO.md - @CONTRATO-API.md - @README.md La entrega debe permitir demostrar el recorrido de un evento de prueba sintético, claramente identificado como tal: se publica en el sistema, el consumidor lo procesa y persiste, y un cliente puede consultarlo mediante la API con la forma GeoJSON definida en el contrato. Debe servir como primer hito verificable de la arquitectura obligatoria del proyecto, sin pretender completar todavía el sistema. Respeta la constitución del proyecto. Considera como restricciones obligatorias que el resultado final requiere cinco servicios separados en Docker Compose: productor Python, Kafka, consumidor Python, PostgreSQL y API FastAPI. No añadas Spark, Flink, Kubernetes ni aprendizaje automático como requisitos. Limita esta especificación a la primera entrega de prueba. Deja para especificaciones posteriores la ingesta live automática de USGS, la carga histórica completa, el enriquecimiento geográfico, las estadísticas y filtros completos, el replay, la publicación en Netlify y la memoria final. No conviertas esos elementos futuros en requisitos de esta primera entrega. Escribe historias de usuario, escenarios de aceptación verificables, requisitos funcionales comprobables, casos límite, supuestos y criterios de éxito medibles. Incluye como mínimo comprobar que el evento consultado aparece una sola vez, que el consumidor puede procesar de nuevo el mismo evento sin duplicar el resultado, y que los errores de persistencia o de consulta no se presentan como una respuesta vacía válida. No inventes requisitos contradictorios con los documentos. Si algo importante no está especificado y no hay un supuesto razonable, marca como máximo tres puntos de aclaración. Genera la especificación y su checklist de calidad; no implementes código, no generes el plan ni las tareas todavía."

## Escenarios de usuario y pruebas *(obligatorio)*

<!--
  IMPORTANTE: Las historias de usuario deben priorizarse como viajes del usuario ordenados por importancia.
  Cada historia o recorrido debe poder probarse de forma INDEPENDIENTE, es decir, si se implementa solo una de ellas,
  aún debería existir un MVP (Producto mínimo viable) útil y demostrable.

  Asigna prioridades (P1, P2, P3, etc.) a cada historia, donde P1 es la más crítica.
  Piensa en cada historia como una porción independiente de funcionalidad que puede ser:
  - desarrollada de forma independiente
  - probada de forma independiente
  - desplegada de forma independiente
  - demostrada a los usuarios de forma independiente
-->

### Historia de usuario 1 - Verificación vertical de un evento sintético (Prioridad: P1)

Un responsable del proyecto o un evaluador desea comprobar que la arquitectura obligatoria funciona como una cadena completa: un evento sintético se publica, el consumidor lo procesa y persiste, y un cliente puede consultarlo mediante la API con el formato GeoJSON esperado.

**Por qué esta prioridad**: Esta entrega es el primer hito verificable del sistema y demuestra que el flujo completo funciona sin pretender cerrar la funcionalidad completa del observatorio.

**Prueba independiente**: Puede validarse ejecutando la pila mínima desde la raíz del proyecto `observatorio-sismico/` con un evento de prueba sintético, comprobando la persistencia y la consulta por API.

**Escenarios de aceptación**:

1. **Dado** que el sistema está levantado con los cinco servicios obligatorios, **cuando** se publica un evento sintético identificado explícitamente como prueba, **entonces** el consumidor lo procesa y lo persiste como una única versión actual del evento.
2. **Dado** que el evento ya está persistido, **cuando** un cliente consulta la API en el endpoint de eventos, **entonces** recibe un GeoJSON `FeatureCollection` con ese evento exactamente una vez y sin duplicados.
3. **Dado** que el consumidor vuelve a procesar el mismo evento sintético, **cuando** se reinicia el flujo de ingestión o se reconsume el mensaje, **entonces** no genera una segunda versión activa ni duplica el resultado visible en la API.

---

### Historia de usuario 2 - Manejo explícito de fallos y registros rechazados (Prioridad: P1)

Un evaluador quiere comprobar por separado que un fallo transitorio de persistencia no hace perder el mensaje, que los registros inválidos se conservan en cuarentena y que un fallo de consulta de la API no se interpreta como “sin eventos”.

**Por qué esta prioridad**: El sistema debe distinguir entre “sin resultados” y “fallo del servicio”; esto es crítico para la fiabilidad técnica y para cumplir la necesidad de trazabilidad del proyecto.

**Prueba independiente**: Se puede probar por separado un fallo transitorio de escritura del consumidor, el rechazo durable de un registro inválido y un fallo de consulta de la API. El consumidor registra el fallo de escritura y no confirma el offset; la API devuelve un error explícito únicamente cuando falla su propia consulta.

**Escenarios de aceptación**:

1. **Dado** que falla temporalmente una escritura del consumidor en PostgreSQL, **cuando** el consumidor intenta persistir un mensaje válido, **entonces** registra el error, no confirma el offset y deja que Kafka permita reintentar el mensaje; no intenta presentar ese fallo como una respuesta de la API.
2. **Dado** que el consumidor rechaza un mensaje por inválido o no soportado, **cuando** registra el rechazo, **entonces** conserva duraderamente el motivo y una referencia al payload original antes de confirmar el offset; si falla la escritura de cuarentena, no confirma el offset.
3. **Dado** que la consulta propia de la API no puede devolver datos válidos, **cuando** el cliente solicita `/api/eventos`, **entonces** la respuesta comunica el error explícitamente y no devuelve un resultado vacío que se presente como válido.

---

### Historia de usuario 3 - Validación del arranque mínimo de la pila (Prioridad: P2)

Un desarrollador o evaluador debe poder levantar la arquitectura mínima para comprobar que los contenedores del sistema quedan conectados y que el flujo se puede ejecutar en conjunto sin añadir infraestructura extra fuera del alcance requerido.

**Por qué esta prioridad**: La primera entrega debe servir como hito de arquitectura y como prueba de integración mínima del sistema, pero sin asumir los requisitos del sistema completo.

**Prueba independiente**: Se puede validar con `docker compose up --build -d` desde la raíz `observatorio-sismico/` y comprobando la disponibilidad de los servicios obligatorios.

**Escenarios de aceptación**:

1. **Dado** un entorno local con Docker disponible, **cuando** se ejecuta la composición de servicios, **entonces** quedan levantados los cinco servicios obligatorios: productor, Kafka, consumidor, PostgreSQL y API.
2. **Dado** la pila levantada, **cuando** se publica un evento sintético de prueba, **entonces** el resultado puede observarse desde la API y la cadena completa queda verificada.

---

### Edge Cases

- ¿Qué ocurre si el mismo evento sintético se procesa dos veces con la misma versión?
- ¿Qué ocurre si un evento sintético llega al consumidor antes de que PostgreSQL esté listo o si la persistencia falla temporalmente?
- ¿Qué ocurre si la consulta a la API no devuelve contenido válido o devuelve una estructura parcialmente corrupta?
- ¿Qué ocurre si el evento se publica con un identificador de prueba no estándar pero claramente marcado como sintético?
- ¿Qué ocurre si una respuesta vacía se interpreta por error como éxito del sistema?

## Requisitos *(obligatorios)*

### Requisitos funcionales

- **FR-001**: El sistema MUST desplegar la arquitectura mínima requerida como cinco servicios separados en Docker Compose: productor Python, Kafka, consumidor Python, PostgreSQL y API FastAPI.
- **FR-002**: El sistema MUST permitir publicar un evento sintético claramente identificado como prueba dentro del flujo principal del sistema.
- **FR-003**: El consumidor MUST procesar el evento recibido y persistir el estado actual sin duplicar la representación visible del evento.
- **FR-004**: La API MUST exponerse en el endpoint definido por el contrato como un GeoJSON `FeatureCollection` válido para los eventos consultados.
- **FR-005**: La API MUST devolver exactamente una instancia visible del evento consultado, no dos o más entradas para el mismo evento activo.
- **FR-006**: El consumidor MUST soportar la relectura del mismo evento sintético sin duplicar el resultado final ni crear registros activos adicionales.
- **FR-007**: La API MUST devolver `features: []` solo cuando la consulta se complete correctamente y no existan resultados; MUST responder con un error explícito cuando falle su propia consulta y MUST NOT afirmar que conoce un fallo del consumidor sin un mecanismo de estado definido.
- **FR-008**: Ante un fallo transitorio al persistir un mensaje válido, el consumidor MUST registrar el error y no confirmar el offset de Kafka para permitir el reintento. Para un mensaje rechazado por inválido o no soportado, MUST persistir duraderamente en cuarentena el motivo y una referencia al payload original antes de confirmar su offset; si esa escritura falla, MUST dejar el offset sin confirmar.
- **FR-009**: El sistema MUST mantener el evento sintético como prueba en un flujo de prueba controlado y no asumir todavía la ingesta live automática de USGS ni la carga histórica completa.
- **FR-010**: La primera entrega MUST estar limitada a la demostración vertical de un evento sintético y no introducir como requisitos la ingestión en directo, la comparación histórica, el replay completo, la publicación en Netlify ni la memoria final.
- **FR-011**: El proyecto MUST respetar la constitución del repositorio y no incorporar requisitos de Spark, Flink, Kubernetes ni aprendizaje automático para esta primera entrega.
- **FR-012**: La primera entrega MUST documentar de forma mínima la forma del evento de prueba y el camino de verificación en la arquitectura, sin extenderse a la entrega completa del observatorio.
- **FR-013**: El mensaje y el estado del evento MUST distinguir la hora de ocurrencia, la actualización de la fuente, la ingesta y la reproducción. Las marcas temporales MUST usar UTC y documentar sus unidades; en esta entrega se usan milisegundos desde la época Unix para los tiempos representados así en la fuente. `replayed_at` MUST ser nulo cuando el evento no provenga de una reproducción; no se implementa una función de replay en esta entrega.

### Entidades clave *(incluir si la funcionalidad implica datos)*

- **Evento sintético**: Representa un terremoto de prueba claramente identificado como tal, con metadatos mínimos que permiten distinguirlo del contenido real del sistema y verificar su seguimiento a través de productor, consumidor y API.
- **Mensaje publicado**: Objeto emitido por el productor para el servicio de mensajería, con información del evento y su identidad de prueba.
- **Versión actual del evento**: Estado persistido del evento tras el procesamiento del consumidor, que representa la versión válida más reciente del mismo evento.
- **Respuesta API**: Resultado GeoJSON del endpoint de eventos para una consulta válida, con exactamente los eventos activos esperados y sin duplicados visibles.
- **Error de servicio**: Estado que representa una consulta fallida o un servicio degradado observado por la API, que no se debe presentar como un resultado vacío válido.

## Criterios de éxito *(obligatorios)*

### Resultados medibles

- **SC-001**: Un evaluador puede ejecutar la pila mínima desde la raíz `observatorio-sismico/`, confirmar que los cinco servicios obligatorios están disponibles y verificar que el evento sintético consultado aparece exactamente una vez en la API.
- **SC-002**: Un evento sintético puede seguir el flujo completo desde publicación hasta consulta por API y ser visible como exactamente una única entidad estándar del sistema.
- **SC-003**: El mismo evento sintético puede procesarse de nuevo sin duplicar el resultado activo en la base ni en la respuesta API.
- **SC-004**: Ante un fallo transitorio de escritura, el consumidor registra el error y no confirma el offset; ante un mensaje rechazado, persiste en cuarentena el motivo y una referencia al original antes de confirmarlo; ante un fallo de consulta de la API, esta comunica el error sin devolver un `FeatureCollection` vacío válido.
- **SC-005**: La entrega demuestra de forma verificable que el sistema cumple el primer hito vertical requerido por la arquitectura del proyecto, sin extenderse a requisitos de ingestión live o análisis completos.

## Suposiciones

- La entrega de prueba usa un evento sintético controlado y no requiere consumir la fuente live de USGS.
- La validación del primer hito se realiza con un solo evento de prueba y no requiere completar la carga histórica ni la comparación con periodos previos.
- La infraestructura mínima se entiende como la composición de cinco servicios que corresponden a la arquitectura obligatoria del proyecto.
- La API de consulta se comporta según el contrato definido en `CONTRATO-API.md` y no se exige aún la implementación completa de filtros avanzados ni estadísticas de negocio.
- Se asume que una consulta API exitosa sin resultados puede devolver `features: []`; los fallos de consulta API se devuelven como error. Los fallos de persistencia del consumidor se registran y dejan el offset sin confirmar, pero no se comunican mediante la API en esta entrega.
- Esta primera entrega no incluye análisis geográfico, replay completo, publicación en Netlify ni memoria final; esos elementos quedan para una especificación posterior.
- Si algo importante no está especificado, se utilizarán suposiciones razonables y se limitarán los puntos de aclaración a un máximo de tres, priorizando la frontera de alcance de la entrega.
