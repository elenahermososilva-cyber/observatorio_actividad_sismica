# Observatorio de actividad sísmica

![Panel del observatorio: pestaña Resumen con indicadores, trazo de actividad y mapa de epicentros de las últimas 24 horas](observatorio-sismico/docs/evidencias/panel-live.png)

*Pestaña «Resumen», lo primero que se ve al abrir el panel: filtros, indicadores, trazo de actividad con los terremotos reales de las últimas 24 h y mapa de epicentros coloreados por profundidad.*

Proyecto de Big Data (RA1): datos de terremotos de USGS → Kafka → PostgreSQL → API FastAPI → panel Angular/Leaflet.

- **Panel publicado:** https://observatorio-sismico-elena.netlify.app (necesita que el backend y el túnel estén activos; ver «Defensa»)
- **API pública (túnel ngrok, dominio fijo):** https://onset-deepen-situation.ngrok-free.dev
- **Todo el código está en** [`observatorio-sismico/`](observatorio-sismico/). Los comandos se ejecutan desde esa carpeta.

## Arquitectura

Cinco servicios de Docker Compose, y solo cinco: **productor** (Python + aiokafka), **Kafka**, **consumidor** (Python + aiokafka), **PostgreSQL** y **API** (FastAPI). Solo la API se publica, en `127.0.0.1:8000`. El panel Angular se compila y publica en Netlify; ngrok da acceso HTTPS a la API. La definición de los servicios está en [`compose.yaml`](observatorio-sismico/compose.yaml).

## Qué se reutilizó y qué se ha desarrollado

| Origen | Contenido |
|---|---|
| **Proporcionado por el curso** (commit `86c4eb1`, «Estructura base proporcionada») | Documentos de requisitos (hoy en [`docs/curso/`](observatorio-sismico/docs/curso/)); esqueleto Angular con el mapa Leaflet base ([`app.component.*`](observatorio-sismico/frontend/src/app/), [`main.ts`](observatorio-sismico/frontend/src/main.ts), [`angular.json`](observatorio-sismico/frontend/angular.json), [`package.json`](observatorio-sismico/frontend/package.json) y [`package-lock.json`](observatorio-sismico/frontend/package-lock.json)); [`paises.geojson`](observatorio-sismico/frontend/public/datos/paises.geojson) (Natural Earth) y [`terremotos-demo.geojson`](observatorio-sismico/frontend/public/datos/terremotos-demo.geojson) (4 eventos ficticios); [`netlify.toml`](observatorio-sismico/frontend/netlify.toml) y [`_redirects`](observatorio-sismico/frontend/public/_redirects) |
| **Desarrollado** | Todo el backend ([`backend/`](observatorio-sismico/backend/): productor, consumidor, migraciones SQL, API), [`Dockerfile`](observatorio-sismico/backend/Dockerfile) y [`compose.yaml`](observatorio-sismico/compose.yaml), pruebas ([`tests/`](observatorio-sismico/tests/)), scripts de medición ([`scripts/`](observatorio-sismico/scripts/)) y documentación ([`docs/`](observatorio-sismico/docs/)) |
| **Modificado o añadido en el frontend** | [`app.component.*`](observatorio-sismico/frontend/src/app/) reescrito (estado, filtros, refresco, avisos, pestañas), y nuevos [`api.ts`](observatorio-sismico/frontend/src/app/api.ts), [`models.ts`](observatorio-sismico/frontend/src/app/models.ts), [`event-map`](observatorio-sismico/frontend/src/app/event-map.component.ts), [`bar-chart`](observatorio-sismico/frontend/src/app/bar-chart.component.ts), [`scatter-chart`](observatorio-sismico/frontend/src/app/scatter-chart.component.ts), [`activity-trace`](observatorio-sismico/frontend/src/app/activity-trace.component.ts), [`event-table`](observatorio-sismico/frontend/src/app/event-table.component.ts) y [`event-detail`](observatorio-sismico/frontend/src/app/event-detail.component.ts); [`config.json`](observatorio-sismico/frontend/public/config.json) apunta a la API. Las versiones fijadas de Angular, ngx-leaflet y Leaflet no se han cambiado |

