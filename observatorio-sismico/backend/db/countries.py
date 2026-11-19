"""Carga de la dimensión país desde el catálogo Natural Earth entregado.

Solo se guardan atributos (ADM0_A3, NAME_ES, ADMIN, CONTINENT, SUBREGION) y la huella SHA-256 del archivo.
La geometría no se guarda en PostgreSQL: el punto-en-polígono (Fase 8) usa el GeoJSON en memoria.
`ADM0_A3` se usa como identificador solo después de comprobar su unicidad; no se presupone que sea ISO oficial.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("countries")

_REQUIRED_GEOMETRIES = {"Polygon", "MultiPolygon"}


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Country:
    country_id: str
    name_es: str | None
    admin: str | None
    continent: str | None
    subregion: str | None


@dataclass(frozen=True)
class Catalog:
    countries: list[Country]
    sha256: str


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def fingerprint(raw: bytes) -> str:
    """SHA-256 con saltos de línea normalizados a LF.

    Con `core.autocrlf=true` (Git en Windows) la copia de trabajo tiene CRLF y su SHA difiere de la huella
    publicada en docs/curso/FUENTES-Y-LICENCIAS.md, aunque el contenido sea el mismo. Normalizar da la misma huella en todo equipo.
    """
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def read_catalog(path: Path) -> Catalog:
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise CatalogError(f"{path.name} is not valid JSON") from error
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list) or not features:
        raise CatalogError("catalog must be a non-empty FeatureCollection")

    countries: list[Country] = []
    seen: dict[str, int] = {}
    for index, feature in enumerate(features):
        properties = feature.get("properties") if isinstance(feature, dict) else None
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(properties, dict):
            raise CatalogError(f"feature {index} has no properties")
        if not isinstance(geometry, dict) or geometry.get("type") not in _REQUIRED_GEOMETRIES:
            raise CatalogError(f"feature {index} geometry must be Polygon or MultiPolygon")
        country_id = _text(properties.get("ADM0_A3"))
        if country_id is None:
            raise CatalogError(f"feature {index} has no ADM0_A3")
        if country_id in seen:
            raise CatalogError(f"ADM0_A3 {country_id!r} is not unique (features {seen[country_id]} and {index})")
        seen[country_id] = index
        countries.append(
            Country(
                country_id,
                _text(properties.get("NAME_ES")),
                _text(properties.get("ADMIN")),
                _text(properties.get("CONTINENT")),
                _text(properties.get("SUBREGION")),
            )
        )
    return Catalog(countries, fingerprint(raw))


_UPSERT = """
INSERT INTO ref.dim_country (country_id, name_es, admin, continent, subregion, source_sha256)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (country_id) DO UPDATE SET
    name_es = EXCLUDED.name_es, admin = EXCLUDED.admin, continent = EXCLUDED.continent,
    subregion = EXCLUDED.subregion, source_sha256 = EXCLUDED.source_sha256, loaded_at = now()
WHERE (ref.dim_country.name_es, ref.dim_country.admin, ref.dim_country.continent,
       ref.dim_country.subregion, ref.dim_country.source_sha256)
      IS DISTINCT FROM
      (EXCLUDED.name_es, EXCLUDED.admin, EXCLUDED.continent, EXCLUDED.subregion, EXCLUDED.source_sha256)
"""


def load_catalog(conn, path: Path) -> tuple[int, int]:
    """Carga idempotente. Devuelve (total en catálogo, filas insertadas o modificadas). `conn` es psycopg síncrona."""
    catalog = read_catalog(path)
    changed = 0
    with conn.transaction():
        for c in catalog.countries:
            cursor = conn.execute(_UPSERT, (c.country_id, c.name_es, c.admin, c.continent, c.subregion, catalog.sha256))
            changed += cursor.rowcount
    log.info("dim_country: %d countries in catalog, %d inserted/updated (sha256 %s)", len(catalog.countries), changed, catalog.sha256[:12])
    return len(catalog.countries), changed
