"""Construcción de /api/estadisticas y de la frescura de /api/salud (sin dependencias externas).

Todo se calcula a partir de las filas ACTUALES (`event_current`): no hay contadores incrementales, así que una revisión
(que cambia magnitud, lugar o fecha) o un duplicado nunca puede contarse dos veces (enunciado §8).
Las cifras se calculan sobre TODO el conjunto filtrado en la base de datos, no sobre una página ni una muestra.
"""

import calendar
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.api.params import EventFilters

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
MAG_BIN_WIDTH = 0.5
DEPTH_BIN_KM = 10.0
ZERO_FILL_MAX_HOURS = 2_000
NO_COUNTRY_LABEL = "Sin país asignado"
PENDING_LABEL = "Pendiente de atribución"
# El histórico solo contiene M ≥ 4 (consulta de descarga): comparar por debajo de ese umbral no sería equivalente.
COMPARISON_MIN_MAG = 4.0
GROUPINGS = ("country", "subregion")


# ---------------------------------------------------------------------------------------- horas UTC
def floor_hour(ms: int) -> int:
    return ms - ms % HOUR_MS


def fill_hours(sparse: dict[int, int], start_ms: int, end_ms: int) -> tuple[list[dict], bool]:
    """Serie por hora UTC fija (por tiempo de ocurrencia). Con ≤ ZERO_FILL_MAX_HOURS horas rellena con ceros las horas
    sin eventos (un cero es información); con más devuelve solo las horas con eventos. Devuelve (serie, zero_filled)."""
    if end_ms <= start_ms:
        return [], True
    first, last = floor_hour(start_ms), floor_hour(end_ms - 1)
    hours = (last - first) // HOUR_MS + 1
    if hours > ZERO_FILL_MAX_HOURS:
        return [{"hour": h, "count": c} for h, c in sorted(sparse.items())], False
    return [{"hour": first + i * HOUR_MS, "count": sparse.get(first + i * HOUR_MS, 0)} for i in range(hours)], True


# ---------------------------------------------------------------------------------------- histogramas
def histogram(sparse_bins: dict[int, int], width: float) -> list[dict]:
    """Intervalos [from, to) con eventos, ordenados. `sparse_bins` mapea índice de intervalo → recuento."""
    return [
        {"from": round(index * width, 6), "to": round((index + 1) * width, 6), "count": count}
        for index, count in sorted(sparse_bins.items())
    ]


# ---------------------------------------------------------------------------------------- países / subregiones
@dataclass(frozen=True)
class GroupRow:
    hour: int
    country_status: str  # assigned | unassigned | pending
    country_id: str | None
    country_name: str | None
    subregion: str | None
    count: int


def _group_key(row: GroupRow, by: str) -> tuple[str | None, str]:
    """(clave, nombre). La clave `None` es «Sin país asignado»; `pending` no se confunde con él."""
    if row.country_status == "unassigned":
        return None, NO_COUNTRY_LABEL
    if row.country_status != "assigned":
        return "pending", PENDING_LABEL
    if by == "subregion":
        return (row.subregion, row.subregion) if row.subregion else (row.country_id, row.country_name or row.country_id)
    return row.country_id, row.country_name or row.country_id


def aggregate_groups(rows: list[GroupRow], by: str) -> tuple[list[dict], list[dict]]:
    """(recuentos por hora y grupo, totales por grupo). Solo grupos/horas con eventos; los totales van de mayor a menor."""
    hourly: dict[tuple[int, str | None], dict] = {}
    totals: dict[str | None, dict] = {}
    for row in rows:
        key, name = _group_key(row, by)
        cell = hourly.setdefault((row.hour, key), {"hour": row.hour, "key": key, "name": name, "count": 0})
        cell["count"] += row.count
        total = totals.setdefault(key, {"key": key, "name": name, "count": 0})
        total["count"] += row.count
    series = sorted(hourly.values(), key=lambda c: (c["hour"], c["name"]))
    ranking = sorted(totals.values(), key=lambda t: (-t["count"], t["name"]))
    return series, ranking


# ---------------------------------------------------------------------------------------- frescura (salud)
@dataclass(frozen=True)
class Freshness:
    stale: bool | None  # None = no aplica (demo/replay no consultan a USGS)
    seconds_since_last_ingestion: int | None
    reason: str | None


