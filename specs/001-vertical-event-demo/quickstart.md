# Guía rápida de validación para la primera entrega vertical

## Objetivo

Validar que un evento sintético entra en el sistema, se persiste con idempotencia y puede consultarse a través de la API con el formato GeoJSON del contrato.

## Prerrequisitos

- Docker y Docker Compose disponibles en el equipo.
- Repositorio clonado y preparado.
- Frontend entregado ya presente en `observatorio-sismico/frontend`.
- La infraestructura backend aún no implementada, pero el objetivo es que la composición mínima de la entrega pueda levantarse con un único comando.

## Validación de servicios

1. Ejecuta la composición mínima del proyecto desde la raíz del repositorio:
   ```bash
   cd observatorio-sismico
   docker compose up --build -d
   ```
   El archivo de composición esperado es `observatorio-sismico/compose.yaml`.
2. Verifica el estado de los cinco servicios obligatorios:
   ```bash
   docker compose ps
   ```
3. Comprueba que están levantados los servicios de productor, Kafka, consumidor, PostgreSQL y API.

**Resultado esperado**: todos los servicios aparecen activos y sin errores de arranque.

## Publicación y consumo del evento de prueba

1. Publica un evento de prueba sintético claramente identificado, por ejemplo con `event_id = demo-evt-001` y metadata de `synthetic_flag = true`.
2. Verifica que el consumidor lo procesa y lo persiste.
3. Reintenta la misma publicación o el reconsumo del mismo evento sin cambiar la versión.

**Resultado esperado**: la base almacena una sola versión activa para ese evento y no duplica el resultado visible.

## Consulta API

1. Consulta el endpoint del contrato:
   ```bash
   curl http://localhost:8000/api/eventos
   ```
2. Comprueba que la respuesta es un JSON válido con `type: "FeatureCollection"`.
3. Revisa que el evento de prueba aparece exactamente una vez.

**Resultado esperado**: el evento de prueba aparece una sola vez en `features` y la respuesta sigue el esquema del contrato.

## Validación de errores explícitos

1. Fuerza o simula un fallo de persistencia del consumidor y comprueba que el consumidor lo registra en cuarentena y no confirma el offset.
2. Intenta consultar la API.
3. Comprueba que la respuesta no se presenta como un `FeatureCollection` válido vacío para un error del backend; la API solo comunica los errores que observa directamente y no asume un fallo del consumidor si el contrato no define ese estado.

**Resultado esperado**: el consumidor conserva el fallo sin confirmar el offset, y la respuesta de la API comunica un error de forma explícita o un estado de ausencia real y no se confunde con éxito.

## Criterios de aceptación de la fase

- **SC-001**: los cinco servicios obligatorios están disponibles y el evento sintético consultado aparece exactamente una vez mediante la API.
- El evento sintético se procesa y persiste una sola vez como estado actual.
- El reconsumo del mismo evento no duplica el resultado visible.
- La API devuelve un GeoJSON `FeatureCollection` válido conforme al contrato.
- Los errores se distinguen explícitamente de un resultado vacío válido.
- La validación no exige todavía USGS live, histórico completo ni despliegue en Netlify.

## Limitaciones de esta guía

- No incluye ingestión automática de USGS ni históricos completos.
- No incluye estadísticas ni filtros avanzados.
- No incluye despliegue real ni publicación en Netlify.
- El criterio SC-001 se define en términos binarios y verificables: disponibilidad de servicios y consulta exacta del evento sintético una sola vez.
