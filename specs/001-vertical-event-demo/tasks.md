# Tasks: Primera entrega vertical del observatorio de actividad sísmica

**Input**: `/specs/001-vertical-event-demo/spec.md`, `/specs/001-vertical-event-demo/plan.md`, `/specs/001-vertical-event-demo/research.md`, `/specs/001-vertical-event-demo/data-model.md`, `/specs/001-vertical-event-demo/contracts/api-eventos.md`, `/specs/001-vertical-event-demo/quickstart.md`, `.specify/memory/constitution.md`

**Organización**: tareas agrupadas por historia de usuario para permitir implementación y verificación independientes; el alcance queda limitado a la entrega vertical de prueba del evento sintético.

**Convención de rutas**: `observatorio-sismico/` es la raíz del proyecto que contiene `compose.yaml`, `backend/` y `tests/`; las rutas de archivos de código y pruebas en las tareas se escriben desde la raíz del repositorio, incluyendo el prefijo `observatorio-sismico/` cuando corresponda.

## Fase 1: Setup (infraestructura compartida)

**Propósito**: preparar la estructura del repositorio y la composición mínima del sistema para la entrega vertical.

- [X] T001 Crear la estructura base del proyecto en `observatorio-sismico/compose.yaml`, `observatorio-sismico/backend/producer/`, `observatorio-sismico/backend/consumer/`, `observatorio-sismico/backend/api/`, `observatorio-sismico/backend/db/`, `observatorio-sismico/tests/contract/`, `observatorio-sismico/tests/integration/` y `observatorio-sismico/tests/smoke/` para la entrega vertical sin añadir servicios no solicitados.
- [X] T002 Definir en `observatorio-sismico/compose.yaml` exactamente cinco servicios: productor Python, Kafka, consumidor Python, PostgreSQL y API FastAPI, sin Spark, Flink, Kubernetes ni ML.
- [X] T003 [P] Preparar plantillas de variables en `observatorio-sismico/backend/producer/.env.example`, `observatorio-sismico/backend/consumer/.env.example`, `observatorio-sismico/backend/api/.env.example` y `observatorio-sismico/backend/db/.env.example`, sin editar `compose.yaml` ni almacenar secretos reales en Git o en el frontend.

---

## Fase 2: Fundacionales (prerrequisitos bloqueantes)

**Propósito**: dejar la base de datos, los contratos y la semántica de datos lista antes de cualquier historia funcional.

**⚠️ CRÍTICO**: ninguna historia puede empezar hasta completar esta fase.

- [X] T004 Definir el esquema de persistencia en `observatorio-sismico/backend/db/schema.sql` o `observatorio-sismico/backend/db/migrations/` con `event_message`, `event_current` y `quarantine_record`, manteniendo una sola fila activa por `event_id`, las cuatro marcas temporales distintas y una referencia duradera al payload original en cuarentena.
- [X] T005 [P] Definir el contrato del mensaje publicado en `observatorio-sismico/backend/producer/schema.py` con `event_id`, `source`, `mode`, `time`, `updated`, `ingested_at`, `replayed_at`, `payload` y `synthetic_flag`; especificar UTC y unidades para cada tiempo, y que `replayed_at` es nulo en esta entrega.
- [X] T006 Documentar en `specs/001-vertical-event-demo/data-model.md` el contrato de procesamiento del consumidor: comparar `event_id` y versión de fuente; ignorar versiones repetidas o anteriores; ante fallo transitorio de escritura, registrar y no confirmar el offset; para un rechazo, persistir cuarentena antes de confirmar; nunca confirmar antes del commit durable correspondiente.
- [X] T007 Definir en `specs/001-vertical-event-demo/contracts/api-eventos.md` la respuesta `FeatureCollection`, su metadata y los errores observables por la API; `features: []` es válido solo tras una consulta exitosa sin resultados, y la API no reporta fallos internos del consumidor.
- [X] T008 Definir en `specs/001-vertical-event-demo/contracts/api-eventos.md` el alcance de `GET /api/salud`: informa solo del estado observable de la API y de las dependencias que consulta directamente, no del estado de ingesta del consumidor.
- [X] T009 Documentar en `specs/001-vertical-event-demo/quickstart.md` la comprobación de arranque desde `observatorio-sismico/` usando `docker compose ps`, enumerando los cinco servicios y sus estados esperados; esta tarea define el procedimiento y no ejecuta la validación final del flujo.

**Punto de control**: la base de datos, el contrato API y la semántica de idempotencia están listos; puede empezar la implementación de historias.

---

## Fase 3: Historia de usuario 1 - Verificación vertical de un evento sintético (Prioridad: P1) 🎯 MVP

**Objetivo**: publicar un evento sintético, procesarlo con idempotencia, persistirlo y consultarlo por la API exactamente una vez.

**Prueba independiente**: desde la raíz `observatorio-sismico/`, levantar la pila y comprobar que el evento sintético identificado como `demo-evt-001` aparece exactamente una vez en `GET /api/eventos` dentro de un `FeatureCollection` válido.

