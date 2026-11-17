"""Reglas de calidad y transformación del consumidor (puras, sin dependencias externas).

Principios (enunciado §6):
- NO se rellenan nulos con cero. Magnitud o profundidad ausentes se conservan como NULL («ND»).
- Una magnitud o profundidad NEGATIVA no es automáticamente un error: se conserva y se señala.
- Nada de esto rechaza el registro. El rechazo (cuarentena) es solo para lo que no se puede tratar: JSON/esquema
  inválido, coordenadas inválidas o tipo distinto de `earthquake` (processing.py).
- Cada regla que actúa deja un código en `event_current.quality_flags`, de modo que se puede CONTAR cuántos
  registros afecta (`SELECT code, count(*) FROM event_current, unnest(quality_flags) code GROUP BY 1`).

Códigos. Prefijos: `gap_` dato ausente · `anomaly_` valor sospechoso conservado · `fixed_` transformación que
CAMBIA el dato · `country_` atribución geográfica.
"""

from dataclasses import dataclass, replace

from backend.db.columns import EventColumns

# Umbrales de plausibilidad física. Marcan, nunca rechazan.
MAG_MIN_PLAUSIBLE = -2.0  # por debajo hay microsismos instrumentales, pero es raro y conviene revisarlo
MAG_MAX_PLAUSIBLE = 10.0  # ningún terremoto registrado alcanza M10
DEPTH_MAX_PLAUSIBLE_KM = 800.0  # los sismos más profundos conocidos rondan los 700 km
FUTURE_TOLERANCE_MS = 5 * 60 * 1000  # tolerancia de reloj entre la fuente y la ingestión

FLAG_CODES = {
    "gap_mag_missing": "magnitud ausente (se conserva NULL, se muestra ND)",
    "gap_mag_type_missing": "hay magnitud pero no su tipo (magType)",
    "gap_depth_missing": "profundidad ausente (se conserva NULL)",
    "gap_place_missing": "sin descripción textual del lugar",
    "anomaly_mag_negative": "magnitud negativa: válida, se conserva",
    "anomaly_mag_out_of_range": f"magnitud fuera de [{MAG_MIN_PLAUSIBLE:g}, {MAG_MAX_PLAUSIBLE:g}]",
    "anomaly_depth_negative": "profundidad negativa: puede indicar posición sobre el nivel de referencia, se conserva",
    "anomaly_depth_very_large": f"profundidad superior a {DEPTH_MAX_PLAUSIBLE_KM:g} km",
    "anomaly_time_in_future": "ocurrencia posterior a la ingestión (más allá de la tolerancia de reloj)",
    "anomaly_updated_before_time": "la actualización de la fuente es anterior a la ocurrencia",
    "fixed_place_trimmed": "se quitaron espacios sobrantes de `place`",
    "fixed_place_blank_to_null": "`place` vacío o solo espacios convertido a NULL",
    "fixed_mag_type_lowercased": "`magType` pasado a minúsculas (USGS lo publica en minúsculas)",
    "country_boundary_ambiguous": "el punto cae sobre una frontera y cumple varios países (se eligió el menor ADM0_A3)",
}


@dataclass(frozen=True)
class Assessment:
    columns: EventColumns  # tras las transformaciones `fixed_*`
    flags: tuple[str, ...]


def assess(columns: EventColumns, updated_ms: int) -> Assessment:
    flags: list[str] = []
    place, mag_type = columns.place, columns.mag_type

    # --- transformaciones (cambian el dato; se registran) ---
    if place is not None:
        stripped = place.strip()
        if stripped != place:
            flags.append("fixed_place_blank_to_null" if not stripped else "fixed_place_trimmed")
        place = stripped or None
    if mag_type is not None and mag_type != mag_type.lower():
        flags.append("fixed_mag_type_lowercased")
        mag_type = mag_type.lower()

    # --- huecos de datos (no se rellenan) ---
    if columns.mag is None:
        flags.append("gap_mag_missing")
    elif mag_type is None or not mag_type.strip():
        flags.append("gap_mag_type_missing")
    if columns.depth_km is None:
        flags.append("gap_depth_missing")
    if place is None:
        flags.append("gap_place_missing")

    # --- anomalías (se conservan) ---
    if columns.mag is not None:
        if columns.mag < 0:
            flags.append("anomaly_mag_negative")
        if not MAG_MIN_PLAUSIBLE <= columns.mag <= MAG_MAX_PLAUSIBLE:
            flags.append("anomaly_mag_out_of_range")
    if columns.depth_km is not None:
        if columns.depth_km < 0:
            flags.append("anomaly_depth_negative")
        if columns.depth_km > DEPTH_MAX_PLAUSIBLE_KM:
            flags.append("anomaly_depth_very_large")
    ingested_ms = int(columns.ingested_at.timestamp() * 1000)
    if columns.time_ms > ingested_ms + FUTURE_TOLERANCE_MS:
        flags.append("anomaly_time_in_future")
    if updated_ms < columns.time_ms:
        flags.append("anomaly_updated_before_time")

    return Assessment(replace(columns, place=place, mag_type=mag_type), tuple(flags))