## Requisitos y versiones

| Herramienta | Versión utilizada | Para qué |
|---|---|---|
| Docker Engine con Compose v2 | Docker Desktop (Windows 11) | Los cinco servicios |
| Imágenes | `python:3.12-slim`, `apache/kafka:3.9.0` (KRaft), `postgres:17.2` | Fijadas en [`backend/Dockerfile`](observatorio-sismico/backend/Dockerfile) y [`compose.yaml`](observatorio-sismico/compose.yaml) |
| Dependencias Python | Fijadas en [`backend/requirements.txt`](observatorio-sismico/backend/requirements.txt) (directas e indirectas) | Se instalan dentro de la imagen |
| Python en el equipo | 3.11 o superior (solo para las pruebas unitarias y los scripts [`medir_api.py`](observatorio-sismico/scripts/medir_api.py) y [`procedencia.py`](observatorio-sismico/scripts/procedencia.py)) | Biblioteca estándar |
| Node.js | 22.12+ o 24 (Angular 20.3, ngx-leaflet 20.0, Leaflet 1.9.4, fijadas en [`package-lock.json`](observatorio-sismico/frontend/package-lock.json)) | Panel |
| ngrok | Agente v3 con cuenta gratuita y dominio fijo | Túnel HTTPS a la API |

## Arranque (backend)

```bash
cd observatorio-sismico
cp .env.example .env            # editar POSTGRES_PASSWORD (y DATABASE_URL con la misma clave) y CORS_ORIGINS
docker compose up --build -d
docker compose ps               # los 5 servicios deben aparecer como «healthy»
curl http://127.0.0.1:8000/api/salud?mode=live
```

La plantilla de configuración es [`.env.example`](observatorio-sismico/.env.example); el `.env` real no se versiona.

**Las tablas se crean solas:** cada servicio Python ejecuta `python -m backend.db.migrate` antes de arrancar. Aplica [`backend/db/schema.sql`](observatorio-sismico/backend/db/schema.sql) y las migraciones de [`backend/db/migrations/`](observatorio-sismico/backend/db/migrations/) (una vez, idempotente) y carga el catálogo de países en `ref.dim_country`.

Por defecto el productor consulta el feed de USGS cada 60 s (`PRODUCER_MODE=live`). Modos alternativos en `.env`: `demo` (un evento sintético) y `replay` (reproducción acelerada del histórico, aislada de los datos live).

**Estado y logs:**

```bash
docker compose ps                         # salud de los 5 servicios
docker compose logs -f producer consumer  # una línea por consulta a USGS y por decisión NEW/DUPLICATE/REVISION/STALE
docker compose logs --tail 50 api
```

**Detener y qué se conserva:**

- `docker compose stop` o `docker compose down`: se paran los servicios y **se conservan** los volúmenes `postgres_data` (eventos, versiones, cuarentena, estado del productor) y `kafka_data` (mensajes, 168 h), y los originales en `data/raw/`. Al volver a arrancar, el productor sigue desde su estado y el consumidor desde su último offset confirmado, sin duplicar nada.
- `docker compose down -v`: **borra** los volúmenes, y con ellos la base de datos y Kafka. Hay que volver a cargar el histórico, aunque los originales de `data/raw/` siguen ahí.

### Histórico 2025 (carga única)

```bash
docker compose run --rm --no-deps producer python -m backend.producer.history_download   # descarga a data/raw/historico
docker compose run --rm --no-deps consumer python -m backend.consumer.history_loader     # carga en el esquema «historico»
```

Los originales se guardan en `observatorio-sismico/data/raw/` (no se versionan; procedimiento para regenerarlos en [`data/README.md`](observatorio-sismico/data/README.md)).

### Reproducción histórica (demostración con actividad garantizada)

Requiere el histórico descargado. Se ejecuta **junto al productor live, sin pararlo**, y publica en el topic `sismos.replay` (esquema `replay`):

```bash
docker compose run --rm --no-deps -e PRODUCER_MODE=replay -e REPLAY_INTERVAL_SECONDS=0.2 producer
```