- [X] T010 [P] [US1] Preparar la prueba de contrato en `observatorio-sismico/tests/contract/test_api_eventos.py` para validar `FeatureCollection`, metadata, unidades temporales y una sola instancia del evento.
- [X] T011 [P] [US1] Preparar la prueba de integración en `observatorio-sismico/tests/integration/test_vertical_demo.py` para publicar el mismo evento sintético dos veces y comprobar que la API lo devuelve exactamente una vez.
- [X] T012 [US1] Implementar en `observatorio-sismico/backend/producer/producer.py` la publicación del evento de prueba con `source="synthetic-demo"`, `mode="demo"`, `synthetic_flag=true`, `event_id` estable y los tiempos definidos en `backend/producer/schema.py`.
- [X] T013 [US1] Implementar en `observatorio-sismico/backend/consumer/consumer.py` la lectura desde Kafka y la normalización del mensaje, preservando por separado ocurrencia, actualización, ingesta y reproducción en UTC con unidades explícitas.
- [X] T014 [US1] Implementar en `observatorio-sismico/backend/db/repository.py` una transacción que conserve el mensaje original y actualice el estado actual solo si la versión es más reciente; retornar solo después del commit durable para que el consumidor pueda confirmar el offset.
- [X] T015 [US1] Implementar en `observatorio-sismico/backend/api/app.py` `GET /api/eventos` como `FeatureCollection` GeoJSON con metadata contractual y exactamente una instancia visible del evento activo.
- [ ] T016 [US1] Ejecutar `observatorio-sismico/tests/integration/test_vertical_demo.py` y comprobar que el evento sintético procesado/reprocesado queda persistido una sola vez y aparece una sola vez en la API.

**Punto de control**: User Story 1 queda funcional y verificable por sí misma con un solo evento sintético.

---

## Fase 4: Historia de usuario 2 - Manejo explícito de fallos y registros rechazados (Prioridad: P1)

**Objetivo**: distinguir una consulta API vacía exitosa de un error de consulta, conservar registros rechazados en cuarentena y reintentar fallos transitorios de escritura sin perder mensajes.

**Prueba independiente**: provocar por separado un fallo temporal de escritura del consumidor, un rechazo que deba guardarse en cuarentena y un fallo de la consulta API; verificar el offset/reintento del consumidor y que solo el fallo de consulta se comunica como error API.

- [ ] T017 [P] [US2] Preparar pruebas de API en `observatorio-sismico/tests/contract/test_api_errors.py`: consulta exitosa sin datos devuelve `200` con `features: []`, y un fallo de consulta devuelve un error HTTP, no una colección vacía.
- [ ] T018 [P] [US2] Preparar las pruebas de fallos del consumidor en `observatorio-sismico/tests/integration/test_consumer_failures.py`: comprobar que tras un fallo transitorio no hay confirmación, que tras el commit durable el mensaje se reintenta/persiste y se confirma, y que la cuarentena durable precede a la confirmación, incluido el fallo al escribirla.
- [ ] T019 [US2] Implementar en `observatorio-sismico/backend/consumer/consumer.py` la secuencia de confirmación: confirmar solo después de que la persistencia normal de T014 o la cuarentena de T020 hayan terminado su commit durable; ante un fallo transitorio, registrar el error y dejar el offset sin confirmar para reintento.
- [ ] T020 [US2] Implementar en `observatorio-sismico/backend/db/quarantine.py` el almacenamiento durable de mensajes inválidos/no soportados con motivo y referencia al payload original; devolver éxito solo después del commit y propagar los fallos para impedir la confirmación del offset.
- [ ] T021 [US2] Implementar en `observatorio-sismico/backend/api/app.py` la respuesta de error explícita para fallos de su propia consulta o dependencias observables, sin presentar el fallo como `FeatureCollection` vacío ni atribuirlo al consumidor.
- [ ] T022 [US2] Ejecutar `observatorio-sismico/tests/contract/test_api_errors.py` y `observatorio-sismico/tests/integration/test_consumer_failures.py` y comprobar por separado consulta vacía válida, error de consulta API, reintento sin confirmar offset y cuarentena durable antes de confirmar.

**Punto de control**: User Story 2 queda funcional y demuestra por separado el reintento del consumidor, la cuarentena durable y el error observable de consulta API.

---

## Fase 5: Historia de usuario 3 - Validación del arranque mínimo de la pila (Prioridad: P2)

**Objetivo**: comprobar que la arquitectura mínima queda levantada y funcionando en un entorno local con Docker Compose y que la prueba vertical queda validada de extremo a extremo.

**Prueba independiente**: ejecutar `docker compose up --build -d` desde la raíz `observatorio-sismico/` y comprobar que los cinco servicios están disponibles y que el evento sintético aparece exactamente una vez vía API.

