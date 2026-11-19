# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

A student project (course assignment) for a seismic-activity observatory: ingest USGS earthquake data through a Kafka pipeline into PostgreSQL, expose it through a FastAPI API, and display it on an Angular/Leaflet map. The course supplied the frontend map and the assignment docs. The students build the backend. Work is driven by **GitHub Spec Kit** (spec → plan → tasks → implement).

All project documents, specs and conversation with the user are in **Spanish**. Keep new docs and spec edits in Spanish.

## Layout (two roots)

- `observatorio-sismico/`: the actual project. **Run all commands from here.** Imports such as `backend.consumer.versioning` resolve relative to this directory.
  - `docs/curso/` (index in `docs/curso/README.md`; the course README is `README-curso.md`):
    `docs/curso/ENUNCIADO.md` (assignment + rubric), `docs/curso/FAQ-ALUMNADO.md`, `docs/curso/CONTRATO-API.md` (API contract, authoritative), `docs/curso/FUENTES-Y-LICENCIAS.md`, `docs/curso/VALIDACION.md`: supplied by the course. Treat them as requirements, not as files to edit.
  - `frontend/`: supplied Angular 20.3 + ngx-leaflet 20.0 + Leaflet 1.9.4 SPA (pinned versions; do not upgrade).
  - `backend/`: student-built Python backend (in progress).
  - `tests/unit/`: stdlib `unittest` tests.
- `specs/001-vertical-event-demo/`: current Spec Kit feature (spec, plan, data-model, contracts, quickstart, `tasks.md` with `[x]` checkboxes tracking progress).
- `.specify/memory/constitution.md`: project constitution. Its rules are binding (see below).
- `.github/skills/speckit-*`: Spec Kit skills (installed for the Copilot integration).

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
- **API** (`docs/curso/CONTRATO-API.md`):
  - `GET /api/eventos` returns a GeoJSON FeatureCollection with `metadata` {generated, last_ingestion, mode, count, truncated}. Filters: `start` (inclusive), `end` (exclusive), `min_mag`, `country_id`. Null magnitude never satisfies `min_mag`. Use `null`, never NaN.
  - `GET /api/salud` and `GET /api/estadisticas` also belong to the contract.
  - A DB failure must return an explicit error, never an empty `features: []` presented as success.
  - Uvicorn listens on `0.0.0.0:8000`.
  - CORS must allow the Netlify origin and `http://localhost:4200`, the GET and OPTIONS methods, and the `ngrok-skip-browser-warning` header.
- **Frontend**:
  - `frontend/public/config.json` switches `mode: "demo"` (static `terremotos-demo.geojson`) or `"api"`. In `api` mode it calls `${apiUrl}/api/eventos`, so `apiUrl` must not end in `/api`.
  - `config.json` is public, so it must never hold secrets. The ngrok authtoken stays out of Git and out of the frontend.

## Current state

