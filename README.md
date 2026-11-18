# Observatorio de actividad sísmica

Proyecto de Big Data (RA1): datos de terremotos de USGS → Kafka → PostgreSQL → API FastAPI → panel Angular/Leaflet.

- **Panel publicado:** https://observatorio-sismico-elena.netlify.app (necesita que el backend y el túnel estén activos; ver «Defensa»)
- **API pública (túnel ngrok, dominio fijo):** https://onset-deepen-situation.ngrok-free.dev
- **Todo el código está en** [`observatorio-sismico/`](observatorio-sismico/). Los comandos se ejecutan desde esa carpeta.

## Arquitectura

Cinco servicios de Docker Compose, y solo cinco: **productor** (Python + aiokafka), **Kafka**, **consumidor** (Python + aiokafka), **PostgreSQL** y **API** (FastAPI). Solo la API se publica, en `127.0.0.1:8000`. El panel Angular se compila y publica en Netlify; ngrok da acceso HTTPS a la API.

## Arranque (backend)

Requisitos: Docker con Compose y acceso a internet.

```bash
cd observatorio-sismico
cp .env.example .env            # editar POSTGRES_PASSWORD (y DATABASE_URL con la misma clave)
docker compose up --build -d
docker compose ps               # los 5 servicios deben aparecer como «healthy»
curl http://127.0.0.1:8000/api/salud?mode=live
```

Por defecto el productor consulta el feed de USGS cada 60 s (`PRODUCER_MODE=live`). Modos alternativos en `.env`: `demo` (un evento sintético) y `replay` (reproducción acelerada del histórico, aislada de los datos live).

### Histórico 2025 (carga única)

```bash
docker compose run --rm --no-deps producer python -m backend.producer.history_download   # descarga a data/raw/historico
docker compose run --rm --no-deps consumer python -m backend.consumer.history_loader     # carga en el esquema «historico»
```

Los originales se guardan en `observatorio-sismico/data/raw/` (no se versionan; procedimiento para regenerarlos en `data/README.md`).

## Defensa: activar el túnel y el panel

1. Backend arrancado (sección anterior) y `PRODUCER_MODE=live`.
2. Túnel con el dominio fijo de la cuenta de ngrok: `ngrok http --url=onset-deepen-situation.ngrok-free.dev 8000`. El authtoken se registra con `ngrok config add-authtoken …` en el equipo; **nunca** va en Git ni en el frontend.
3. `CORS_ORIGINS` en `.env` debe incluir el origen exacto del panel (`https://observatorio-sismico-elena.netlify.app`); después, `docker compose up -d --force-recreate api`.
4. Abrir el panel. Checklist completa y tabla de fallos: [`docs/despliegue.md`](observatorio-sismico/docs/despliegue.md).

Para publicar de nuevo el panel (si cambia `frontend/public/config.json`): ver «Volver a publicar el panel» en `docs/despliegue.md`.

## Pruebas

```bash
cd observatorio-sismico
python -m unittest discover -s tests/unit                 # unitarias (Python 3.11+)
# contrato, integración y aceptación se ejecutan dentro de la imagen `api`: ver specs/001-vertical-event-demo/quickstart.md
```

## Dónde está cada entregable (ENUNCIADO §12)

| Entregable | Ubicación |
|---|---|
| Código, Dockerfile, `compose.yaml`, dependencias fijadas, `.env.example` | `observatorio-sismico/backend/`, `compose.yaml`, `backend/requirements.txt`, `.env.example` |
| Memoria: extracción, calidad (antes/después), modelo conceptual/lógico/físico e índices, análisis con 3 conclusiones, complejidad, costes, limitaciones | [`docs/memoria.md`](observatorio-sismico/docs/memoria.md) |
| Diccionario de datos | [`docs/diccionario-de-datos.md`](observatorio-sismico/docs/diccionario-de-datos.md) |
| Registro de consultas y procedencia | [`docs/consultas-y-procedencia.md`](observatorio-sismico/docs/consultas-y-procedencia.md) |
| Reglas de calidad y geografía | [`docs/fase8-calidad-y-geografia.md`](observatorio-sismico/docs/fase8-calidad-y-geografia.md) |
| Informe de complejidad (mediciones) | `docs/evidencias/complejidad.md` y `api-latencia.json` |
| Evidencias de aceptación y reproducción histórica | `docs/evidencias/aceptacion-s11.md`, `pila-real.md`, `panel.md` |
| Capturas de los filtros del análisis | `docs/evidencias/analisis/*.png` |
| Guion del vídeo y esquema de la explicación individual | [`docs/guion-video.md`](observatorio-sismico/docs/guion-video.md) |
| Material del curso (requisitos, no se edita) | `ENUNCIADO.md`, `FAQ-ALUMNADO.md`, `CONTRATO-API.md`, `FUENTES-Y-LICENCIAS.md`, `VALIDACION.md` |

## Fuentes y licencias

USGS Earthquake Catalog (dominio público), Natural Earth (dominio público), mapa base © OpenStreetMap contributors. Detalle en `observatorio-sismico/FUENTES-Y-LICENCIAS.md`.
