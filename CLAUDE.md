# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

A student project (course assignment) for a seismic-activity observatory: ingest USGS earthquake data through a Kafka pipeline into PostgreSQL, expose it through a FastAPI API, and display it on an Angular/Leaflet map. The course supplied the frontend map and the assignment docs. The students build the backend. Work is driven by **GitHub Spec Kit** (spec → plan → tasks → implement).

All project documents, specs and conversation with the user are in **Spanish**. Keep new docs and spec edits in Spanish.

## Layout (two roots)

- `observatorio-sismico/`: the actual project. **Run all commands from here.** Imports such as `backend.consumer.versioning` resolve relative to this directory.
  - `ENUNCIADO.md` (assignment + rubric), `FAQ-ALUMNADO.md`, `CONTRATO-API.md` (API contract, authoritative), `FUENTES-Y-LICENCIAS.md`, `VALIDACION.md`: supplied by the course. Treat them as requirements, not as files to edit.
  - `frontend/`: supplied Angular 20.3 + ngx-leaflet 20.0 + Leaflet 1.9.4 SPA (pinned versions; do not upgrade).
  - `backend/`: student-built Python backend (in progress).
  - `tests/unit/`: stdlib `unittest` tests.
- `specs/001-vertical-event-demo/`: current Spec Kit feature (spec, plan, data-model, contracts, quickstart, `tasks.md` with `[x]` checkboxes tracking progress).
- `.specify/memory/constitution.md`: project constitution. Its rules are binding (see below).
- `.github/skills/speckit-*`: Spec Kit skills (installed for the Copilot integration).
- `historial.md`: Spanish log of past AI-assistant sessions and decisions.

## Commands

From `observatorio-sismico/`:

```bash
# Unit tests (Python 3.11+; uses StrEnum / typing.Self)
python -m unittest discover -s tests/unit
# Single file / single test
python -m unittest discover -s tests/unit -p test_versioning.py
python -m unittest discover -s tests/unit -k test_same_version_is_duplicate

# Backend stack (once compose.yaml exists; planned at observatorio-sismico/compose.yaml)
docker compose up --build -d
docker compose ps
```

Frontend (from `observatorio-sismico/frontend/`, Node 22.12+ or 24):

```bash
npm ci
npm start        # ng serve → http://localhost:4200
npm run build    # output: dist/observatorio/browser (Netlify base dir: frontend)
```

There is no linter or formatter configured.

## Architecture and binding constraints (from the constitution)

The pipeline has **exactly five Docker Compose services**: Python producer → Kafka → Python consumer → PostgreSQL → FastAPI API. Do not add Spark, Flink, Kubernetes or ML. Angular only presents API results and never acts as the pipeline or the source of truth.

- **Versioning and idempotency**: each event is identified by `event_id` and versioned by the USGS `properties.updated` value (Unix ms). `backend/consumer/versioning.py::classify_version` returns NEW / DUPLICATE / REVISION / STALE. Only a newer version replaces the current row, and stale versions are ignored. Kafka offsets are committed **only after** the PostgreSQL write commits.
- **Storage** (`backend/db/schema.sql` = migration 001, then `backend/db/migrations/`; applied by `python -m backend.db.migrate`):
  - One PostgreSQL schema per mode (`demo`, `live`, `replay`, `historico`) with identical tables; the consumer picks the schema by Kafka topic, the API by `?mode=`. Migrations marked `-- @per-schema` run once per mode schema. Never edit an applied migration; add a new one.
  - `event_message`: every accepted message, unique on `(event_id, updated_ms)`.
  - `event_current`: one row per `event_id`, with denormalized columns (`time_ms`, `mag`, `lon`, `lat`, `country_id`, `country_status`...).
  - `quarantine_record`: durable rejects, with the reason and the original payload or a Kafka offset reference.
  - `ref.dim_country` (Natural Earth attributes) and `ingest.*` (producer state, extraction log).
  - Rejected records, including non-earthquake types, must be quarantined. They must never be silently dropped.
- **Message contract** (`backend/producer/schema.py::EventMessage`): validates `mode` (`demo`/`live`/`replay`), `synthetic_flag` (demo ⇒ synthetic, live ⇒ not synthetic), UTC `ingested_at`, and the GeoJSON Point payload.
- **Time semantics**: keep the four timestamps distinct: occurrence (`time`), source update (`updated`), ingestion and replay. All are in UTC, and the API uses Unix ms.
- **Country attribution**: point-in-polygon against the Natural Earth catalogue (`frontend/public/datos/paises.geojson`). Never derive the country from the `place` text or from proximity. Events outside every country keep an explicit "no country" state (`null`).
- **API** (`CONTRATO-API.md`):
  - `GET /api/eventos` returns a GeoJSON FeatureCollection with `metadata` {generated, last_ingestion, mode, count, truncated}. Filters: `start` (inclusive), `end` (exclusive), `min_mag`, `country_id`. Null magnitude never satisfies `min_mag`. Use `null`, never NaN.
  - `GET /api/salud` and `GET /api/estadisticas` also belong to the contract.
  - A DB failure must return an explicit error, never an empty `features: []` presented as success.
  - Uvicorn listens on `0.0.0.0:8000`.
  - CORS must allow the Netlify origin and `http://localhost:4200`, the GET and OPTIONS methods, and the `ngrok-skip-browser-warning` header.
- **Frontend**:
  - `frontend/public/config.json` switches `mode: "demo"` (static `terremotos-demo.geojson`) or `"api"`. In `api` mode it calls `${apiUrl}/api/eventos`, so `apiUrl` must not end in `/api`.
  - `config.json` is public, so it must never hold secrets. The ngrok authtoken stays out of Git and out of the frontend.

## Current state

Feature `001-vertical-event-demo` is **complete and verified** (all 28 tasks): one synthetic event flows end to end through the five services (`compose.yaml`, producer, consumer with versioning/quarantine, API with `start`/`end` filters, `/api/salud`). Unit, contract, integration and smoke tests pass; see `specs/001-vertical-event-demo/quickstart.md`. Phase 6 (mode schemas, denormalized columns, indexes, `ref.dim_country`, `ingest` state) and Phase 7 (USGS client with retries, live producer, 2025 history download, accelerated replay, `replay_at`) are done and were verified against the real USGS feed. The producer service has three modes via `PRODUCER_MODE` (`demo` default, `live`, `replay`); keep it on `demo` unless actively testing live, because live polls USGS every 60 s. Downloaded originals live in `observatorio-sismico/data/raw/` (git-ignored; see `data/README.md`). Next, in the phased plan agreed with the user: 8 consumer quality + country attribution (point-in-polygon, history loader), 9 full API (min_mag/country filters, stats, pagination, CORS), 10 acceptance tests, 11 panel, 12 deployment, 13 report.

Test commands: unit tests run in the host (`python -m unittest discover -s tests/unit`); contract and DB integration tests run inside the `api` image; smoke and stack integration tests run in the host against a running stack (see quickstart section 4).

## Execution rules for Claude
- Complete the remaining tasks in `specs/001-vertical-event-demo/tasks.md` in dependency order to establish the foundational end-to-end pipeline.
- Consider the vertical demo complete once it passes the project's documented end-to-end verification.
- Then continue implementing the remaining requirements in `ENUNCIADO.md`, `VALIDACION.md` and `CONTRATO-API.md`, while respecting the project constitution and treating supplied course documents as requirements, not files to edit.
- After each implementation task, run the relevant unit tests from `observatorio-sismico/` before moving on.
