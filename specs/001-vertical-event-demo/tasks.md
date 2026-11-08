# Tasks: Primera entrega vertical del observatorio de actividad sísmica

**Input**: `/specs/001-vertical-event-demo/spec.md`, `/specs/001-vertical-event-demo/plan.md`, `/specs/001-vertical-event-demo/research.md`, `/specs/001-vertical-event-demo/data-model.md`, `/specs/001-vertical-event-demo/contracts/api-eventos.md`, `/specs/001-vertical-event-demo/quickstart.md`, `.specify/memory/constitution.md`

**Organización**: tareas agrupadas por historia de usuario para permitir implementación y verificación independientes; el alcance queda limitado a la entrega vertical de prueba del evento sintético.

## Fase 1: Setup (infraestructura compartida)

**Propósito**: preparar la estructura del repositorio y la composición mínima del sistema para la entrega vertical.

- [ ] T001 Crear la estructura base del proyecto en `compose.yaml`, `backend/producer/`, `backend/consumer/`, `backend/api/`, `backend/db/`, `tests/contract/` y `tests/integration/` para la entrega vertical sin añadir servicios no solicitados.
- [ ] T002 [P] Definir la composición de Docker Compose en `compose.yaml` con exactamente cinco servicios: productor Python, Kafka, consumidor Python, PostgreSQL y API FastAPI, sin Spark, Flink, Kubernetes ni ML.
- [ ] T003 [P] Preparar la configuración de entorno y plantillas de variables en `backend/producer/.env.example`, `backend/consumer/.env.example`, `backend/api/.env.example`, `backend/db/.env.example` y `compose.yaml` sin almacenar secretos reales ni credenciales en Git ni en el frontend.

---

## Fase 2: Fundacionales (prerrequisitos bloqueantes)

**Propósito**: dejar la base de datos, los contratos y la semántica de datos lista antes de cualquier historia funcional.

**⚠️ CRÍTICO**: ninguna historia puede empezar hasta completar esta fase.

- [ ] T004 Definir el esquema de persistencia en `backend/db/schema.sql` o `backend/db/migrations/` con `event_message`, `event_current` y `quarantine_record`, manteniendo una sola fila activa por `event_id` y una referencia duradera al payload original en cuarentena.
- [ ] T005 [P] Definir el contrato del mensaje publicado por el productor en `backend/producer/producer.py` y/o `backend/producer/schema.py`, incluyendo `event_id`, `source`, `mode`, `ingested_at`, `updated`, `payload`, `synthetic_flag`, y la distinción clara entre `demo` y flujo real.
- [ ] T006 [P] Definir la lógica de idempotencia del consumidor en `backend/consumer/consumer.py` con comparación por `event_id` y `updated`/versión de origen, ignorando versiones anteriores y reemplazando solo si la nueva versión es más reciente.
- [ ] T007 [P] Definir la semántica explícita de la API en `backend/api/app.py` para devolver `FeatureCollection` válido, metadata obligatoria (`generated`, `last_ingestion`, `mode`, `count`, `truncated`) y un error explícito cuando la persistencia o la consulta fallen, sin presentar como válido un `FeatureCollection` vacío para un error del sistema.
- [ ] T008 Definir el contrato de error de servicio y la política de estado del backend en `specs/001-vertical-event-demo/contracts/api-eventos.md` y `backend/api/errors.py` para distinguir “sin resultados” de “fallo del servicio”; la API no debe afirmar que conoce un fallo del consumidor si el diseño del contrato no define ese estado.
- [ ] T009 Definir la verificación operativa mínima del arranque y del contrato de servicio para esta entrega en `compose.yaml`, `specs/001-vertical-event-demo/quickstart.md` y `specs/001-vertical-event-demo/contracts/api-eventos.md`, sin ejecutar la validación final de la pila antes de completar la implementación funcional.

**Punto de control**: la base de datos, el contrato API y la semántica de idempotencia están listos; puede empezar la implementación de historias.

---

## Fase 3: Historia de usuario 1 - Verificación vertical de un evento sintético (Prioridad: P1) 🎯 MVP

**Objetivo**: publicar un evento sintético, procesarlo con idempotencia, persistirlo y consultarlo por la API exactamente una vez.