Feature `001-vertical-event-demo` is **complete and verified** (all 28 tasks): one synthetic event flows end to end through the five services (`compose.yaml`, producer, consumer with versioning/quarantine, API with `start`/`end` filters, `/api/salud`). Unit, contract, integration and smoke tests pass; see `specs/001-vertical-event-demo/quickstart.md`. Phase 6 (mode schemas, denormalized columns, indexes, `ref.dim_country`, `ingest` state), Phase 7 (USGS client with retries, live producer, 2025 history download, accelerated replay, `replay_at`) and Phase 8 (country attribution by point-in-polygon in `backend/consumer/geo.py`, quality rules in `quality.py` stored as `event_current.quality_flags`, `history_loader` into the `historico` schema, DB-enforced mode isolation) are done and were verified against the real USGS feed and the real 2025 history (18,302 events). Rules and measured results: `observatorio-sismico/docs/reglas-calidad-y-geografia.md`. The producer service has three modes via `PRODUCER_MODE` (`demo` default, `live`, `replay`); keep it on `demo` unless actively testing live, because live polls USGS every 60 s. Downloaded originals live in `observatorio-sismico/data/raw/` (git-ignored; see `data/README.md`). Phase 9 (full API) is done and verified against real data: `min_mag`/`country_id` filters (`country_id=none` = no country; null magnitude never satisfies `min_mag` and is counted in `metadata.null_mag_excluded`), `limit`/`offset` pagination, `GET /api/estadisticas` (hourly UTC windows by country/subregion, distributions, comparison against the 2025 history incl. median/min/max per day), `GET /api/salud` with `stale` for live, and CORS from the `CORS_ORIGINS` env var (exact origins only, currently `http://localhost:4200`; add the Netlify origin there when known and run `docker compose up -d --force-recreate api`). Reference: `specs/001-vertical-event-demo/contracts/api-eventos.md`. Phase 10 (acceptance tests) is done: `tests/acceptance/test_aceptacion_s11.py` has one test per row of ENUNCIADO §11 plus replay↔live isolation tests (run in the `api` image against a temp PostgreSQL; with `EVIDENCE_DIR` set it writes `docs/evidencias/aceptacion-s11.{json,md}`), and `docs/evidencias/pila-real.md` records the real-stack runs (consumer restart, DB outage, replay through Kafka). Rows 9-10 (close/reopen the tunnel) are marked PENDING until the panel (11) and ngrok (12) exist. Phase 11 (panel) is done: `frontend/src/app/` has `api.ts` (fetch, shared filter→query params), `app.component` (state, refresh every 60 s, banners), `event-map`, `bar-chart` (hand-made SVG, no chart libs), `event-table`. Filters (period, min magnitude, country incl. «Sin país asignado») apply identically to `/api/eventos` and `/api/estadisticas`; the panel keeps the last good reading and shows a banner if the API fails; REPRODUCCIÓN/DEMO/stale banners. `config.json` now has `mode: api`, `apiUrl: http://localhost:8000`, `dataMode` (live|demo|replay, also `?mode=`); filters can be preset via URL (`range`, `from`, `to`, `min_mag`, `country`). Browser test: `tests/e2e/panel_e2e.mjs`; evidence in `docs/evidencias/panel.md`. Phase 12 (deployment) is done: panel published on Netlify (`https://observatorio-sismico-elena.netlify.app`, deployed with `npx netlify-cli deploy --prod --dir=dist/observatorio/browser --site <SITE_ID>`, production visibility Public), API exposed through ngrok with the account's fixed free domain (`ngrok http --url=onset-deepen-situation.ngrok-free.dev 8000`; authtoken stays in the user profile, never in Git), `CORS_ORIGINS` in the local `.env` includes the Netlify origin, `PRODUCER_MODE=live`/`API_DEFAULT_MODE=live`. Procedure, checklist and failure table: `observatorio-sismico/docs/despliegue.md`; evidence of the real-tunnel close/reopen test: `docs/evidencias/panel.md`. Phase 13 (report) is done: `observatorio-sismico/docs/memoria.md` (extraction, quality before/after in 6 dimensions, model, 3 conclusions + 1 cautionary result, complexity with 3+ sizes, costs, limitations), `docs/diccionario-de-datos.md`, `docs/consultas-y-procedencia.md` (generated by `scripts/procedencia.py`), `docs/guion-video.md`. All numbers come from reproducible scripts: `scripts/memoria_datos.py` (analysis/quality/timeliness → `docs/evidencias/memoria-datos.json`; live figures are a snapshot, rerun before recording), `scripts/medir_complejidad.py` (synthetic data in a temp DB, run with `-e PYTHONPATH=/app`), `scripts/medir_api.py`. Conclusion 4 of the memoria (recent equivalent comparison) comes from `scripts/comparacion_reciente.py` (FDSN download of 2026-10-01..2026-11-18 into `data/raw/reciente/`, not loaded into the DB; compares against same-length 2025 windows; `RECIENTE_SNAPSHOT=reciente-2` takes a second snapshot to measure catalogue completion) → `docs/evidencias/comparacion-reciente.json`. Panel redesign (after Phase 13): tabs (Resumen, Análisis, Eventos, Histórico 2025, Estado) mirrored in the URL hash, event detail view (`event-detail.component.ts`, opened from table rows, map popups and the magnitude–depth scatter `scatter-chart.component.ts`), hover tooltips on the hand-made SVG charts, and a server-paginated «Histórico 2025» tab backed by the read-only API mode `historico` (`READ_MODES` in `backend/db/modes.py`; never a Kafka/default mode). Browser test: `tests/e2e/panel_secciones.mjs` (21 checks, screenshots in `docs/evidencias/secciones/`). Visual quality report: `docs/analisis-calidad.md`, generated by `scripts/graficos_calidad.py` with matplotlib installed only in an ephemeral `api` container (`pip install --target /tmp/mpl`; the image runs as non-root). Remaining work is the user's: re-run the data script with more live days, the individual explanation and the video.

Test commands: unit tests run in the host (`python -m unittest discover -s tests/unit`); contract and DB integration tests run inside the `api` image; smoke and stack integration tests run in the host against a running stack (see quickstart section 4).

## Execution rules for Claude
- Complete the remaining tasks in `specs/001-vertical-event-demo/tasks.md` in dependency order to establish the foundational end-to-end pipeline.
- Consider the vertical demo complete once it passes the project's documented end-to-end verification.
- Then continue implementing the remaining requirements in `docs/curso/ENUNCIADO.md`, `docs/curso/VALIDACION.md` and `docs/curso/CONTRATO-API.md`, while respecting the project constitution and treating supplied course documents as requirements, not files to edit.
- After each implementation task, run the relevant unit tests from `observatorio-sismico/` before moving on.
