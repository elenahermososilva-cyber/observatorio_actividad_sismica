# Evidencias en la pila Docker real (Kafka + PostgreSQL + consumidor + API)

Ejecutadas el 2026-11-18 con los 5 servicios levantados (`docker compose up -d`). Complementan a [`aceptacion-s11.md`](aceptacion-s11.md), que usa PostgreSQL real pero entrega los mensajes al consumidor sin pasar por Kafka.

## Reiniciar consumidor (ENUNCIADO §11, fila 8)

Comando: `python -m unittest tests.integration.test_reconsume_event tests.integration.test_failure_scenarios -v` (desde el equipo anfitrión).

| Prueba | Qué hace | Resultado |
|---|---|---|
| `test_rereading_the_whole_topic_does_not_duplicate_visible_state` | Para el consumidor, lleva los offsets del grupo al principio (`--reset-offsets --to-earliest`), lo arranca y espera lag 0 | OK: `event_current`, `event_message` y versión vigente idénticos antes y después |
| `test_restart_without_reset_reprocesses_nothing` | `docker compose restart consumer` | OK: estado idéntico |
| `test_database_outage_blocks_offset_commit_and_api_reports_error` | Para PostgreSQL, publica un mensaje, comprueba que el consumidor registra `offset NOT committed` y no avanza el offset, que la API responde 503 (no `features: []`) y que al volver la base el estado no se duplica | OK |

Resultado: `Ran 3 tests in 51.7s — OK`.

## Reproducción histórica por Kafka (ENUNCIADO §11, fila 11)

Comando: `docker compose run --rm --no-deps -e PRODUCER_MODE=replay -e REPLAY_INTERVAL_SECONDS=0.2 producer` (selección: M ≥ 5,0 desde 2025-01-01, 10 eventos + 3 casos controlados).

Registro del productor (extracto): 10 mensajes `original` (esperado NEW), `duplicate` us6000pgsd (esperado DUPLICATE), `revision` us6000pgtj M5,0 → M5,2 (esperado REVISION), `stale` us6000pgtj M5,0 (esperado STALE); «reproducción completa».

Estado observado después, consultado por la API y por SQL:

| Consulta | Resultado |
|---|---|
| `GET /api/eventos?mode=replay&start=2020-01-01T00:00:00Z` | `metadata.mode = replay`, `total = 10` |
| `GET /api/eventos?mode=live&start=2020-01-01T00:00:00Z` | `mode = live`, `total = 227` (datos live reales; sin ningún evento de 2025) |
| `GET /api/eventos?mode=demo&start=2020-01-01T00:00:00Z` | `mode = demo`, `total = 1` |
| `replay.event_current` / `replay.event_message` | 10 / 11 (10 originales + la revisión; el duplicado y la versión antigua no se guardan) |
| `replay.quarantine_record` | 0 |
| mensajes de `replay.event_message` con `replay_at` | 11 de 11 |
| `us6000pgtj` en `replay.event_current` | M5,2, versión de la revisión: la versión antigua no la sustituyó |
| `live.event_current` | 227: no cambió por la reproducción |

El tiempo de ocurrencia original se conserva (por ejemplo `2025-01-01 08:09 UTC`) y el momento de la reproducción se guarda aparte en `replay_at`.

## Cerrar y volver a abrir el túnel (filas 9 y 10)

Pendientes de las Fases 11 (panel) y 12 (túnel ngrok). Ver el procedimiento manual en [`aceptacion-s11.md`](aceptacion-s11.md), pruebas P9 y P10.