**Prueba independiente**: desde la raíz `observatorio-sismico/`, levantar la pila y comprobar que el evento sintético identificado como `demo-evt-001` aparece exactamente una vez en `GET /api/eventos` dentro de un `FeatureCollection` válido.

- [ ] T010 [P] [US1] Preparar la prueba de contrato del endpoint de eventos en `tests/contract/test_api_eventos.py` con validación del schema `FeatureCollection`, `metadata` y `features` para la entrega vertical.
- [ ] T011 [P] [US1] Preparar la prueba de integración del flujo completo en `tests/integration/test_vertical_demo.py` para publicar un evento sintético y comprobar la sola aparición en la API.
- [ ] T012 [US1] Implementar la publicación del evento sintético en `backend/producer/producer.py` con `source="synthetic-demo"`, `mode="demo"`, `synthetic_flag=true` y `event_id` estable para la prueba controlada.
- [ ] T013 [US1] Implementar la captura y normalización del mensaje en `backend/consumer/consumer.py` para leer desde Kafka y preparar el payload de persistencia con marcas temporales en UTC y unidades explícitas.
- [ ] T014 [US1] Implementar la ruta de escritura a PostgreSQL en `backend/db/repository.py` y/o `backend/db/event_store.py` para guardar `event_current` solo si la versión nueva es más reciente, manteniendo un único estado activo por `event_id`.
- [ ] T015 [US1] Implementar la consulta de eventos en `backend/api/app.py` para devolver `GET /api/eventos` con GeoJSON válido y exactamente una instancia visible del evento activo.
- [ ] T016 [US1] Ejecutar la validación del flujo de demostración descrita en `specs/001-vertical-event-demo/quickstart.md` y verificar que la consulta del evento sintético retorna exactamente una vez y sin duplicados.

**Punto de control**: User Story 1 queda funcional y verificable por sí misma con un solo evento sintético.

---

## Fase 4: Historia de usuario 2 - Validación de fallo con persistencia y consulta (Prioridad: P1)

**Objetivo**: distinguir claramente entre ausencia real de resultados y fallo del backend, y asegurar que el consumidor sea idempotente al reconsumir el mismo evento.

**Prueba independiente**: forzar un error de persistencia o de consulta en la ruta de la API y confirmar que la respuesta no se presenta como un `FeatureCollection` vacío válido; además, reconsumir el mismo evento con la misma versión no debe duplicar la fila activa.

- [ ] T017 [P] [US2] Preparar la prueba de contrato de errores en `tests/contract/test_api_errors.py` para comprobar que `features: []` solo es válido en ausencia real de resultados y no cuando la API falla por consulta o cuando el consumidor ha registrado un fallo sin un estado explícito definido por el contrato.
- [ ] T018 [P] [US2] Preparar la prueba de reconsumo y idempotencia en `tests/integration/test_reconsume_event.py` para que el mismo evento con la misma versión no duplique el resultado activo.
- [ ] T019 [US2] Implementar la deduplicación y la comparación de versiones en `backend/consumer/consumer.py` para ignorar mensajes repetidos y solo reemplazar si `updated`/versión es más reciente.
- [ ] T020 [US2] Implementar la cuarentena y el almacenamiento de rechazo en `backend/db/quarantine.py` y `backend/db/schema.sql` con `reason`, `original_payload` y referencia al payload original para auditoría durable y sin confirmar el offset si la escritura falla.
- [ ] T021 [US2] Implementar la respuesta de error explícita en `backend/api/app.py` para los casos de consulta fallida o de servicio degradado definido por el contrato, sin devolver un resultado vacío como respuesta válida del sistema y sin afirmar que conoce un fallo del consumidor si no existe un mecanismo explícito.
- [ ] T022 [US2] Validar los escenarios negativos del quickstart en `specs/001-vertical-event-demo/quickstart.md` para confirmar que: (a) el consumidor registra un fallo y no confirma el offset; (b) la API no devuelve `FeatureCollection` vacío como respuesta válida para un error de consulta; (c) la relectura del evento no duplica el resultado visible.

**Punto de control**: User Story 2 queda funcional y demuestra separación correcta entre “sin resultados” y “error del sistema”.

---

## Fase 5: Historia de usuario 3 - Validación del arranque mínimo de la pila (Prioridad: P2)

