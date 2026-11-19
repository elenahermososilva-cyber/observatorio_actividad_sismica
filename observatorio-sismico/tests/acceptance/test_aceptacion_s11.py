"""Fase 10: pruebas de aceptación de ENUNCIADO §11, una por fila de la tabla, contra PostgreSQL real.

Recorrido real: mensaje Kafka (sobre del productor) → consumidor (`handle_record`) → PostgreSQL → API FastAPI
(`/api/eventos` y `/api/estadisticas`, el mismo SQL que usa el panel). Solo Kafka se sustituye por la entrega
directa del valor del mensaje con su referencia (topic, partición, offset).

Cada prueba registra su evidencia (entrada, esperado, observado en la API) y, si existe EVIDENCE_DIR, la escribe en
`aceptacion-s11.json` y `aceptacion-s11.md`.

    docker compose run --rm --no-deps -v ./tests:/app/tests -v ./docs/evidencias:/app/docs/evidencias \
        -e EVIDENCE_DIR=/app/docs/evidencias api \
        python -m unittest discover -s tests/acceptance -t . -v

Las filas «Cerrar el túnel» y «Volver a abrir el túnel» dependen del panel y del túnel; aquí se comprueban solo sus
precondiciones en la API. Su prueba real está en `tests/e2e/panel_published.mjs` (ver `docs/evidencias/panel.md`).
"""

import asyncio
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

try:
    import psycopg
    from fastapi.testclient import TestClient

    from backend.api.app import create_app
    from backend.api.queries import PostgresQueries
    from backend.consumer.consumer import handle_record
    from backend.consumer.geo import CountryIndex
    from backend.consumer.processing import RejectionReason
    from backend.consumer.versioning import VersionDecision
    from backend.db.quarantine import KafkaRef
    from backend.producer.envelope import build_envelope
    from backend.producer.replay import build_plan, select_events
    from backend.producer.schema import IngestionMode
except ImportError:
    psycopg = None

from tests.integration.dbutil import AVAILABLE, COUNTRIES, TempDatabase

