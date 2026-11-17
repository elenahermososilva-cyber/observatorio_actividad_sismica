# Guía rápida de validación para la primera entrega vertical

## Objetivo

Validar que un evento sintético entra por el productor, viaja por Kafka, el consumidor lo persiste con idempotencia en PostgreSQL y la API lo sirve como `FeatureCollection` conforme al contrato. Todos los comandos se ejecutan desde `observatorio-sismico/`.

## Prerrequisitos

- Docker y Docker Compose v2.
- Python 3.11+ en el host (solo para lanzar los tests; no hace falta instalar dependencias).
- Primera vez: `cp .env.example .env`. Si cambias `POSTGRES_PASSWORD`, cambia también la contraseña dentro de `DATABASE_URL`.
- En Git Bash de Windows, antepón `MSYS_NO_PATHCONV=1` a los `docker compose exec` que lleven rutas de Linux.

## 1. Arranque y servicios (SC-001)

```bash
docker compose up --build -d
docker compose ps
```

**Esperado**: cinco servicios (`producer`, `kafka`, `consumer`, `postgres`, `api`) en `running` y `healthy`. Solo la API aparece publicada, en `127.0.0.1:8000`. Kafka y PostgreSQL no se publican. Tarda unos 15 s en frío.

Automatizado: `python -m unittest tests.smoke.test_stack_startup -v`.

## 2. Evento sintético exactamente una vez (SC-002, SC-003)

El productor publica `demo-evt-001` al arrancar (`source=synthetic-demo`, `mode=demo`, `synthetic_flag=true`) y, con `DEMO_DUPLICATES=1` (valor de `.env.example`), reenvía una copia de la misma versión.

```bash
curl "http://localhost:8000/api/eventos?start=2026-10-27T00:00:00Z"            # modo por defecto: API_DEFAULT_MODE=demo
curl "http://localhost:8000/api/eventos?mode=live&start=2026-10-27T00:00:00Z"  # datos aislados: 0 eventos
```

El evento ocurre el 2026-10-27T14:00:00Z. Sin `start`, la ventana por defecto son las últimas 24 h y la respuesta es legítimamente `features: []`. No se alteran las fechas del evento para que aparezca.

**Esperado**: `type: "FeatureCollection"`, `metadata.count = 1`, `features[0].id = "demo-evt-001"`, coordenadas `[-3.7, 40.4, 12]`, `country_id: null`.

En la base:

```bash
docker compose exec postgres psql -U observatorio -d observatorio -c \
  "select event_id, current_version_ms from demo.event_current; select count(*) from demo.event_message;"
```

**Esperado**: una fila en `event_current` y una en `event_message`, pese a haber recibido dos mensajes con la misma versión.

Automatizado: `python -m unittest tests.integration.test_vertical_demo tests.integration.test_reconsume_event -v`. El segundo detiene el consumidor, retrocede sus offsets al principio del topic, lo arranca y comprueba que el estado no cambia (SC-003).

## 3. Escenarios negativos (SC-004)

```bash
docker compose stop postgres
curl -i "http://localhost:8000/api/eventos?start=2026-10-27T00:00:00Z"   # 503 + {"error": {...}}, nunca features: []
docker compose logs consumer --tail 5                                      # "database unavailable ... offset NOT committed"
docker compose start postgres                                              # todo se recupera solo
```

**Esperado**:
- (a) El consumidor registra el fallo y no confirma el offset: el lag del grupo se mantiene mientras la base está caída.
- (b) La API responde **503** con `{"error": {"code": "database_unavailable", ...}}`. Un `features: []` con 200 solo ocurre cuando la base responde y no hay eventos.
- (c) Al volver PostgreSQL, el consumidor procesa lo pendiente y la relectura no duplica nada.

Un dato **inválido** (JSON roto, coordenadas fuera de rango, tipo distinto de `earthquake`) va a `quarantine_record` con su motivo y su referencia Kafka y el offset sí se confirma:

```bash
printf '{"roto":\n' | docker compose exec -T kafka /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic sismos.demo
docker compose exec postgres psql -U observatorio -d observatorio -c "select reason, kafka_offset from demo.quarantine_record"
```

Automatizado: `python -m unittest tests.integration.test_failure_scenarios -v` (apaga y reinicia PostgreSQL; tarda ~1 min).

## 4. Batería completa