def assess_freshness(mode: str, last_ingestion_ms: int | None, now_ms: int, stale_after_seconds: int) -> Freshness:
    """Solo el modo live espera una ingesta continua: ahí «obsoleto» es una condición real. En demo y replay no aplica."""
    if mode != "live":
        return Freshness(None, None if last_ingestion_ms is None else max(0, (now_ms - last_ingestion_ms) // 1000), None)
    if last_ingestion_ms is None:
        return Freshness(True, None, "no_successful_query")
    seconds = max(0, (now_ms - last_ingestion_ms) // 1000)
    if seconds > stale_after_seconds:
        return Freshness(True, seconds, "last_successful_query_too_old")
    return Freshness(False, seconds, None)


# ---------------------------------------------------------------------------------------- comparación histórica
def days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def year_bounds_ms(year: int) -> tuple[int, int]:
    start = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(year + 1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    return start, end


@dataclass(frozen=True)
class BaselineData:
    year: int
    year_events_total: int  # eventos del año en el histórico, sin filtros: 0 ⇒ el histórico no está cargado
    events: int  # los que cumplen país y umbral de magnitud
    days_with_events: int  # días UTC distintos con al menos un evento de esos
    null_mag_excluded: int
    # Distribución diaria sobre TODOS los días del año (los días sin eventos cuentan como 0). La media sola puede
    # engañar si hay jornadas extremas (p. ej. una secuencia de réplicas): la mediana y el rango dan el contexto.
    median_per_day: float | None = None
    min_per_day: int | None = None
    max_per_day: int | None = None


@dataclass(frozen=True)
class StatsData:
    last_ingestion: int | None
    total: int
    missing_mag: int
    missing_depth: int
    hourly: dict[int, int]
    group_rows: list[GroupRow]
    mag_bins: dict[int, int]
    depth_bins: dict[int, int]
    window_count: int  # últimas 24 h bajo el umbral de comparación
    window_null_mag_excluded: int
    baseline: BaselineData


CAVEATS = [
    "La ventana de las últimas 24 h es móvil (no el día natural anterior) y su final puede estar incompleto: USGS "
    "publica con retraso y revisa sus datos, así que el recuento reciente puede subir después.",
    "El histórico es una instantánea del catálogo USGS en su fecha de extracción, no un registro de todas sus revisiones.",
    "La cobertura de detección y los tipos de magnitud (mww, mb, ml…) varían entre regiones y épocas.",
    "Estadística descriptiva: no es una predicción de terremotos ni una evaluación de riesgo.",
]


def build_comparison(data: StatsData, filters: EventFilters, ref_ms: int) -> dict:
    threshold = max(filters.min_mag if filters.min_mag is not None else COMPARISON_MIN_MAG, COMPARISON_MIN_MAG)
    scope = {
        "filters": {"min_mag": threshold, "country_id": filters.country_id},
        "unit": "terremotos",
    }
    window = {
        "period": {"start": ref_ms - DAY_MS, "end": ref_ms},
        "count": data.window_count,
        "missing": {"null_magnitude_excluded": data.window_null_mag_excluded},
    }
    base = data.baseline
    if base.year_events_total == 0:
        baseline = {
            "available": False,
            "reason": "historico_not_loaded",
            "detail": f"No hay eventos de {base.year} en el esquema histórico; cárgalo con history_loader.",
        }
        ratio = None
    else:
        days = days_in_year(base.year)
        mean = base.events / days  # el denominador son TODOS los días del año, incluidos los que no tuvieron eventos
        start, end = year_bounds_ms(base.year)
        baseline = {
            "available": True,
            "year": base.year,
            "period": {"start": start, "end": end},
            "events": base.events,
            "days": days,
            "days_with_events": base.days_with_events,
            "days_without_events": days - base.days_with_events,
            "mean_per_day": mean,
            "median_per_day": base.median_per_day,
            "min_per_day": base.min_per_day,
            "max_per_day": base.max_per_day,
            "missing": {"null_magnitude_excluded": base.null_mag_excluded},
        }
        ratio = data.window_count / mean if mean > 0 else None
    return {
        **scope,
        "last_24h": window,
        "baseline": baseline,
        "ratio_vs_daily_mean": ratio,
        "same_filters_note": (
            f"Mismos filtros geográficos y de tipo en ambos lados; umbral de magnitud ≥ {threshold:g} "
            f"(el histórico solo contiene M ≥ {COMPARISON_MIN_MAG:g}). Una magnitud nula nunca cumple el umbral."
        ),
        "caveats": CAVEATS,
    }


# ---------------------------------------------------------------------------------------- respuesta completa
def build_statistics(
    data: StatsData, filters: EventFilters, *, mode: str, generated: int, group_by: str,
) -> dict:
    end_effective = filters.end_ms if filters.end_ms is not None else generated
    period = {"start": filters.start_ms, "end": filters.end_ms}
    scope = {"period": period, "filters": {**filters.describe(), "mode": mode}}

    series, zero_filled = fill_hours(data.hourly, filters.start_ms, end_effective)
    groups_hourly, groups_total = aggregate_groups(data.group_rows, group_by)

    with_mag = data.total - data.missing_mag
    with_depth = data.total - data.missing_depth
    return {
        "metadata": {
            "generated": generated,
            "last_ingestion": data.last_ingestion,
            "mode": mode,
            "computed_over": "todos los eventos que cumplen los filtros (sin muestreo ni truncamiento)",
            "note_edges": "El primer y el último intervalo horario pueden ser parciales si start/end no están alineados a la hora.",
        },
        "totals": {**scope, "unit": "terremotos", "events": data.total,
                   "missing": {"magnitude": data.missing_mag, "depth": data.missing_depth}},
        "hourly": {
            **scope, "unit": "terremotos por hora UTC fija (según el tiempo de ocurrencia)", "bucket_ms": HOUR_MS,
            "zero_filled": zero_filled, "series": series, "missing": {},
        },
        "groups": {
            **scope, "unit": "terremotos", "by": group_by, "no_country_label": NO_COUNTRY_LABEL,
            "hourly": groups_hourly, "totals": groups_total, "missing": {},
        },
        "distributions": {
            "magnitude": {
                **scope, "unit": "magnitud (adimensional; tipos mixtos)", "bin_width": MAG_BIN_WIDTH,
                "bins": histogram(data.mag_bins, MAG_BIN_WIDTH), "with_value": with_mag,
                "missing": {"magnitude": data.missing_mag},
            },
            "depth_km": {
                **scope, "unit": "km", "bin_width": DEPTH_BIN_KM,
                "bins": histogram(data.depth_bins, DEPTH_BIN_KM), "with_value": with_depth,
                "missing": {"depth": data.missing_depth},
            },
        },
        "historical_comparison": build_comparison(data, filters, end_effective),
    }