- [ ] T023 [P] [US3] Preparar la prueba de arranque en `observatorio-sismico/tests/smoke/test_stack_startup.py` para verificar que los cinco servicios definidos en `observatorio-sismico/compose.yaml` estén disponibles.
- [ ] T024 [US3] Ejecutar desde `observatorio-sismico/` la comprobación de arranque descrita en `specs/001-vertical-event-demo/quickstart.md` y confirmar con `docker compose ps` que productor, Kafka, consumidor, PostgreSQL y API están disponibles.
- [ ] T025 [US3] Ejecutar desde `observatorio-sismico/` el quickstart completo de `specs/001-vertical-event-demo/quickstart.md` después de completar US1 y US2, comprobando recorrido, idempotencia, cuarentena y errores con los resultados esperados.
- [ ] T026 [US3] Revisar `specs/001-vertical-event-demo/spec.md` y `specs/001-vertical-event-demo/plan.md` para confirmar que el alcance sigue excluyendo ingesta live, histórico completo, enriquecimiento geográfico, estadísticas y filtros completos, replay completo y Netlify.

**Punto de control**: User Story 3 confirma que la pila mínima queda desplegada y verificada sin ampliar el alcance de la entrega.

---

## Fase 6: Pulido y preocupaciones transversales

**Propósito**: cerrar la calidad del hito y revisar coherencia con la constitución y contratos.

- [ ] T027 [P] Revisar la coherencia de `observatorio-sismico/compose.yaml`, `specs/001-vertical-event-demo/quickstart.md` y `specs/001-vertical-event-demo/contracts/api-eventos.md` para que la ubicación de Compose, el arranque desde `observatorio-sismico/` y los criterios de aceptación coincidan.
- [ ] T028 [P] Revisar que no se introducen requisitos contradictorios con la constitución en `.specify/memory/constitution.md`: cinco servicios obligatorios, idempotencia, cuarentena duradera, país por point-in-polygon, UTC y unidades explícitas, y secretos fuera del repositorio.

---

## Dependencias y orden de ejecución

### Dependencias por fase
- **Fase 1 (Setup)**: T001 no depende de otra tarea; T002 y T003 dependen de T001. T002 y T003 pueden avanzar en paralelo porque editan archivos distintos.
- **Fase 2 (Fundacional)**: depende de T001; T004, T005 y T007 pueden avanzar en paralelo en archivos distintos. T006 depende de T004 y T005; T008 depende de T007; T009 depende de T002, T007 y T008. La fase bloquea las historias.
- **Fase 3 (US1)**: depende de la Fase 2; tareas de contrato/prueba pueden prepararse en paralelo según sus contratos. La ejecución integral T016 espera a las implementaciones T012–T015.
- **Fase 4 (US2)**: depende de la Fase 2 y de las partes de US1 que comparte: T020 depende de T004; T019 espera a T013, T014 y T020; T021 espera a T015.
- **Fase 5 (US3)**: T023 depende de T002; T024 espera a las implementaciones de US1 y US2; T025 espera a T024 y a las validaciones T016 y T022; T026 es una revisión de alcance posterior a las especificaciones e implementaciones.
- **Fase 6 (Pulido)**: depende de la finalización de las historias.

### Dependencias reales dentro de cada historia
- User Story 1: T010 depende de T005 y T007; T011 depende de T005–T007; T012 depende de T005; T013 depende de T005–T006; T014 depende de T004 y T006; T015 depende de T007–T008; T016 depende de T010–T015.
- User Story 2: T017 depende de T007–T008; T018 depende de T006 y T014; T020 depende de T004 y T006; T019 depende de T013–T014 y T020; T021 depende de T015; T022 depende de T017–T021.
- User Story 3: T024 depende de T002 y de las implementaciones T012–T015, T019–T021; T025 depende de T024, T016 y T022; T026 depende de las especificaciones y del alcance implementado.

### Oportunidades de paralelismo
- T002 y T003 pueden ejecutarse en paralelo después de T001: T003 modifica solo las plantillas `.env.example` y T002 solo `compose.yaml`.
- T004, T005 y T007 pueden ejecutarse en paralelo después de T001 porque modifican el esquema de base de datos, el esquema de mensaje y el contrato API, respectivamente.
- T010 y T011 pueden prepararse en paralelo una vez definidos los contratos de sus dependencias; T017 y T018 también pueden prepararse en paralelo. T020 precede a T019 porque este último integra la escritura de cuarentena en el consumidor.
- T023 puede prepararse en paralelo con las implementaciones de historias una vez definido el servicio en T002. T027 y T028 son revisiones independientes de archivos distintos y pueden realizarse en paralelo después de las historias.

### Criterios de MVP recomendados
- El MVP mínimo para esta entrega es la User Story 1: evento sintético publicado, persistido idempotentemente y consultado exactamente una vez a través de la API.
- User Story 2 debe cerrarse antes de considerar la entrega totalmente validada para errores y reconsumo.
- User Story 3 sirve como validación operativa del arranque mínimo y del criterio de aceptación de la pila de cinco servicios.