Envía los 10 primeros eventos M ≥ 5 de 2025 en orden de ocurrencia, más tres casos controlados (duplicado, revisión y versión antigua). Se ve en el panel con `?mode=replay&range=custom&from=2025-01-01&to=2025-01-03`, bajo el aviso «REPRODUCCIÓN». Detalle y resultados: [`docs/memoria.md` §9.1](observatorio-sismico/docs/memoria.md#91-reproducción-histórica).

## Panel (frontend)

```bash
cd observatorio-sismico/frontend
npm ci
npm start                 # desarrollo: http://localhost:4200
npm run build             # producción: dist/observatorio/browser
```

El panel usa un tema oscuro («sala de control»: azul noche, acento cian, cifras en JetBrains Mono y texto en Inter, cargadas desde Google Fonts con tipografía de respaldo del sistema). La cabecera incluye un **trazo de actividad** con los eventos reales del periodo consultado: cada terremoto es un pico y su altura depende de la magnitud (es una escala visual, no una señal sísmica medida). Las variables de color están en [`styles.css`](observatorio-sismico/frontend/src/styles.css).

El panel se organiza en pestañas: **Resumen** (indicadores y mapa), **Análisis** (gráficos interactivos y comparación histórica), **Eventos** (tabla), **Histórico 2025** (consulta paginada del catálogo cargado) y **Estado del sistema**. Pulsar un evento en la tabla, el mapa o la dispersión abre su ficha con un mapa del epicentro. La pestaña va en la URL (`#analisis`, `#historico`…).

[`public/config.json`](observatorio-sismico/frontend/public/config.json) decide de dónde lee el panel: `mode: "api"`, `apiUrl` (la URL HTTPS de ngrok, **sin** `/api` al final; para desarrollo, `http://localhost:8000`), `dataMode` (`live`, `demo` o `replay`) y `refreshMs` (60000). Es un archivo público: nunca lleva secretos. Para publicar en Netlify: «Volver a publicar el panel» en [`docs/despliegue.md`](observatorio-sismico/docs/despliegue.md#volver-a-publicar-el-panel).

## Defensa: activar el túnel y el panel

1. Backend arrancado (sección anterior) y `PRODUCER_MODE=live`.
2. Túnel con el dominio fijo de la cuenta de ngrok: `ngrok http --url=onset-deepen-situation.ngrok-free.dev 8000`. El authtoken se registra con `ngrok config add-authtoken …` en el equipo; **nunca** va en Git ni en el frontend.
3. `CORS_ORIGINS` en `.env` debe incluir el origen exacto del panel (`https://observatorio-sismico-elena.netlify.app`); después, `docker compose up -d --force-recreate api`.
4. Abrir el panel. Checklist completa y tabla de fallos: [`docs/despliegue.md`](observatorio-sismico/docs/despliegue.md).

Para publicar de nuevo el panel (si cambia [`frontend/public/config.json`](observatorio-sismico/frontend/public/config.json)): ver «Volver a publicar el panel» en [`docs/despliegue.md`](observatorio-sismico/docs/despliegue.md#volver-a-publicar-el-panel).

## Pruebas

Todos los comandos, desde `observatorio-sismico/`. Las unitarias se ejecutan en el equipo; las de contrato, integración y aceptación, dentro de la imagen `api` (crean y borran su propia base temporal, no tocan los datos reales).

```bash
# Unitarias (Python 3.11+ en el equipo)
python -m unittest discover -s tests/unit

# Contrato de la API e integración con PostgreSQL
docker compose run --rm --no-deps -v "$(pwd)/tests:/app/tests" api sh -c \
  "python -m unittest discover -s tests/contract -t . -p 'test_api_*.py' && \
   python -m unittest discover -s tests/integration -t . -p 'test_*_db.py'"

# Aceptación: una prueba por fila del ENUNCIADO (con EVIDENCE_DIR reescribe docs/evidencias/aceptacion-s11.*)
docker compose run --rm --no-deps -v "$(pwd)/tests:/app/tests" -v "$(pwd)/docs/evidencias:/app/docs/evidencias" \
  -e EVIDENCE_DIR=/app/docs/evidencias api python -m unittest discover -s tests/acceptance -t . -v
```

En PowerShell, sustituye `$(pwd)` por `${PWD}` y la barra invertida final por un acento grave (`` ` ``). Las pruebas de aceptación siguen la tabla del [`ENUNCIADO.md`](observatorio-sismico/docs/curso/ENUNCIADO.md) (§11) y escriben [`aceptacion-s11.md`](observatorio-sismico/docs/evidencias/aceptacion-s11.md). Las pruebas contra la pila en marcha (arranque, reinicio del consumidor, caída de PostgreSQL) y las de navegador sobre el panel están en [`specs/001-vertical-event-demo/quickstart.md`](specs/001-vertical-event-demo/quickstart.md) (secciones 4, 7 y 8); sus scripts están en [`tests/e2e/`](observatorio-sismico/tests/e2e/).

## Dónde está cada entregable

| Entregable | Ubicación |
|---|---|
| Código, Dockerfile, `compose.yaml`, dependencias fijadas, `.env.example` | [`backend/`](observatorio-sismico/backend/), [`Dockerfile`](observatorio-sismico/backend/Dockerfile), [`compose.yaml`](observatorio-sismico/compose.yaml), [`requirements.txt`](observatorio-sismico/backend/requirements.txt), [`package-lock.json`](observatorio-sismico/frontend/package-lock.json), [`.env.example`](observatorio-sismico/.env.example) |
| SQL: creación de tablas, restricciones e índices | [`schema.sql`](observatorio-sismico/backend/db/schema.sql) y [`migrations/`](observatorio-sismico/backend/db/migrations/) (consultas de calidad en [`memoria.md` §3.3](observatorio-sismico/docs/memoria.md#33-consultas-para-reproducir-las-cifras)) |
| Memoria: extracción, calidad (antes/después), modelo conceptual/lógico/físico e índices, análisis con 3 conclusiones, complejidad, costes, limitaciones | [`docs/memoria.md`](observatorio-sismico/docs/memoria.md) |
| Análisis de calidad con gráficos (indicadores por dimensión y conjunto, completitud, cuarentena, actualidad, revisiones) | [`docs/analisis-calidad.md`](observatorio-sismico/docs/analisis-calidad.md) (generado por [`graficos_calidad.py`](observatorio-sismico/scripts/graficos_calidad.py)) |
| Diccionario de datos | [`docs/diccionario-de-datos.md`](observatorio-sismico/docs/diccionario-de-datos.md) |
| Registro de consultas y procedencia | [`docs/consultas-y-procedencia.md`](observatorio-sismico/docs/consultas-y-procedencia.md) |
| Reglas de calidad y geografía | [`docs/reglas-calidad-y-geografia.md`](observatorio-sismico/docs/reglas-calidad-y-geografia.md) |
| Informe de complejidad (mediciones) | [`complejidad.md`](observatorio-sismico/docs/evidencias/complejidad.md) y [`api-latencia.json`](observatorio-sismico/docs/evidencias/api-latencia.json) |
| Evidencias de aceptación y reproducción histórica | [`aceptacion-s11.md`](observatorio-sismico/docs/evidencias/aceptacion-s11.md), [`pila-real.md`](observatorio-sismico/docs/evidencias/pila-real.md), [`panel.md`](observatorio-sismico/docs/evidencias/panel.md) (incluye las capturas de cada sección del panel en [`secciones/`](observatorio-sismico/docs/evidencias/secciones/)) |
| Capturas de los filtros del análisis | [`docs/evidencias/analisis/`](observatorio-sismico/docs/evidencias/analisis/) |

## Fuentes y licencias

USGS Earthquake Catalog (dominio público), Natural Earth (dominio público), mapa base Esri «Canvas Dark Gray» (© Esri, HERE, Garmin, OpenStreetMap contributors; se consulta sin clave de API). Detalle de las fuentes del curso en [`observatorio-sismico/docs/curso/FUENTES-Y-LICENCIAS.md`](observatorio-sismico/docs/curso/FUENTES-Y-LICENCIAS.md).
