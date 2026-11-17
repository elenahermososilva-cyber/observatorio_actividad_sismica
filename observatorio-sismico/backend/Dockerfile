# Imagen común de producer, consumer y api (comando distinto por servicio).
# Contexto de build: la raíz observatorio-sismico/ (ver compose.yaml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend backend
# Catálogo de países (Natural Earth) para la asignación punto-en-polígono.
COPY frontend/public/datos/paises.geojson data/paises.geojson

RUN useradd --system --uid 10001 app && mkdir -p /app/data/raw && chown -R app /app/data
USER app
