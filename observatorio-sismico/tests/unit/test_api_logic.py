"""Lógica pura de la Fase 9: parámetros, CORS, estadísticas y frescura. Sin red ni base de datos; corre en el host."""

import json
import unittest

from backend.api.cors import CorsConfigError, parse_origins
from backend.api.exceptions import InvalidParameter
from backend.api.params import (
    DEFAULT_WINDOW_MS, NO_COUNTRY, EventFilters, build_filters, parse_country_id, parse_min_mag, parse_page,
)
from backend.api.stats import (
    DAY_MS, HOUR_MS, NO_COUNTRY_LABEL, PENDING_LABEL, ZERO_FILL_MAX_HOURS, BaselineData, GroupRow, StatsData,
    aggregate_groups, assess_freshness, build_comparison, build_statistics, days_in_year, fill_hours, floor_hour,
    histogram, year_bounds_ms,
)

NOW = 1_793_200_000_000  # 2026-10-28T14:26:40Z aprox.


# ------------------------------------------------------------------------------------------ parámetros
class MinMagTests(unittest.TestCase):
    def test_valid_values(self) -> None:
        self.assertEqual(parse_min_mag("4.5"), 4.5)
        self.assertEqual(parse_min_mag("-1"), -1.0)  # una magnitud negativa es un umbral legítimo
        self.assertEqual(parse_min_mag("0"), 0.0)  # cero NO es «sin filtro»
        self.assertIsNone(parse_min_mag(None))
        self.assertIsNone(parse_min_mag("  "))

    def test_non_finite_and_garbage_are_rejected(self) -> None:
        for bad in ("nan", "NaN", "inf", "-inf", "Infinity", "abc", "4,5", "4.5.1", "11", "-11", "1e3"):
            with self.assertRaises(InvalidParameter, msg=bad):
                parse_min_mag(bad)


class CountryTests(unittest.TestCase):
    def test_normalizes_case_and_whitespace(self) -> None:
        self.assertEqual(parse_country_id(" esp "), "ESP")
        self.assertIsNone(parse_country_id(None))
        self.assertIsNone(parse_country_id(""))

    def test_none_means_no_country_in_any_case(self) -> None:
        for value in ("none", "NONE", " None "):
            self.assertEqual(parse_country_id(value), NO_COUNTRY)

    def test_malformed_values_never_reach_sql(self) -> None:
        for bad in ("E", "ESPANA", "ES P", "españa", "ES'; DROP TABLE x;--", "ES%", "../etc"):
            with self.assertRaises(InvalidParameter, msg=bad):
                parse_country_id(bad)


class FilterTests(unittest.TestCase):
    def test_default_window_is_the_last_24_hours(self) -> None:
        filters = build_filters(None, None, None, None, NOW)
        self.assertEqual((filters.start_ms, filters.end_ms), (NOW - DEFAULT_WINDOW_MS, None))
        self.assertEqual(filters.describe(), {"min_mag": None, "country_id": None})

    def test_all_filters_together(self) -> None:
        filters = build_filters("2026-10-27", "2026-10-28T00:00:00Z", "4", "chl", NOW)
        self.assertEqual(
            (filters.start_ms, filters.end_ms, filters.min_mag, filters.country_id),
            (1_793_059_200_000, 1_793_145_600_000, 4.0, "CHL"),
        )

    def test_start_must_precede_end(self) -> None:
        for args in (("2026-10-28", "2026-10-27"), ("2026-10-28", "2026-10-28")):
            with self.assertRaises(InvalidParameter):
                build_filters(*args, None, None, NOW)

    def test_bad_dates(self) -> None:
        for bad in ("ayer", "2026-13-01", "27/10/2026", "1793059200000"):
            with self.assertRaises(InvalidParameter, msg=bad):
                build_filters(bad, None, None, None, NOW)


class PageTests(unittest.TestCase):
    def test_defaults_to_maximum_and_zero_offset(self) -> None:
        self.assertEqual(parse_page(None, None, 5000), (5000, 0))
        self.assertEqual(parse_page("10", "20", 5000), (10, 20))

    def test_out_of_range_values_are_rejected(self) -> None:
        for limit, offset in (("0", None), ("-1", None), ("5001", None), ("x", None), (None, "-1"), (None, "x"), ("1.5", None)):
            with self.assertRaises(InvalidParameter, msg=(limit, offset)):
                parse_page(limit, offset, 5000)