**Objetivo**: comprobar que la arquitectura mínima queda levantada y funcionando en un entorno local con Docker Compose y que la prueba vertical queda validada de extremo a extremo.

**Prueba independiente**: ejecutar `docker compose up --build -d` desde la raíz `observatorio-sismico/` y comprobar que los cinco servicios están disponibles y que el evento sintético aparece exactamente una vez vía API.

- [ ] T023 [US3] Preparar la prueba de arranque mínimo en `tests/smoke/test_stack_startup.py` para verificar que el productor, Kafka, consumidor, PostgreSQL y API estén en ejecución y conectados.
- [ ] T024 [US3] Ejecutar la validación de servicios definida en `compose.yaml` y confirmar con `docker compose ps` desde la raíz del repositorio que los cinco servicios obligatorios están levantados y sanos.
- [ ] T025 [US3] Validar el flujo completo de la entrega descrito en `specs/001-vertical-event-demo/quickstart.md`, asegurando que el evento sintético se consulta exactamente una vez mediante la API y que la respuesta cumple el contrato GeoJSON.
- [ ] T026 [US3] Revisar el alcance de la entrega en `specs/001-vertical-event-demo/spec.md` y `specs/001-vertical-event-demo/plan.md` para confirmar que no se introducen ingestión live, histórico completo, enriquecimiento geográfico, estadísticas ni filtros completos, replay completo ni publicación en Netlify.

**Punto de control**: User Story 3 confirma que la pila mínima queda desplegada y verificada sin ampliar el alcance de la entrega.

---

## Fase 6: Pulido y preocupaciones transversales

**Propósito**: cerrar la calidad del hito y revisar coherencia con la constitución y contratos.

- [ ] T027 [P] Revisar la coherencia de `compose.yaml`, `specs/001-vertical-event-demo/quickstart.md` y `specs/001-vertical-event-demo/contracts/api-eventos.md` para que el arranque, la ruta y los criterios de aceptación coincidan exactamente con la raíz del repositorio y la entrega vertical.
- [ ] T028 [P] Revisar que no se introducen requisitos contradictorios con la constitución en `.specify/memory/constitution.md`: cinco servicios obligatorios, idempotencia, cuarentena duradera, país por point-in-polygon, UTC y unidades explícitas, y secretos fuera del repositorio.

---

## Dependencias y orden de ejecución

### Dependencias por fase
- **Fase 1 (Setup)**: no depende de ninguna otra tarea.
- **Fase 2 (Fundacional)**: depende de la preparación del proyecto y bloquea todas las historias de usuario.
- **Fase 3 / Fase 4 / Fase 5**: dependen de la fase fundacional; pueden trabajarse en paralelo si hay varios equipos, pero cada historia debe poder probarse de forma independiente.
- **Fase 6 (Pulido)**: depende de que todas las historias funcionales estén validadas.

### Dependencias reales dentro de cada historia
- User Story 1: `T012` depende de `T005`; `T014` depende de `T004`; `T015` depende de `T007` y `T008`. `T016` se ejecuta tras `T012`, `T013`, `T014`, `T015`.
- User Story 2: `T019` depende de `T006`; `T020` depende de `T004`; `T021` depende de `T007` y `T008`; `T022` se ejecuta tras `T019`, `T020`, `T021`.
- User Story 3: `T024` depende de `T002`; `T025` depende de la validación de User Story 1 y User Story 2; `T026` aplica validación de alcance y no introduce requisitos futuros.

### Oportunidades de paralelismo
- `T002`, `T003` pueden ejecutarse en paralelo tras la etapa de setup.
- `T005`, `T006`, `T007`, `T008` pueden ejecutarse en paralelo dentro de la fase fundacional si la coordinación del contrato está resuelta.
- Las pruebas de contrato e integración de cada historia pueden ejecutarse en paralelo con la implementación del mismo flujo, siempre que la dependencia de contratos quede cerrada.

### Criterios de MVP recomendados
- El MVP mínimo para esta entrega es la User Story 1: evento sintético publicado, persistido idempotentemente y consultado exactamente una vez a través de la API.
- User Story 2 debe cerrarse antes de considerar la entrega totalmente validada para errores y reconsumo.
- User Story 3 sirve como validación operativa del arranque mínimo y del criterio de aceptación de la pila de cinco servicios.

