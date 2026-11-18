"""Fase 9 contra PostgreSQL real: filtros, paginación, estadísticas y comparación histórica con un escenario sembrado.

Los resultados esperados están calculados A MANO a partir de los datos sembrados (ver `seed`), no copiados de la salida.

    docker compose run --rm --no-deps -v ./tests:/app/tests api \
        python -m unittest discover -s tests/integration -t . -p "test_api_stats_db.py"
"""

import asyncio
import unittest
from datetime import datetime, timezone

try:
    import psycopg
    from fastapi.testclient import TestClient

    from backend.api.app import create_app
    from backend.api.queries import PostgresQueries
    from backend.consumer.consumer import handle_record
    from backend.consumer.geo import CountryIndex
    from backend.db.quarantine import KafkaRef
    from backend.producer.envelope import build_envelope
    from backend.producer.schema import IngestionMode
except ImportError:
    psycopg = None

from tests.integration.dbutil import AVAILABLE, COUNTRIES, TempDatabase

DB = TempDatabase()
GEO = None
H = 3_600_000
DAY = 24 * H
NOW = int(datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
MADRID, MADRID2, PARIS, SEA, SANTIAGO = (-3.7, 40.42), (-3.8, 40.5), (2.35, 48.85), (-30.0, 0.0), (-70.65, -33.45)


def setUpModule() -> None:
    global GEO
    DB.create()
    if AVAILABLE and psycopg is not None:
        GEO = CountryIndex.from_file(COUNTRIES)


def tearDownModule() -> None:
    DB.drop()


def ms(*args) -> int:
    return int(datetime(*args, tzinfo=timezone.utc).timestamp() * 1000)


def feature(event_id, where, time_ms, mag, depth=10.0) -> dict:
    coordinates = [*where] if depth is False else [*where, depth]
    return {
        "type": "Feature", "id": event_id, "geometry": {"type": "Point", "coordinates": coordinates},
        "properties": {"mag": mag, "magType": "mww", "place": "x", "time": time_ms, "updated": time_ms + 1000, "type": "earthquake"},
    }


# Eventos live (ventana por defecto = [NOW-24h, ∞)). L6 queda fuera de la ventana; L5 tiene magnitud nula; L7 no tiene profundidad.
LIVE = [
    feature("L1", MADRID, NOW - 1 * H, 5.0),              # ESP
    feature("L2", MADRID2, NOW - 2 * H, 3.0),             # ESP
    feature("L3", PARIS, NOW - 2 * H - 30 * 60_000, 4.4),  # FRA
    feature("L4", SEA, NOW - 5 * H, 4.0, depth=30.0),      # sin país
    feature("L5", SANTIAGO, NOW - 5 * H, None),            # CHL, magnitud nula
    feature("L6", PARIS, NOW - 30 * H, -0.5),              # FRA, magnitud NEGATIVA, fuera de las 24 h
    feature("L7", MADRID, NOW - 3 * H, 4.5, depth=False),  # ESP, sin profundidad
]
# Histórico 2025 (modo historical → esquema historico).
HIST = [
    feature("H1", SEA, ms(2025, 1, 1, 0, 0), 4.0),           # inicio de año: inclusivo
    feature("H2", MADRID, ms(2025, 3, 10, 10), 5.0),         # ESP
    feature("H3", PARIS, ms(2025, 3, 10, 15), 4.2),          # FRA, mismo día que H2
    feature("H4", SEA, ms(2025, 7, 30, 23), 8.8),
    feature("H5", MADRID, ms(2025, 7, 31, 1), 4.0),          # ESP, día siguiente
    feature("H6", SEA, ms(2025, 12, 31, 23, 59), 4.1),
    feature("H7", MADRID, ms(2025, 5, 5, 12), 3.0),          # ESP, bajo el umbral M≥4
    feature("H8", MADRID, ms(2025, 6, 6, 12), None),         # ESP, magnitud nula
    feature("H9", MADRID, ms(2024, 12, 31, 23, 59), 6.0),    # fuera: 2024
    feature("H10", MADRID, ms(2026, 1, 1, 0, 0), 6.0),       # fuera: el fin de año es exclusivo
]
# Esperado del histórico: M≥4 en 2025 → H1,H2,H3,H4,H5,H6 = 6 eventos en 5 días UTC (1-ene, 10-mar, 30-jul, 31-jul, 31-dic);
# todos los eventos de 2025 = H1..H8 = 8; con país ESP y M≥4: H2,H5 = 2 eventos en 2 días; nulas de 2025: H8.


@unittest.skipIf(not AVAILABLE or psycopg is None, "dependencias del backend no disponibles")
class ApiRealSqlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        DB.truncate_events()
        self.conn = await psycopg.AsyncConnection.connect(DB.conninfo, autocommit=True)
        await self.conn.execute("TRUNCATE ingest.extraction_log RESTART IDENTITY")
        self.offset = 0

    async def asyncTearDown(self) -> None:
        await self.conn.close()

    async def seed(self, live=True, hist=True) -> None:
        for mode, mode_enum, source, items in (
            ("live", IngestionMode.LIVE, "usgs", LIVE if live else []),
            ("historical", IngestionMode.HISTORICAL, "usgs-catalog", HIST if hist else []),
        ):
            for item in items:
                self.offset += 1
                envelope = build_envelope(
                    item, mode=mode_enum, source=source, synthetic_flag=False,
                    ingested_at=datetime.fromtimestamp(NOW / 1000, timezone.utc),
                )
                result = await handle_record(self.conn, envelope.value, KafkaRef(f"t.{mode}", 0, self.offset), mode, GEO)
                assert result.rejection is None, result.rejection

    def call(self, path: str, **params):
        def run():
            app = create_app(PostgresQueries(DB.conninfo), clock=lambda: NOW, default_mode="live", cors_origins=["http://localhost:4200"])
            with TestClient(app) as client:
                response = client.get(path, params=params)
                return response.status_code, response.json()

        return asyncio.to_thread(run)

    async def eventos(self, **params):
        status, body = await self.call("/api/eventos", **params)
        self.assertEqual(status, 200, body)
        return body

    async def stats(self, **params):
        status, body = await self.call("/api/estadisticas", **params)
        self.assertEqual(status, 200, body)
        return body

    @staticmethod
    def ids(body):
        return [f["id"] for f in body["features"]]

    # ============================================================== /api/eventos: min_mag
    async def test_min_mag_excludes_null_and_counts_them_separately(self) -> None:
        await self.seed()
        body = await self.eventos(min_mag="4")
        # Por ocurrencia descendente: L1 (NOW-1h, 5.0), L3 (NOW-2h30, 4.4), L7 (NOW-3h, 4.5), L4 (NOW-5h, 4.0).
        # Fuera: L2 (3.0), L5 (magnitud nula) y L6 (fuera de la ventana de 24 h).
        self.assertEqual(self.ids(body), ["L1", "L3", "L7", "L4"])
        self.assertEqual(body["metadata"]["total"], 4)
        self.assertEqual(body["metadata"]["null_mag_excluded"], 1)  # L5
        self.assertEqual(body["metadata"]["null_mag_count"], 0)

    async def test_without_min_mag_the_null_magnitude_event_is_returned_as_null(self) -> None:
        await self.seed()
        body = await self.eventos()
        self.assertEqual(len(body["features"]), 6)  # L1..L5 y L7 (L6 está fuera de las 24 h)
        self.assertIsNone(next(f for f in body["features"] if f["id"] == "L5")["properties"]["mag"])
        self.assertEqual((body["metadata"]["null_mag_count"], body["metadata"]["null_mag_excluded"]), (1, 0))

    async def test_negative_magnitudes_are_valid_data_and_pass_a_negative_threshold(self) -> None:
        await self.seed()
        body = await self.eventos(start=f"{datetime.fromtimestamp((NOW - 48 * H) / 1000, timezone.utc):%Y-%m-%dT%H:%M:%SZ}", min_mag="-1")
        self.assertIn("L6", self.ids(body))  # mag -0.5 ≥ -1
        self.assertNotIn("L5", self.ids(body))  # la nula nunca cumple, ni siquiera un umbral negativo

    # ============================================================== país
    async def test_country_filters_against_real_dimension(self) -> None:
        await self.seed()
        self.assertEqual(self.ids(await self.eventos(country_id="ESP")), ["L1", "L2", "L7"])
        self.assertEqual(self.ids(await self.eventos(country_id="esp")), ["L1", "L2", "L7"])
        self.assertEqual(self.ids(await self.eventos(country_id="FRA")), ["L3"])  # L6 (FRA) fuera de ventana
        self.assertEqual(self.ids(await self.eventos(country_id="CHL")), ["L5"])

    async def test_none_selects_maritime_events_and_they_remain_in_unfiltered_results(self) -> None:
        await self.seed()
        body = await self.eventos(country_id="none")
        self.assertEqual(self.ids(body), ["L4"])
        self.assertEqual(body["features"][0]["properties"]["country_id"], None)
        self.assertIn("L4", self.ids(await self.eventos()))

    async def test_unknown_country_is_400_but_a_known_country_without_events_is_an_empty_success(self) -> None:
        await self.seed()
        status, body = await self.call("/api/eventos", country_id="ZZZ")
        self.assertEqual((status, body["error"]["code"]), (400, "invalid_parameter"))
        empty = await self.eventos(country_id="JPN")  # existe en el catálogo, no tiene eventos
        self.assertEqual((empty["features"], empty["metadata"]["total"]), ([], 0))

    async def test_country_and_magnitude_combine(self) -> None:
        await self.seed()
        body = await self.eventos(country_id="ESP", min_mag="4.5")
        self.assertEqual(self.ids(body), ["L1", "L7"])  # 5.0 y 4.5 (inclusivo); L2 = 3.0 fuera
        self.assertEqual(body["metadata"]["null_mag_excluded"], 0)  # ninguna nula española
        chile = await self.eventos(country_id="CHL", min_mag="1")
        self.assertEqual((chile["features"], chile["metadata"]["null_mag_excluded"]), ([], 1))

    # ============================================================== paginación
    async def test_pagination_walks_the_real_table_without_gaps_or_repeats(self) -> None:
        await self.seed()
        full = self.ids(await self.eventos())
        seen, offset = [], 0
        while offset is not None:
            body = await self.eventos(limit=2, offset=offset)
            self.assertEqual(body["metadata"]["total"], 6)
            seen += self.ids(body)
            offset = body["metadata"]["next_offset"]
        self.assertEqual(seen, full)
        self.assertEqual(len(set(seen)), 6)
        # orden: ocurrencia descendente; empates por id (L4 y L5 comparten instante)
        self.assertEqual(full, ["L1", "L2", "L3", "L7", "L4", "L5"])

    async def test_truncated_response_reports_the_complete_total(self) -> None:
        await self.seed()
        body = await self.eventos(limit=3)
        meta = body["metadata"]
        self.assertEqual((meta["count"], meta["total"], meta["truncated"], meta["next_offset"]), (3, 6, True, 3))

    # ============================================================== /api/estadisticas
    async def test_totals_missing_values_and_distributions(self) -> None:
        await self.seed()
        body = await self.stats()
        self.assertEqual(body["totals"]["events"], 6)
        self.assertEqual(body["totals"]["missing"], {"magnitude": 1, "depth": 1})  # L5 sin magnitud, L7 sin profundidad
        mag = body["distributions"]["magnitude"]
        self.assertEqual(mag["bins"], [
            {"from": 3.0, "to": 3.5, "count": 1},   # L2
            {"from": 4.0, "to": 4.5, "count": 2},   # L3 (4.4) y L4 (4.0): el borde inferior es inclusivo
            {"from": 4.5, "to": 5.0, "count": 1},   # L7
            {"from": 5.0, "to": 5.5, "count": 1},   # L1
        ])
        self.assertEqual((mag["with_value"], mag["missing"]), (5, {"magnitude": 1}))
        depth = body["distributions"]["depth_km"]
        self.assertEqual(depth["bins"], [{"from": 10.0, "to": 20.0, "count": 4}, {"from": 30.0, "to": 40.0, "count": 1}])
        self.assertEqual((depth["with_value"], depth["missing"]), (5, {"depth": 1}))
        self.assertEqual(sum(b["count"] for b in mag["bins"]), mag["with_value"])  # las distribuciones no pierden eventos

    async def test_hourly_windows_are_fixed_utc_hours_by_event_time_with_explicit_zeros(self) -> None:
        await self.seed()
        hourly = (await self.stats())["hourly"]
        self.assertTrue(hourly["zero_filled"])
        self.assertEqual(len(hourly["series"]), 24)  # [NOW-24h, NOW): 24 horas
        counts = {(NOW - s["hour"]) // H: s["count"] for s in hourly["series"]}
        # L1 en NOW-1h; L2 en NOW-2h; L3 (NOW-2h30) y L7 (NOW-3h) en la hora NOW-3h; L4 y L5 en NOW-5h
        self.assertEqual({h: c for h, c in counts.items() if c}, {1: 1, 2: 1, 3: 2, 5: 2})
        self.assertEqual(sum(counts.values()), 6)
        self.assertEqual(hourly["bucket_ms"], H)
        self.assertTrue(all(s["hour"] % H == 0 for s in hourly["series"]))

    async def test_counts_by_country_include_no_country_explicitly(self) -> None:
        await self.seed()
        groups = (await self.stats())["groups"]
        totals = {t["name"]: t["count"] for t in groups["totals"]}
        self.assertEqual(totals, {"España": 3, "Francia": 1, "Chile": 1, "Sin país asignado": 1})
        self.assertEqual(sum(totals.values()), 6)
        self.assertEqual(groups["totals"][0]["name"], "España")  # ordenado de mayor a menor
        self.assertEqual(sum(c["count"] for c in groups["hourly"]), 6)
        no_country = [c for c in groups["hourly"] if c["key"] is None]
        self.assertEqual([(c["name"], (NOW - c["hour"]) // H) for c in no_country], [("Sin país asignado", 5)])

    async def test_counts_by_subregion(self) -> None:
        await self.seed()
        groups = (await self.stats(group="subregion"))["groups"]
        totals = {t["name"]: t["count"] for t in groups["totals"]}
        self.assertEqual(totals["Sin país asignado"], 1)
        self.assertEqual(sum(totals.values()), 6)
        self.assertEqual(groups["by"], "subregion")
        self.assertEqual(totals["Southern Europe"], 3)  # España; Francia (Western Europe) y Chile (South America) aparte

    async def test_statistics_use_the_same_filters_as_the_map(self) -> None:
        """Para cada combinación de filtros, el total de /estadisticas == el total de /eventos (misma semántica SQL)."""
        await self.seed()
        for params in (
            {}, {"min_mag": "4"}, {"country_id": "ESP"}, {"country_id": "none"}, {"country_id": "ESP", "min_mag": "4.5"},
            {"min_mag": "9"}, {"start": "2026-11-17T09:00:00Z", "end": "2026-11-17T11:00:00Z"}, {"min_mag": "-1"},
        ):
            events = await self.eventos(**params)
            statistics = await self.stats(**params)
            self.assertEqual(statistics["totals"]["events"], events["metadata"]["total"], params)
            self.assertEqual(sum(t["count"] for t in statistics["groups"]["totals"]), events["metadata"]["total"], params)
            self.assertEqual(sum(s["count"] for s in statistics["hourly"]["series"]), events["metadata"]["total"], params)

    async def test_statistics_are_computed_over_everything_even_when_the_map_is_truncated(self) -> None:
        await self.seed()
        events = await self.eventos(limit=2)
        self.assertTrue(events["metadata"]["truncated"])
        statistics = await self.stats()
        self.assertEqual(statistics["totals"]["events"], 6)  # no 2: no se calculan sobre la página truncada

    async def test_revisions_and_duplicates_are_never_counted_twice(self) -> None:
        await self.seed()
        revised = feature("L1", PARIS, NOW - 1 * H, 5.4)  # misma id y ocurrencia, versión posterior, otro país
        revised["properties"]["updated"] += 5000
        self.offset += 1
        envelope = build_envelope(revised, mode=IngestionMode.LIVE, source="usgs", synthetic_flag=False,
                                  ingested_at=datetime.fromtimestamp(NOW / 1000, timezone.utc))
        await handle_record(self.conn, envelope.value, KafkaRef("t.live", 0, self.offset), "live", GEO)
        await handle_record(self.conn, envelope.value, KafkaRef("t.live", 0, self.offset + 1000), "live", GEO)  # duplicado
        statistics = await self.stats()
        self.assertEqual(statistics["totals"]["events"], 6)  # sigue siendo 6, no 7 ni 8
        totals = {t["name"]: t["count"] for t in statistics["groups"]["totals"]}
        self.assertEqual((totals["España"], totals["Francia"]), (2, 2))  # L1 pasó de España a Francia: se recalcula

    async def test_empty_period_is_a_zero_filled_success_not_an_error(self) -> None:
        await self.seed()
        body = await self.stats(start="2020-01-01T00:00:00Z", end="2020-01-01T03:00:00Z")
        self.assertEqual(body["totals"]["events"], 0)
        self.assertEqual([s["count"] for s in body["hourly"]["series"]], [0, 0, 0])
        self.assertEqual(body["distributions"]["magnitude"]["bins"], [])
        self.assertEqual(body["groups"]["totals"], [])

    # ============================================================== comparación histórica
    async def test_comparison_uses_all_365_days_including_empty_ones(self) -> None:
        await self.seed()
        comparison = (await self.stats())["historical_comparison"]
        last = comparison["last_24h"]
        self.assertEqual(last["count"], 4)  # L1 5.0, L3 4.4, L4 4.0, L7 4.5 (L2 = 3.0 y la nula L5 no cumplen M≥4)
        self.assertEqual(last["period"], {"start": NOW - DAY, "end": NOW})
        self.assertEqual(last["missing"], {"null_magnitude_excluded": 1})
        base = comparison["baseline"]
        self.assertTrue(base["available"])
        self.assertEqual((base["year"], base["events"], base["days"]), (2025, 6, 365))  # H1..H6; H9/H10 fuera del año
        self.assertEqual((base["days_with_events"], base["days_without_events"]), (5, 360))
        self.assertAlmostEqual(base["mean_per_day"], 6 / 365)  # 0,01644: NO 6/5, que ignoraría los 360 días con cero eventos
        self.assertAlmostEqual(comparison["ratio_vs_daily_mean"], 4 / (6 / 365))
        self.assertEqual(base["missing"], {"null_magnitude_excluded": 1})  # H8
        self.assertEqual(comparison["filters"], {"min_mag": 4.0, "country_id": None})
        # Distribución diaria sobre los 365 días: 1-ene:1, 10-mar:2, 30-jul:1, 31-jul:1, 31-dic:1 y 360 días con 0
        self.assertEqual((base["median_per_day"], base["min_per_day"], base["max_per_day"]), (0.0, 0, 2))

    async def test_comparison_year_boundaries_are_start_inclusive_end_exclusive(self) -> None:
        await self.seed(live=False)
        base = (await self.stats())["historical_comparison"]["baseline"]
        self.assertEqual(base["events"], 6)  # H1 (1-ene 00:00) cuenta; H10 (1-ene-2026 00:00) y H9 (2024) no

    async def test_comparison_applies_the_same_country_filter_on_both_sides(self) -> None:
        await self.seed()
        comparison = (await self.stats(country_id="ESP"))["historical_comparison"]
        self.assertEqual(comparison["last_24h"]["count"], 2)  # L1 y L7
        self.assertEqual((comparison["baseline"]["events"], comparison["baseline"]["days_with_events"]), (2, 2))  # H2 y H5
        self.assertEqual((comparison["baseline"]["median_per_day"], comparison["baseline"]["max_per_day"]), (0.0, 1))
        self.assertAlmostEqual(comparison["baseline"]["mean_per_day"], 2 / 365)
        self.assertEqual(comparison["filters"]["country_id"], "ESP")
        self.assertEqual(comparison["baseline"]["missing"], {"null_magnitude_excluded": 1})  # H8 es de España

    async def test_comparison_without_country_events_reports_zero_mean_and_null_ratio(self) -> None:
        await self.seed()
        comparison = (await self.stats(country_id="JPN"))["historical_comparison"]
        self.assertEqual((comparison["last_24h"]["count"], comparison["baseline"]["events"]), (0, 0))
        self.assertEqual((comparison["baseline"]["mean_per_day"], comparison["baseline"]["days_without_events"]), (0.0, 365))
        self.assertEqual((comparison["baseline"]["median_per_day"], comparison["baseline"]["min_per_day"], comparison["baseline"]["max_per_day"]), (0.0, 0, 0))
        self.assertIsNone(comparison["ratio_vs_daily_mean"])  # nunca Infinity/NaN

    async def test_comparison_threshold_follows_a_higher_min_mag_on_both_sides(self) -> None:
        await self.seed()
        comparison = (await self.stats(min_mag="5"))["historical_comparison"]
        self.assertEqual(comparison["filters"]["min_mag"], 5.0)
        self.assertEqual(comparison["last_24h"]["count"], 1)  # solo L1 (5.0)
        self.assertEqual(comparison["baseline"]["events"], 2)  # solo H2 (5.0) y H4 (8.8) llegan a M5 en 2025

    async def test_a_lower_min_mag_cannot_go_below_the_history_floor(self) -> None:
        await self.seed()
        comparison = (await self.stats(min_mag="0"))["historical_comparison"]
        self.assertEqual(comparison["filters"]["min_mag"], 4.0)  # el histórico solo contiene M ≥ 4

    async def test_window_follows_end_when_given(self) -> None:
        await self.seed()
        comparison = (await self.stats(start="2026-11-17T00:00:00Z", end="2026-11-17T08:00:00Z"))["historical_comparison"]
        self.assertEqual(comparison["last_24h"]["period"], {"start": NOW - 4 * H - DAY, "end": NOW - 4 * H})
        # Ventana [ayer 08:00, hoy 08:00): L4 (NOW-5h = 07:00, M4.0) cuenta; L5 es de magnitud nula, L6 queda antes de la
        # ventana (NOW-30h) y L1, L2, L3, L7 ocurren después del fin.
        self.assertEqual(comparison["last_24h"]["count"], 1)
        self.assertEqual(comparison["last_24h"]["missing"], {"null_magnitude_excluded": 1})  # L5, también dentro de la ventana

    async def test_missing_history_is_explicit_not_a_zero_mean(self) -> None:
        await self.seed(hist=False)
        comparison = (await self.stats())["historical_comparison"]
        self.assertEqual(comparison["baseline"]["available"], False)
        self.assertEqual(comparison["baseline"]["reason"], "historico_not_loaded")
        self.assertIsNone(comparison["ratio_vs_daily_mean"])
        self.assertEqual(comparison["last_24h"]["count"], 4)  # la parte reciente sigue calculándose

    async def test_baseline_year_parameter(self) -> None:
        await self.seed()
        other = (await self.stats(baseline_year="2024"))["historical_comparison"]["baseline"]
        self.assertEqual((other["year"], other["events"], other["days"]), (2024, 1, 366))  # H9; 2024 es bisiesto
        empty = (await self.stats(baseline_year="2019"))["historical_comparison"]["baseline"]
        self.assertFalse(empty["available"])

    # ============================================================== aislamiento y errores
    async def test_modes_are_isolated_in_statistics(self) -> None:
        await self.seed()
        for mode in ("demo", "replay"):
            body = await self.stats(mode=mode)
            self.assertEqual(body["totals"]["events"], 0, mode)
            self.assertEqual(body["metadata"]["mode"], mode)
        self.assertEqual((await self.stats(mode="live"))["totals"]["events"], 6)

    async def test_history_never_appears_in_the_map(self) -> None:
        await self.seed()
        for mode in ("live", "demo", "replay"):
            body = await self.eventos(mode=mode, start="2025-01-01T00:00:00Z", end="2026-01-01T00:00:00Z")
            self.assertEqual(body["features"], [], mode)

    async def test_unreachable_database_is_503_for_statistics(self) -> None:
        def run():
            app = create_app(PostgresQueries("postgresql://nobody:x@127.0.0.1:1/none", timeout=1.0), clock=lambda: NOW,
                             default_mode="live", cors_origins=["http://localhost:4200"])
            with TestClient(app) as client:
                return client.get("/api/estadisticas"), client.get("/api/eventos", params={"min_mag": "4"})

        stats, eventos = await asyncio.to_thread(run)
        self.assertEqual((stats.status_code, eventos.status_code), (503, 503))
        self.assertNotIn("totals", stats.json())
        self.assertNotIn("features", eventos.json())

    # ============================================================== salud
    async def health(self, **params):
        return await self.call("/api/salud", **params)

    async def insert_query(self, seconds_ago: int, ok: bool = True) -> None:
        await self.conn.execute(
            "INSERT INTO ingest.extraction_log (mode, source_url, started_at, ok, record_count, error) "
            "VALUES ('live', 'u', to_timestamp(%s / 1000.0), %s, %s, %s)",
            (NOW - seconds_ago * 1000, ok, 3 if ok else None, None if ok else "HTTP 503"),
        )

    async def test_health_live_fresh_stale_and_never(self) -> None:
        status, body = await self.health()
        self.assertEqual((status, body["status"], body["stale_reason"]), (200, "stale", "no_successful_query"))
        await self.insert_query(seconds_ago=3600)
        status, body = await self.health()
        self.assertEqual((body["status"], body["stale_reason"], body["seconds_since_last_ingestion"]), ("stale", "last_successful_query_too_old", 3600))
        await self.insert_query(seconds_ago=60)
        status, body = await self.health()
        self.assertEqual((status, body["status"], body["stale"], body["seconds_since_last_ingestion"]), (200, "ok", False, 60))

    async def test_failed_query_does_not_refresh_the_health(self) -> None:
        await self.insert_query(seconds_ago=3600)
        await self.insert_query(seconds_ago=10, ok=False)  # USGS falló hace 10 s: los datos NO están al día
        status, body = await self.health()
        self.assertEqual((body["status"], body["seconds_since_last_ingestion"]), ("stale", 3600))

    async def test_health_for_demo_mode_is_never_stale(self) -> None:
        status, body = await self.health(mode="demo")
        self.assertEqual((status, body["stale"], body["status"]), (200, None, "ok"))


if __name__ == "__main__":
    unittest.main()