# ------------------------------------------------------------------------------------------ CORS
class CorsTests(unittest.TestCase):
    def test_default_is_local_development_only(self) -> None:
        self.assertEqual(parse_origins(None), ["http://localhost:4200"])
        self.assertEqual(parse_origins("  "), ["http://localhost:4200"])

    def test_netlify_can_be_added_next_to_localhost(self) -> None:
        self.assertEqual(
            parse_origins("http://localhost:4200, https://mi-sitio.netlify.app"),
            ["http://localhost:4200", "https://mi-sitio.netlify.app"],
        )

    def test_trailing_slash_is_normalized_and_duplicates_removed(self) -> None:
        self.assertEqual(parse_origins("https://a.netlify.app/,https://a.netlify.app"), ["https://a.netlify.app"])

    def test_wildcard_and_malformed_origins_fail_at_startup(self) -> None:
        for bad in ("*", "http://localhost:4200,*", "localhost:4200", "ftp://x.com", "https://x.com/panel",
                    "https://", "https://x.com?a=1", "http://x .com", "https://x.com,,,not an origin"):
            with self.assertRaises(CorsConfigError, msg=bad):
                parse_origins(bad)

    def test_only_commas_is_an_error_not_a_silent_default(self) -> None:
        with self.assertRaises(CorsConfigError):
            parse_origins(" , ,")

    def test_ip_origins_and_ports(self) -> None:
        self.assertEqual(parse_origins("http://127.0.0.1:4200"), ["http://127.0.0.1:4200"])