DB = TempDatabase()
GEO = None
EVIDENCE: dict[str, dict] = {}
NOW = int(datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
H = 3_600_000
MADRID, SEA = (-3.7, 40.42), (-30.0, 0.0)  # SEA: Atlántico, fuera de todo polígono de país
ORDER = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11"]


def setUpModule() -> None:
    global GEO
    DB.create()
    if AVAILABLE and psycopg is not None:
        GEO = CountryIndex.from_file(COUNTRIES)


def tearDownModule() -> None:
    DB.drop()
    target = os.environ.get("EVIDENCE_DIR")
    if target and EVIDENCE:
        write_evidence(Path(target))


def write_evidence(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    rows = [EVIDENCE[key] for key in ORDER if key in EVIDENCE]
    (folder / "aceptacion-s11.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Evidencias de las pruebas de aceptación (ENUNCIADO §11)",
        "",
        "Generado por `tests/acceptance/test_aceptacion_s11.py` contra PostgreSQL real, el consumidor real y la API real.",
        "Cada fila indica el resultado esperado del enunciado, lo observado y si la prueba pasó.",
        "",
        "| Prueba | Estado | Resultado esperado |",
        "|---|---|---|",
    ]
    for row in rows:
        lines.append(f"| {row['id']} {row['prueba']} | {row['estado']} | {row['esperado']} |")
    for row in rows:
        lines += ["", f"## {row['id']} · {row['prueba']}", "", f"**Estado:** {row['estado']}", "", f"**Esperado:** {row['esperado']}", ""]
        lines += ["**Pasos y observaciones:**", ""]
        lines += [f"- {step}" for step in row["pasos"]]
        if row.get("datos"):
            lines += ["", "```json", json.dumps(row["datos"], indent=2, ensure_ascii=False), "```"]
    (folder / "aceptacion-s11.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def feature(event_id, where=MADRID, time_ms=NOW - H, updated=NOW - H + 1000, mag=4.5, depth=10.0, kind="earthquake") -> dict:
    return {
        "type": "Feature", "id": event_id,
        "geometry": {"type": "Point", "coordinates": [*where, depth]},
        "properties": {"mag": mag, "magType": "mww", "place": "prueba", "time": time_ms, "updated": updated, "type": kind},
    }


@unittest.skipIf(not AVAILABLE or psycopg is None, "dependencias del backend no disponibles")
class AcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        DB.truncate_events()
        self.conn = await psycopg.AsyncConnection.connect(DB.conninfo, autocommit=True)
        self.offset = 0

    async def asyncTearDown(self) -> None:
        await self.conn.close()

    # ------------------------------------------------------------------ utilidades
    async def ingest(self, item, mode="live", topic=None, **envelope_args):
        """Entrega una feature al consumidor real como si viniera de Kafka y devuelve el resultado."""
        self.offset += 1
        mode_enum = {"live": IngestionMode.LIVE, "replay": IngestionMode.REPLAY, "demo": IngestionMode.DEMO}[mode]
        envelope_args.setdefault("source", "usgs" if mode == "live" else "usgs-replay")
        envelope_args.setdefault("synthetic_flag", mode == "demo")
        envelope = build_envelope(
            item, mode=mode_enum, ingested_at=datetime.fromtimestamp(NOW / 1000, timezone.utc), **envelope_args,
        )
        return await handle_record(self.conn, envelope.value, KafkaRef(topic or f"sismos.{mode}", 0, self.offset), mode, GEO)

    def call(self, path, mode="live", **params):
        def run():
            app = create_app(PostgresQueries(DB.conninfo), clock=lambda: NOW, default_mode=mode, cors_origins=["http://localhost:4200"])
            with TestClient(app) as client:
                response = client.get(path, params={"mode": mode, "start": "2026-11-16T00:00:00Z", **params})
                return response.status_code, response.json()

        return asyncio.to_thread(run)

    async def events(self, mode="live", **params):
        status, body = await self.call("/api/eventos", mode, **params)
        self.assertEqual(status, 200, body)
        return body

    async def stats(self, mode="live", **params):
        status, body = await self.call("/api/estadisticas", mode, **params)
        self.assertEqual(status, 200, body)
        return body

    async def scalar(self, sql, *params):
        return (await (await self.conn.execute(sql, params)).fetchone())[0]

    def record(self, key, prueba, esperado, pasos, datos=None, estado="PASA") -> None:
        EVIDENCE[key] = {"id": key, "prueba": prueba, "esperado": esperado, "estado": estado, "pasos": pasos, "datos": datos}

    def compact(self, body) -> list[dict]:
        return [
            {"id": f["id"], "mag": f["properties"]["mag"], "country_id": f["properties"]["country_id"], "updated": f["properties"]["updated"]}
            for f in body["features"]
        ]

    # ------------------------------------------------------------------ P1
    async def test_p01_new_event_is_one_current_row_visible_in_api_and_analysis(self) -> None:
        result = await self.ingest(feature("e1", mag=4.7))
        self.assertEqual(result.decision, VersionDecision.NEW)
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_current"), 1)
        body = await self.events()
        self.assertEqual((body["metadata"]["count"], body["metadata"]["total"]), (1, 1))  # visible en la API y, por tanto, en el mapa
        stats = await self.stats()
        self.assertEqual(stats["totals"]["events"], 1)  # visible en el análisis
        self.assertEqual(sum(h["count"] for h in stats["hourly"]["series"]), 1)
        self.assertEqual(stats["distributions"]["magnitude"]["bins"][0]["count"], 1)
        self.record(
            "P1", "Recibir un evento nuevo", "Una fila actual, visible en API, mapa y análisis",
            ["Se entrega un evento live nuevo (`e1`, M4,7) al consumidor.", "Decisión del consumidor: NEW.",
             "`live.event_current` tiene 1 fila.", "`GET /api/eventos` devuelve 1 evento (el mapa lee este endpoint).",
             "`GET /api/estadisticas` cuenta 1 evento en totales, serie horaria y distribución de magnitud."],
            {"api_eventos": self.compact(body), "totals": stats["totals"]},
        )

    # ------------------------------------------------------------------ P2
    async def test_p02_same_version_again_does_not_increase_the_count(self) -> None:
        await self.ingest(feature("e1"))
        before = (await self.events())["metadata"]["total"], (await self.stats())["totals"]["events"]
        results = [await self.ingest(feature("e1")) for _ in range(3)]
        self.assertTrue(all(r.decision == VersionDecision.DUPLICATE for r in results))
        after = (await self.events())["metadata"]["total"], (await self.stats())["totals"]["events"]
        self.assertEqual(before, after)
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_current"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_message"), 1)  # ni siquiera se guarda dos veces
        self.record(
            "P2", "Reenviar la misma versión", "No aumenta el número de terremotos",
            ["Se entrega `e1` y después la misma versión 3 veces más.", "Las 3 decisiones son DUPLICATE.",
             f"Total en la API y en estadísticas antes/después: {before} / {after}.", "`event_message` conserva 1 sola fila."],
            {"antes": before, "despues": after},
        )

    # ------------------------------------------------------------------ P3
    async def test_p03_later_version_changes_current_data_and_the_affected_aggregations(self) -> None:
        await self.ingest(feature("e1", mag=4.1, updated=NOW - H + 1000))
        before_stats = await self.stats()
        before_api = await self.events()
        result = await self.ingest(feature("e1", mag=6.3, updated=NOW - H + 90_000))
        self.assertEqual(result.decision, VersionDecision.REVISION)
        api = await self.events()
        self.assertEqual((api["metadata"]["total"], api["features"][0]["properties"]["mag"]), (1, 6.3))  # sigue siendo 1 terremoto
        stats = await self.stats()
        bins_before = {b["from"]: b["count"] for b in before_stats["distributions"]["magnitude"]["bins"]}
        bins_after = {b["from"]: b["count"] for b in stats["distributions"]["magnitude"]["bins"]}
        self.assertEqual(bins_before, {4.0: 1})
        self.assertEqual(bins_after, {6.0: 1})  # la agregación afectada cambia de intervalo
        self.assertEqual(stats["totals"]["events"], 1)  # y el recuento total no se duplica
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_message"), 2)  # el historial conserva ambas
        self.assertEqual((await self.stats(min_mag=6))["totals"]["events"], 1)  # ahora cumple el filtro de M6
        self.record(
            "P3", "Recibir una versión posterior", "Cambian los datos actuales y las agregaciones afectadas",
            ["Se entrega `e1` M4,1 (updated t) y después la revisión M6,3 (updated t+89 s).", "Decisión: REVISION.",
             "La API pasa de M4,1 a M6,3 sin duplicar el evento (total 1).",
             "El histograma de magnitud pasa del intervalo [4,0-4,5) al [6,0-6,5).",
             "`event_message` guarda las 2 versiones; `event_current` solo la última."],
            {"antes": self.compact(before_api), "despues": self.compact(api), "histograma_antes": bins_before, "histograma_despues": bins_after},
        )

    # ------------------------------------------------------------------ P4
    async def test_p04_older_version_does_not_replace_the_latest(self) -> None:
        await self.ingest(feature("e1", mag=6.3, updated=NOW - H + 90_000))
        result = await self.ingest(feature("e1", mag=4.1, updated=NOW - H + 1000))  # llega tarde una versión anterior
        self.assertEqual(result.decision, VersionDecision.STALE)
        api = await self.events()
        self.assertEqual((api["features"][0]["properties"]["mag"], api["features"][0]["properties"]["updated"]), (6.3, NOW - H + 90_000))
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_current"), 1)
        self.record(
            "P4", "Recibir después una versión antigua", "No sustituye a la más reciente",
            ["Se entrega `e1` M6,3 (updated t+89 s) y después una versión anterior M4,1 (updated t+1 s).", "Decisión: STALE.",
             "La API sigue mostrando M6,3 con `updated` = t+89 s."],
            {"api": self.compact(api)},
        )

    # ------------------------------------------------------------------ P5
    async def test_p05_null_magnitude_is_kept_and_displayed_as_nd(self) -> None:
        result = await self.ingest(feature("nul", mag=None))
        self.assertIsNone(result.rejection)
        self.assertIsNone(await self.scalar("SELECT mag FROM live.event_current WHERE event_id = 'nul'"))  # se conserva NULL, nunca 0
        api = await self.events()
        self.assertIsNone(api["features"][0]["properties"]["mag"])  # null en JSON: el panel lo muestra como ND
        self.assertNotIn("NaN", json.dumps(api))
        self.assertEqual(api["metadata"]["null_mag_count"], 1)
        filtered = await self.events(min_mag=0)
        self.assertEqual((filtered["metadata"]["total"], filtered["metadata"]["null_mag_excluded"]), (0, 1))  # nunca cumple min_mag
        stats = await self.stats()
        self.assertEqual(stats["totals"]["events"], 1)  # permanece en el análisis
        self.assertEqual(stats["totals"]["missing"]["magnitude"], 1)
        self.assertEqual(stats["distributions"]["magnitude"]["missing"], {"magnitude": 1})
        self.record(
            "P5", "Magnitud nula", "Se conserva con tratamiento documentado y se visualiza como ND",
            ["Se entrega `nul` con `mag: null`.", "Se guarda NULL (no 0) y se acepta: no va a cuarentena.",
             "La API devuelve `mag: null` (sin NaN) y `metadata.null_mag_count = 1`; el panel lo pinta como ND.",
             "Con `min_mag=0` queda fuera y se cuenta en `null_mag_excluded = 1`.",
             "Las estadísticas lo cuentan como evento y lo declaran en `missing.magnitude`, sin entrar en el histograma."],
            {"api": self.compact(api), "con_min_mag_0": filtered["metadata"], "totals": stats["totals"]},
        )

    # ------------------------------------------------------------------ P6
    async def test_p06_invalid_coordinates_go_to_quarantine_with_reason_and_no_point(self) -> None:
        bad_lat = await self.ingest(feature("bad1", where=(10.0, 95.0)))
        bad_lon = await self.ingest(feature("bad2", where=(200.0, 10.0)))
        for result in (bad_lat, bad_lon):
            self.assertEqual(result.rejection.reason, RejectionReason.INVALID_COORDINATES)
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_current"), 0)
        rows = await (await self.conn.execute(
            "SELECT event_id, reason, kafka_topic, kafka_offset, length(original_payload) FROM live.quarantine_record ORDER BY quarantine_id"
        )).fetchall()
        self.assertEqual([r[0] for r in rows], ["bad1", "bad2"])
        self.assertTrue(all(r[1] and r[4] > 0 for r in rows))  # motivo y payload original conservados
        api = await self.events()
        self.assertEqual((api["features"], api["metadata"]["total"]), ([], 0))  # ningún punto inventado
        self.assertEqual((await self.stats())["totals"]["events"], 0)
        self.record(
            "P6", "Coordenadas inválidas", "Cuarentena y motivo; no aparecen puntos inventados",
            ["Se entregan `bad1` (latitud 95) y `bad2` (longitud 200).", "Ambos rechazados con motivo `invalid_coordinates`.",
             "`quarantine_record` guarda 2 filas con motivo, payload original y referencia Kafka.",
             "`event_current` queda vacía y la API devuelve 0 eventos: no se corrige ni se coloca ningún punto."],
            {"cuarentena": [{"event_id": r[0], "motivo": r[1], "topic": r[2], "offset": r[3]} for r in rows]},
        )

    # ------------------------------------------------------------------ P7
    async def test_p07_maritime_event_has_no_country_and_stays_in_the_analysis(self) -> None:
        await self.ingest(feature("mar", where=SEA, mag=4.6))
        await self.ingest(feature("tierra", where=MADRID, mag=4.2))
        api = await self.events()
        by_id = {f["id"]: f["properties"] for f in api["features"]}
        self.assertIsNone(by_id["mar"]["country_id"])
        self.assertEqual(by_id["tierra"]["country_id"], "ESP")
        self.assertEqual(await self.scalar("SELECT country_status FROM live.event_current WHERE event_id = 'mar'"), "unassigned")
        stats = await self.stats()
        self.assertEqual(stats["totals"]["events"], 2)  # el marítimo permanece en el análisis
        groups = {g["key"]: g["count"] for g in stats["groups"]["totals"]}
        self.assertEqual(groups, {"ESP": 1, None: 1})  # «Sin país asignado» es un grupo propio
        sin_pais = await self.events(country_id="none")
        self.assertEqual([f["id"] for f in sin_pais["features"]], ["mar"])
        self.record(
            "P7", "Evento marítimo", "Sin país asignado; permanece en el análisis",
            ["Se entregan `mar` (Atlántico, 30°W 0°N) y `tierra` (Madrid).", "`mar` queda con `country_id: null` y estado `unassigned`; `tierra` es ESP.",
             "Las estadísticas cuentan los 2 eventos y muestran «Sin país asignado» como grupo propio.",
             "`country_id=none` devuelve solo `mar`."],
            {"api": self.compact(api), "grupos": stats["groups"]["totals"]},
        )

    # ------------------------------------------------------------------ P8
    async def test_p08_consumer_restart_replays_without_duplicating_persisted_effects(self) -> None:
        stream = [feature("a", mag=4.0), feature("b", mag=5.0), feature("a", mag=4.4, updated=NOW + 5000), feature("c", where=SEA, mag=None)]
        first = [(await self.ingest(item)).decision for item in stream]
        snapshot_before = await self.snapshot()
        # Reinicio: el consumidor no confirmó nada y Kafka vuelve a entregar TODO desde el offset 0 (como `--reset-offsets --to-earliest`)
        self.offset = 0
        second = [(await self.ingest(item)).decision for item in stream]
        self.assertEqual(first, [VersionDecision.NEW, VersionDecision.NEW, VersionDecision.REVISION, VersionDecision.NEW])
        self.assertTrue(all(d in (VersionDecision.DUPLICATE, VersionDecision.STALE) for d in second), second)  # nada es NEW ni REVISION
        self.assertEqual(await self.snapshot(), snapshot_before)
        total = (await self.events())["metadata"]["total"]
        self.assertEqual(total, 3)
        self.record(
            "P8", "Reiniciar consumidor", "Reanuda sin duplicar los efectos ya persistidos",
            ["Se procesan 4 mensajes (3 eventos, uno con revisión) y se guarda el estado.",
             "Se simula el reinicio con relectura completa desde el offset 0 (el consumidor no había confirmado).",
             f"Decisiones en la relectura: {[d.value for d in second]}: ningún efecto nuevo.",
             "Filas de `event_current`, `event_message`, cuarentena y versiones vigentes: idénticas antes y después.",
             "En la pila Docker real lo cubren `tests/integration/test_reconsume_event.py` (reset de offsets a earliest y `docker compose restart consumer`) y `test_failure_scenarios.py` (caída de PostgreSQL sin confirmar offsets)."],
            {"estado": snapshot_before, "decisiones_relectura": [d.value for d in second]},
        )

    async def snapshot(self) -> dict:
        return {
            "event_current": await self.scalar("SELECT count(*) FROM live.event_current"),
            "event_message": await self.scalar("SELECT count(*) FROM live.event_message"),
            "quarantine": await self.scalar("SELECT count(*) FROM live.quarantine_record"),
            "versiones": [list(r) for r in await (await self.conn.execute(
                "SELECT event_id, current_version_ms, mag FROM live.event_current ORDER BY event_id")).fetchall()],
        }

    # ------------------------------------------------------------------ P9 y P10 (túnel): precondiciones en la API
    async def test_p09_p10_tunnel_preconditions_are_exposed_by_the_api(self) -> None:
        await self.ingest(feature("e1"))
        body = await self.events()
        self.assertIsNotNone(body["metadata"]["generated"])  # el panel conserva e identifica la última lectura con estos campos
        status, salud = await self.call("/api/salud")
        self.assertEqual(status, 200)
        self.assertIn("status", salud)
        self.record(
            "P9", "Cerrar el túnel", "El panel muestra el fallo y conserva/identifica la última lectura",
            ["Precondición verificada aquí en la API: cada respuesta lleva `metadata.generated` y `last_ingestion`, que el panel usa para identificar la última lectura buena.",
             "Comprobado en el panel real (Edge, `tests/e2e/panel_e2e.mjs`, ver `panel-e2e.json`): con el servicio `api` parado el panel muestra el aviso «No se pudo actualizar», conserva los eventos de la última lectura, indica cuándo fue y marca la API como «Sin respuesta».",
             "Comprobado también con el túnel ngrok real y el panel publicado en Netlify (`panel-publicado-watch.json`, 18-nov-2026): al cerrar ngrok el panel mostró el aviso en ~60 s, con estado «Sin respuesta», y conservó 185 eventos idénticos hasta el final del fallo."],
            {"metadata": body["metadata"]}, estado="PASA (panel publicado + túnel ngrok real)",
        )
        self.record(
            "P10", "Volver a abrir el túnel", "Se recuperan las consultas automáticamente",
            ["Comprobado en el panel real (`panel-e2e.json`): al arrancar de nuevo el servicio `api`, el aviso desaparece solo en el siguiente refresco, sin recargar la página, y el estado vuelve a «Accesible» o «Datos desactualizados» según `/api/salud`.",
             "Las lecturas de la API no tienen estado de sesión, de modo que la siguiente consulta recupera el estado completo.",
             "Comprobado con el túnel ngrok real (`panel-publicado-watch.json`): al reabrir `ngrok http --url=<dominio-fijo> 8000` el panel publicado se recuperó solo, sin recargar la página, 183 s después del primer aviso (el tiempo depende de cuánto estuvo cerrado el túnel y del refresco de 60 s). Con el dominio fijo no hizo falta cambiar `config.json` ni volver a publicar."],
            estado="PASA (panel publicado + túnel ngrok real)",
        )

    # ------------------------------------------------------------------ P11
    async def test_p11_historical_replay_goes_through_kafka_path_without_mixing_with_live(self) -> None:
        live_event = feature("live1", mag=4.9, time_ms=NOW - 2 * H)
        await self.ingest(live_event)
        history = select_events(
            [feature(f"h{i}", time_ms=1_735_689_600_000 + i * H, updated=1_736_000_000_000 + i, mag=5.0 + i / 10) for i in range(6)],
            start_ms=0, min_mag=5.0, count=3,
        )
        plan = build_plan(history)
        replay_at = datetime(2026, 11, 17, 15, 30, tzinfo=timezone.utc)
        decisions = []
        for item in plan:
            decisions.append((await self.ingest(
                item.feature, mode="replay", topic="sismos.replay", replay_at=replay_at,
                source=item.source, synthetic_flag=item.synthetic_flag,
            )).decision.value.upper())
        self.assertEqual(decisions, ["NEW", "NEW", "NEW", "DUPLICATE", "REVISION", "STALE"])  # incluye los casos controlados
        replay = await self.events(mode="replay", start="2020-01-01T00:00:00Z")
        live = await self.events(mode="live")
        self.assertEqual(replay["metadata"]["mode"], "replay")
        self.assertEqual({f["id"] for f in replay["features"]}, {"h0", "h1", "h2"})
        self.assertEqual({f["id"] for f in live["features"]}, {"live1"})  # el live no contiene nada de la reproducción
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_current"), 1)
        # tiempo original intacto + tiempo de reproducción aparte
        times = await (await self.conn.execute(
            "SELECT c.time_ms, m.replay_at FROM replay.event_current c JOIN replay.event_message m USING (message_id) ORDER BY c.time_ms LIMIT 1"
        )).fetchone()
        self.assertEqual(times[0], history[0]["properties"]["time"])
        self.assertEqual(times[1], replay_at)
        # un mensaje de replay en el topic live se rechaza, no se mezcla
        mixed_result = await handle_record(
            self.conn, build_envelope(history[0], mode=IngestionMode.REPLAY, source="usgs-replay", synthetic_flag=False,
                                      ingested_at=replay_at, replay_at=replay_at).value, KafkaRef("sismos.live", 0, 999), "live", GEO)
        self.assertEqual(mixed_result.rejection.reason, RejectionReason.MODE_MISMATCH)
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_current"), 1)
        self.record(
            "P11", "Reproducción histórica", "Procesa por Kafka sin mezclarla con datos live",
            ["Un evento live (`live1`) está en `live`.", "Se reproducen 3 eventos históricos (topic `sismos.replay`) más los casos controlados duplicado, revisión y antigua.",
             f"Decisiones del consumidor: {decisions}.", "`/api/eventos?mode=replay` devuelve solo h0, h1, h2; `/api/eventos?mode=live` solo `live1`.",
             "El tiempo de ocurrencia original se conserva y `replay_at` se guarda aparte.",
             "Un mensaje de replay entregado al consumidor live se rechaza con `mode_mismatch` y va a cuarentena: nunca se mezcla.",
             "La API devuelve `metadata.mode = replay` y el panel muestra el aviso «REPRODUCCIÓN» (`panel-replay.png`)."],
            {"decisiones": decisions, "replay": self.compact(replay), "live": self.compact(live)},
        )

    # ------------------------------------------------------------------ aislamiento replay <-> live (más allá de la fila P11)
    async def test_isolation_same_event_id_in_live_and_replay_never_interacts(self) -> None:
        replay_at = datetime(2026, 11, 17, 15, 30, tzinfo=timezone.utc)
        await self.ingest(feature("same", mag=4.0, updated=NOW - H))
        # el replay recibe el MISMO event_id con una versión posterior y otra magnitud: no puede tocar el live
        await self.ingest(feature("same", mag=7.7, updated=NOW + H), mode="replay", topic="sismos.replay", replay_at=replay_at)
        live = await self.events(mode="live")
        replay = await self.events(mode="replay")
        self.assertEqual([f["properties"]["mag"] for f in live["features"]], [4.0])
        self.assertEqual([f["properties"]["mag"] for f in replay["features"]], [7.7])
        self.assertEqual((await self.stats(mode="live"))["totals"]["events"], 1)
        self.assertEqual((await self.stats(mode="replay", start="2026-11-16T00:00:00Z"))["totals"]["events"], 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM live.event_message"), 1)
        self.assertEqual(await self.scalar("SELECT count(*) FROM replay.event_message"), 1)

    async def test_isolation_replay_does_not_move_live_freshness_nor_last_ingestion(self) -> None:
        await self.conn.execute("TRUNCATE ingest.extraction_log RESTART IDENTITY")
        await self.ingest(feature("r1", mag=5.0), mode="replay", topic="sismos.replay", replay_at=datetime(2026, 11, 17, 15, 30, tzinfo=timezone.utc))
        status, salud = await self.call("/api/salud", mode="live")
        self.assertEqual(status, 200)
        self.assertIsNone(salud["last_ingestion"])  # live no ha consultado a USGS: la reproducción no cuenta como lectura live
        self.assertIs(salud["stale"], True)

    async def test_isolation_database_rejects_a_foreign_mode_even_with_direct_sql(self) -> None:
        for schema, mode, extra_cols, extra_vals in (
            ("live", "replay", ", replay_at", ", now()"), ("replay", "live", "", ""), ("demo", "live", "", ""), ("historico", "live", "", ""),
        ):
            with self.assertRaises(psycopg.errors.CheckViolation, msg=f"{schema} admitió modo {mode}"):
                await self.conn.execute(
                    f"INSERT INTO {schema}.event_message (event_id, updated_ms, source, mode, ingested_at, synthetic_flag, payload{extra_cols}) "
                    f"VALUES ('x', 1, 's', '{mode}', now(), false, '{{}}'{extra_vals})"
                )


if __name__ == "__main__":
    unittest.main()