```bash
# Host (necesitan la pila levantada)
python -m unittest discover -s tests/unit
python -m unittest tests.smoke.test_stack_startup tests.integration.test_vertical_demo \
                   tests.integration.test_reconsume_event tests.integration.test_failure_scenarios

# Dentro del contenedor (contrato con base simulada e integración con PostgreSQL real)
docker compose run --rm --no-deps -v "$(pwd)/tests:/app/tests" api sh -c \
  "python -m unittest discover -s tests/contract -t . -p 'test_api_*.py' && \
   python -m unittest discover -s tests/integration -t . -p 'test_*_db.py'"
```

## 5. Modos del productor: live, replay e histórico (Fase 7)

`PRODUCER_MODE` en `.env` elige qué hace el servicio `producer` (`demo` por defecto). Tras cambiarlo: `docker compose up -d --force-recreate producer`.

| Modo | Qué hace | Esquema | Cómo verlo |
|---|---|---|---|
| `demo` | Publica `demo-evt-001` (+ duplicados) y se queda en reposo. | `demo` | `curl "localhost:8000/api/eventos?start=2026-10-27"` |
| `live` | Consulta el feed de USGS cada `POLL_SECONDS` (60 s) y publica solo novedades y revisiones. | `live` | `curl "localhost:8000/api/eventos?mode=live"` (ventana por defecto: últimas 24 h) |
| `replay` | Reproduce de forma acelerada una selección del histórico (sección siguiente). | `replay` | `curl "localhost:8000/api/eventos?mode=replay&start=2025-01-01&end=2025-01-03"` |

Para que la API use `live` sin escribir `?mode=live`, pon `API_DEFAULT_MODE=live` y recrea `api`. Los datos de cada modo viven en un esquema distinto y nunca se mezclan.

**Histórico 2025** (una vez; el resto de veces se reutiliza):

```bash
docker compose run --rm --no-deps producer python -m backend.producer.history_download
```

**Replay.** Requiere el histórico descargado. Variables: `REPLAY_START`, `REPLAY_COUNT` (10), `REPLAY_MIN_MAG` (5.0), `REPLAY_INTERVAL_SECONDS` (2), `REPLAY_INJECT_CASES` (true).

```bash
sed -i 's/^PRODUCER_MODE=.*/PRODUCER_MODE=replay/' .env && docker compose up -d --force-recreate producer
docker compose logs -f producer consumer
```

Publica los 10 eventos más antiguos con M ≥ 5 desde `REPLAY_START`, en orden de ocurrencia, y añade tres casos controlados. Resultado esperado del consumidor: **10 `NEW`, 1 `DUPLICATE`, 1 `REVISION`, 1 `STALE`**; en `replay.event_current` quedan 10 filas y en `replay.event_message` 11. El tiempo de ocurrencia original no se toca; el de reproducción se guarda aparte (`replay_at`). La revisión inyectada lleva `synthetic_flag=true` y `source="replay-injected"`. Volver a ejecutarlo no cambia nada (todo es `DUPLICATE`/`STALE`); para repetir desde cero: `TRUNCATE replay.event_current, replay.event_message, replay.quarantine_record;`.

Los tests de la Fase 7 (`test_phase7_pure`, `test_usgs_client`, `test_live_replay_db`) no salen a internet: simulan USGS y Kafka.

## 6. Limpieza

`docker compose down` conserva los datos; `docker compose down -v` borra los volúmenes (Kafka, PostgreSQL y originales).

## Criterios de aceptación de la fase

- **SC-001**: cinco servicios disponibles y sanos; el evento sintético aparece exactamente una vez en la API.
- **SC-002**: recorre productor → Kafka → consumidor → PostgreSQL → API como una única entidad.
- **SC-003**: reprocesarlo (duplicado, relectura del topic, reinicio) no duplica el estado.
- **SC-004**: fallo de persistencia ⇒ offset sin confirmar; fallo de consulta ⇒ 503 explícito, nunca una colección vacía válida; dato inválido ⇒ cuarentena.
- **SC-005**: hito vertical verificable sin ingesta live, histórico, país, estadísticas ni Netlify.

## Limitaciones de esta guía

Las secciones 1 a 4 validan la entrega vertical. La sección 5 cubre la ingesta live, el histórico y el replay. Siguen fuera: asignación de país, estadísticas, filtros `min_mag`/`country_id`, CORS y despliegue en Netlify/ngrok.