# ------------------------------------------------------------------------------------------ horas UTC
class HourSeriesTests(unittest.TestCase):
    H = 1_793_109_600_000  # 2026-10-27T14:00:00Z, alineada a la hora

    def test_floor_hour(self) -> None:
        self.assertEqual(floor_hour(self.H), self.H)
        self.assertEqual(floor_hour(self.H + 3_599_999), self.H)
        self.assertEqual(floor_hour(self.H + HOUR_MS), self.H + HOUR_MS)

    def test_zero_hours_are_filled_with_explicit_zeros(self) -> None:
        series, filled = fill_hours({self.H: 3, self.H + 2 * HOUR_MS: 1}, self.H, self.H + 3 * HOUR_MS)
        self.assertTrue(filled)
        self.assertEqual([(s["hour"] - self.H) // HOUR_MS for s in series], [0, 1, 2])
        self.assertEqual([s["count"] for s in series], [3, 0, 1])

    def test_end_is_exclusive_at_an_exact_hour_boundary(self) -> None:
        series, _ = fill_hours({}, self.H, self.H + HOUR_MS)
        self.assertEqual(len(series), 1)
        series, _ = fill_hours({}, self.H, self.H + HOUR_MS + 1)
        self.assertEqual(len(series), 2)

    def test_unaligned_edges_include_partial_hours(self) -> None:
        series, _ = fill_hours({}, self.H + 30 * 60_000, self.H + 90 * 60_000)
        self.assertEqual([s["hour"] for s in series], [self.H, self.H + HOUR_MS])

    def test_empty_or_inverted_period(self) -> None:
        self.assertEqual(fill_hours({}, self.H, self.H)[0], [])
        self.assertEqual(fill_hours({}, self.H + 1, self.H)[0], [])

    def test_very_long_periods_return_only_hours_with_events(self) -> None:
        span = (ZERO_FILL_MAX_HOURS + 5) * HOUR_MS
        series, filled = fill_hours({self.H + 10 * HOUR_MS: 7, self.H: 2}, self.H, self.H + span)
        self.assertFalse(filled)
        self.assertEqual(series, [{"hour": self.H, "count": 2}, {"hour": self.H + 10 * HOUR_MS, "count": 7}])

    def test_exactly_at_the_limit_is_still_zero_filled(self) -> None:
        series, filled = fill_hours({}, self.H, self.H + ZERO_FILL_MAX_HOURS * HOUR_MS)
        self.assertTrue(filled)
        self.assertEqual(len(series), ZERO_FILL_MAX_HOURS)


class HistogramTests(unittest.TestCase):
    def test_bins_are_half_open_sorted_and_sparse(self) -> None:
        self.assertEqual(
            histogram({9: 2, 8: 5}, 0.5),
            [{"from": 4.0, "to": 4.5, "count": 5}, {"from": 4.5, "to": 5.0, "count": 2}],
        )

    def test_negative_bins_are_supported(self) -> None:
        self.assertEqual(histogram({-1: 3}, 0.5), [{"from": -0.5, "to": 0.0, "count": 3}])
        self.assertEqual(histogram({-1: 1}, 10.0), [{"from": -10.0, "to": 0.0, "count": 1}])

    def test_no_float_noise_in_edges(self) -> None:
        for bin_ in histogram({i: 1 for i in range(0, 30)}, 0.1):
            self.assertEqual(bin_["from"], round(bin_["from"], 6))
        self.assertEqual(histogram({3: 1}, 0.1)[0]["to"], 0.4)

    def test_empty(self) -> None:
        self.assertEqual(histogram({}, 0.5), [])


# ------------------------------------------------------------------------------------------ países / subregiones
class GroupTests(unittest.TestCase):
    H = 1_793_109_600_000

    def rows(self) -> list[GroupRow]:
        return [
            GroupRow(self.H, "assigned", "ESP", "España", "Southern Europe", 2),
            GroupRow(self.H, "assigned", "ITA", "Italia", "Southern Europe", 3),
            GroupRow(self.H, "unassigned", None, None, None, 4),
            GroupRow(self.H + HOUR_MS, "assigned", "ESP", "España", "Southern Europe", 1),
            GroupRow(self.H + HOUR_MS, "unassigned", None, None, None, 2),
            GroupRow(self.H + HOUR_MS, "pending", None, None, None, 1),
        ]

    def test_by_country_keeps_no_country_as_its_own_explicit_group(self) -> None:
        hourly, totals = aggregate_groups(self.rows(), "country")
        by_name = {t["name"]: t for t in totals}
        self.assertEqual(by_name[NO_COUNTRY_LABEL], {"key": None, "name": NO_COUNTRY_LABEL, "count": 6})
        self.assertEqual(by_name["España"]["count"], 3)
        self.assertEqual(sum(t["count"] for t in totals), 13)  # nada se pierde ni se cuenta dos veces
        self.assertEqual(sum(c["count"] for c in hourly), 13)

    def test_pending_is_not_confused_with_no_country(self) -> None:
        _, totals = aggregate_groups(self.rows(), "country")
        pending = [t for t in totals if t["key"] == "pending"]
        self.assertEqual(pending, [{"key": "pending", "name": PENDING_LABEL, "count": 1}])

    def test_by_subregion_merges_countries(self) -> None:
        _, totals = aggregate_groups(self.rows(), "subregion")
        by_name = {t["name"]: t["count"] for t in totals}
        self.assertEqual(by_name["Southern Europe"], 6)  # España 3 + Italia 3
        self.assertEqual(by_name[NO_COUNTRY_LABEL], 6)

    def test_totals_sorted_descending_then_by_name_and_hourly_by_time(self) -> None:
        hourly, totals = aggregate_groups(self.rows(), "country")
        self.assertEqual([t["count"] for t in totals], sorted((t["count"] for t in totals), reverse=True))
        self.assertEqual([c["hour"] for c in hourly], sorted(c["hour"] for c in hourly))

    def test_same_hour_and_group_rows_are_summed(self) -> None:
        rows = [GroupRow(self.H, "assigned", "ESP", "España", None, 2), GroupRow(self.H, "assigned", "ESP", "España", None, 5)]
        hourly, _ = aggregate_groups(rows, "country")
        self.assertEqual(len(hourly), 1)
        self.assertEqual(hourly[0]["count"], 7)

    def test_subregion_missing_falls_back_to_country(self) -> None:
        rows = [GroupRow(self.H, "assigned", "XXX", "Isla", None, 1)]
        self.assertEqual(aggregate_groups(rows, "subregion")[1], [{"key": "XXX", "name": "Isla", "count": 1}])


# ------------------------------------------------------------------------------------------ frescura
class FreshnessTests(unittest.TestCase):
    def test_live_recent_query_is_fresh(self) -> None:
        f = assess_freshness("live", NOW - 60_000, NOW, 300)
        self.assertEqual((f.stale, f.seconds_since_last_ingestion, f.reason), (False, 60, None))

    def test_live_exactly_at_the_threshold_is_still_fresh(self) -> None:
        self.assertFalse(assess_freshness("live", NOW - 300_000, NOW, 300).stale)
        self.assertTrue(assess_freshness("live", NOW - 301_000, NOW, 300).stale)

    def test_live_without_any_successful_query_is_stale(self) -> None:
        f = assess_freshness("live", None, NOW, 300)
        self.assertEqual((f.stale, f.reason), (True, "no_successful_query"))

    def test_live_old_query_is_stale_with_reason(self) -> None:
        f = assess_freshness("live", NOW - 3_600_000, NOW, 300)
        self.assertEqual((f.stale, f.seconds_since_last_ingestion, f.reason), (True, 3600, "last_successful_query_too_old"))

    def test_other_modes_never_report_stale(self) -> None:
        for mode in ("demo", "replay"):
            self.assertIsNone(assess_freshness(mode, NOW - 10**9, NOW, 300).stale)
            self.assertIsNone(assess_freshness(mode, None, NOW, 300).stale)

    def test_clock_skew_never_gives_negative_seconds(self) -> None:
        self.assertEqual(assess_freshness("live", NOW + 5_000, NOW, 300).seconds_since_last_ingestion, 0)


# ------------------------------------------------------------------------------------------ comparación histórica
def stats(**overrides) -> StatsData:
    base = dict(
        last_ingestion=NOW, total=10, missing_mag=2, missing_depth=1, hourly={}, group_rows=[], mag_bins={}, depth_bins={},
        window_count=40, window_null_mag_excluded=3,
        baseline=BaselineData(2025, year_events_total=18_302, events=3_650, days_with_events=300, null_mag_excluded=0),
    )
    base.update(overrides)
    return StatsData(**base)


def flt(**kw) -> EventFilters:
    base = dict(start_ms=NOW - DAY_MS, end_ms=None, min_mag=None, country_id=None)
    base.update(kw)
    return EventFilters(**base)


class ComparisonTests(unittest.TestCase):
    def test_mean_uses_every_day_of_the_year_including_days_with_zero_events(self) -> None:
        c = build_comparison(stats(), flt(), NOW)
        base = c["baseline"]
        self.assertEqual((base["days"], base["days_with_events"], base["days_without_events"]), (365, 300, 65))
        self.assertEqual(base["mean_per_day"], 3_650 / 365)  # 10,0: NO 3.650/300, que ignoraría los 65 días vacíos
        self.assertAlmostEqual(c["ratio_vs_daily_mean"], 4.0)

    def test_daily_distribution_is_exposed_to_give_context_to_the_mean(self) -> None:
        data = stats(baseline=BaselineData(2025, 18_302, 18_302, 365, 0, median_per_day=43.0, min_per_day=20, max_per_day=645))
        base = build_comparison(data, flt(), NOW)["baseline"]
        self.assertEqual((base["median_per_day"], base["min_per_day"], base["max_per_day"]), (43.0, 20, 645))
        self.assertAlmostEqual(base["mean_per_day"], 18_302 / 365)  # la media (50,1) y la mediana (43) difieren: se muestran ambas

    def test_leap_year_has_366_days(self) -> None:
        data = stats(baseline=BaselineData(2024, 5_000, 3_660, 360, 0))
        base = build_comparison(data, flt(), NOW)["baseline"]
        self.assertEqual((base["days"], base["mean_per_day"]), (366, 10.0))

    def test_threshold_is_never_below_the_history_floor(self) -> None:
        self.assertEqual(build_comparison(stats(), flt(min_mag=None), NOW)["filters"]["min_mag"], 4.0)
        self.assertEqual(build_comparison(stats(), flt(min_mag=2.0), NOW)["filters"]["min_mag"], 4.0)  # M≥2 no es comparable
        self.assertEqual(build_comparison(stats(), flt(min_mag=5.5), NOW)["filters"]["min_mag"], 5.5)

    def test_country_filter_is_the_same_on_both_sides(self) -> None:
        self.assertEqual(build_comparison(stats(), flt(country_id="CHL"), NOW)["filters"]["country_id"], "CHL")

    def test_missing_history_is_reported_explicitly_not_as_zero(self) -> None:
        data = stats(baseline=BaselineData(2025, year_events_total=0, events=0, days_with_events=0, null_mag_excluded=0))
        c = build_comparison(data, flt(), NOW)
        self.assertEqual(c["baseline"]["available"], False)
        self.assertEqual(c["baseline"]["reason"], "historico_not_loaded")
        self.assertNotIn("mean_per_day", c["baseline"])
        self.assertIsNone(c["ratio_vs_daily_mean"])

    def test_zero_baseline_mean_gives_null_ratio_not_infinity(self) -> None:
        data = stats(baseline=BaselineData(2025, year_events_total=10, events=0, days_with_events=0, null_mag_excluded=0))
        c = build_comparison(data, flt(country_id="XXX"), NOW)
        self.assertEqual(c["baseline"]["mean_per_day"], 0.0)
        self.assertEqual(c["baseline"]["days_without_events"], 365)
        self.assertIsNone(c["ratio_vs_daily_mean"])
        json.dumps(c, allow_nan=False)

    def test_window_is_the_24_hours_before_the_reference(self) -> None:
        c = build_comparison(stats(), flt(), NOW)
        self.assertEqual(c["last_24h"]["period"], {"start": NOW - DAY_MS, "end": NOW})
        self.assertEqual(c["last_24h"]["missing"], {"null_magnitude_excluded": 3})

    def test_states_the_caveats_the_assignment_asks_for(self) -> None:
        text = " ".join(build_comparison(stats(), flt(), NOW)["caveats"])
        for expected in ("incompleto", "retraso", "instantánea", "predicción"):
            self.assertIn(expected, text)

    def test_year_helpers(self) -> None:
        self.assertEqual((days_in_year(2025), days_in_year(2024), days_in_year(1900)), (365, 366, 365))
        start, end = year_bounds_ms(2025)
        self.assertEqual((start, end), (1_735_689_600_000, 1_767_225_600_000))
        self.assertEqual((end - start) // DAY_MS, 365)


class BuildStatisticsTests(unittest.TestCase):
    H = 1_793_109_600_000

    def build(self, data=None, filters=None, group="country", generated=None):
        return build_statistics(
            data or stats(hourly={self.H: 3}, mag_bins={8: 2}, depth_bins={1: 1}),
            filters or flt(start_ms=self.H, end_ms=self.H + 2 * HOUR_MS),
            mode="live", generated=generated or self.H + 5 * HOUR_MS, group_by=group,
        )

    def test_every_section_states_period_filters_unit_and_missing(self) -> None:
        body = self.build()
        sections = {
            "totals": body["totals"], "hourly": body["hourly"], "groups": body["groups"],
            "magnitude": body["distributions"]["magnitude"], "depth_km": body["distributions"]["depth_km"],
        }
        for name, section in sections.items():
            for key in ("period", "filters", "unit", "missing"):
                self.assertIn(key, section, f"{name} sin {key}")
            self.assertEqual(section["period"], {"start": self.H, "end": self.H + 2 * HOUR_MS}, name)
            self.assertEqual(section["filters"]["mode"], "live", name)

    def test_missing_values_are_reported_separately_from_the_distributions(self) -> None:
        body = self.build()
        self.assertEqual(body["totals"]["missing"], {"magnitude": 2, "depth": 1})
        self.assertEqual(body["distributions"]["magnitude"]["missing"], {"magnitude": 2})
        self.assertEqual(body["distributions"]["magnitude"]["with_value"], 8)  # 10 - 2
        self.assertEqual(body["distributions"]["depth_km"]["with_value"], 9)

    def test_open_ended_period_runs_until_generation_time(self) -> None:
        body = self.build(filters=flt(start_ms=self.H, end_ms=None), generated=self.H + 3 * HOUR_MS)
        self.assertEqual(len(body["hourly"]["series"]), 3)
        self.assertIsNone(body["hourly"]["period"]["end"])
        self.assertTrue(body["hourly"]["zero_filled"])

    def test_response_is_strict_json_with_no_nan(self) -> None:
        json.dumps(self.build(), allow_nan=False)

    def test_states_it_is_computed_over_all_matching_events(self) -> None:
        self.assertIn("sin muestreo", self.build()["metadata"]["computed_over"])


if __name__ == "__main__":
    unittest.main()
