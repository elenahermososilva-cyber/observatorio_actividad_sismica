# Plan de implementación: Primera entrega vertical del observatorio de actividad sísmica

**Rama**: `001-vertical-event-demo` | **Fecha**: 2026-11-09 | **Especificación**: [spec.md](./spec.md)

**Entrada**: Especificación de funcionalidad en `/specs/001-vertical-event-demo/spec.md`

## Resumen

La primera entrega vertical debe demostrar, sin abarcar aún la ingesta live ni el sistema completo, que un evento sintético claramente identificado recorre productor, Kafka, consumidor, PostgreSQL y API FastAPI y puede consultarse como un `FeatureCollection` GeoJSON según el contrato. El objetivo del plan es validar la arquitectura obligatoria del proyecto, la idempotencia del consumidor, la persistencia y la separación clara entre errores de persistencia del consumidor y errores de consulta de la API. Ante un fallo transitorio de escritura, el consumidor registra el error y no confirma el offset; confirma offsets solo después de persistir duraderamente el estado. Los registros rechazados se ponen en cuarentena duradera antes de confirmar su offset. La API solo informa de fallos que observa directamente y no presenta una consulta fallida como una respuesta vacía válida.

## Contexto técnico

**Lenguaje/Versión**: Python 3.11+ para productor, consumidor y API; el frontend existente ya usa Angular/Leaflet y no se sustituye en esta fase.

**Dependencias principales**: Kafka (cliente Python, ej. `aiokafka`), FastAPI, Pydantic, PostgreSQL driver, Docker Compose, y el frontend Angular ya entregado en `observatorio-sismico/frontend`.

**Almacenamiento**: PostgreSQL persistente mediante volúmenes de Docker; Kafka como transporte de mensajes y retención de mensajes para reinicios y relecturas; el almacenamiento de origen de la prueba es un evento sintético controlado.

**Semántica temporal y unidades**: conservar por separado ocurrencia del evento, actualización de la fuente, ingesta y reproducción. Los tiempos se expresan en UTC con unidades documentadas; los valores temporales de la fuente y el contrato GeoJSON usan milisegundos desde la época Unix cuando corresponda. `replayed_at` es nulo en esta entrega, que no implementa replay. Coordenadas se expresan en grados decimales y profundidad en kilómetros.

**Pruebas**: Validación de humo con Docker Compose y comprobación de mensajes publicados/consumidos, persistencia y respuesta API; pruebas de contrato de API y de idempotencia del consumidor.

**Plataforma de destino**: Entorno local con Docker Desktop/Compose; no se exige despliegue cloud ni publicación en Netlify en esta entrega.

**Tipo de proyecto**: Pipeline de datos + servicio web + flujo de integración de prueba vertical.

**Objetivos de rendimiento**: No se fijan valores inventados. La validación de la entrega se define por disponibilidad de servicios y resultado puntual del evento sintético, no por un tiempo arbitrario.

**Restricciones**: Cinco servicios obligatorios separados; sin Spark, Flink, Kubernetes ni aprendizaje automático; entornos locales; alcance limitado a un evento sintético y a la demostración vertical de la arquitectura.

**Escala/alcance**: Una única prueba sintética, un único flujo de publicación/consumo y una consulta API con un resultado GeoJSON válido. No se incluye carga histórica ni ingesta live automática de USGS.

## Comprobación de la constitución

*GATE: debe pasar antes de la investigación de fase 0. Se vuelve a revisar tras el diseño de fase 1.*

- Pasada: arquitectura obligatoria de cinco servicios separados en Docker Compose.
- Pasada: no se introducen requisitos de Spark, Flink, Kubernetes ni aprendizaje automático.
- Pasada: se mantiene la obligación de idempotencia del consumidor, confirmación de offsets y cuarentena de registros rechazados.
- Pasada: los fallos transitorios de escritura del consumidor no confirman offsets; los registros rechazados se ponen en cuarentena duradera antes de confirmar. La API distingue una consulta correcta sin resultados de un fallo de su propia consulta y no afirma conocer fallos del consumidor.
- Pasada: los tiempos de ocurrencia, actualización, ingesta y reproducción permanecen diferenciados, con UTC y unidades explícitas.
- Pasada: se conserva la separación entre origen de verdad, integración y presentación del frontend.
- Pasada: no se almacenan secretos en frontend ni en Git.
- Pasada: el criterio SC-001 se define como verificable sin inventar un tiempo: los cinco servicios deben estar disponibles y el evento sintético debe consultarse exactamente una vez mediante la API.

## Estructura del proyecto

### Documentación de esta funcionalidad

```text
specs/001-vertical-event-demo/
├── plan.md                # Este archivo
├── research.md            # Fase 0
├── data-model.md          # Fase 1
├── quickstart.md           # Fase 1
├── contracts/             # Fase 1
├── spec.md                # Especificación funcional
├── checklists/
│   └── requirements.md    # Checklist de calidad
└── tasks.md               # Fase 2 (no creada aquí)
```

### Código fuente (raíz del repositorio)

```text
observatorio-sismico/
├── frontend/
│   ├── src/
│   ├── public/
│   ├── angular.json
│   └── package.json
├── compose.yaml           # composición Docker de la entrega vertical
├── backend/
│   ├── producer/
│   ├── consumer/
│   ├── api/
│   └── db/
├── docs/
│   └── ...
└── README.md
```

**Decisión de estructura**: Se reutiliza el frontend ya entregado y la primera entrega mantiene la composición Docker en la raíz `observatorio-sismico/`, con la capa backend bajo `backend/` para separar responsabilidades sin crear una estructura adicional innecesaria. Esta decisión coincide con la guía de validación y evita inconsistencia entre rutas y ejecución real del comando `docker compose up --build -d`.

## Seguimiento de complejidad

No hay violaciones de la constitución que requieran justificación adicional. El criterio SC-001 se define de forma binaria y verificable: los cinco servicios deben estar disponibles y el evento sintético debe consultarse exactamente una vez mediante la API, sin necesidad de inventar un valor temporal.
