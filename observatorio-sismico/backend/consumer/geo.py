"""Atribución de país por punto-en-polígono sobre el catálogo Natural Earth (constitución IV).

Reglas (documentadas y verificadas contra el catálogo real, escala 1:110M):

1. Solo geometría. El país NUNCA se deduce del texto `place` ni por proximidad. Un epicentro en el mar queda
   «sin país asignado» (`unassigned`): no es un error ni se atribuye al país más cercano.
2. Sistema de coordenadas: WGS84 (EPSG:4326), longitud/latitud en grados; catálogo y eventos son compatibles
   y no se reproyecta.
3. Frontera: el predicado es `covered_by`, así que un punto SOBRE el borde de un polígono cuenta como dentro.
4. Varias coincidencias (punto sobre una frontera compartida, o solape del catálogo): se elige el menor `ADM0_A3`
   en orden alfabético, para que el resultado sea determinista y reproducible, y se marca `ambiguous=True`
   (queda como `country_boundary_ambiguous` en `quality_flags`).
5. Antimeridiano: Natural Earth parte los polígonos en ±180°, así que lon = 180 y lon = -180 caen cada uno en la
   pieza que le corresponde.
6. Geometrías inválidas: 2 de las 177 del catálogo (USA y SDN) tienen autointersecciones. Se reparan con
   `make_valid` al construir el índice; el área no cambia. Sin esto los predicados no serían fiables.
7. Limitación conocida: las costas están simplificadas y faltan islas pequeñas, así que un evento costero o en una
   isla menor puede quedar «sin país» aunque su `place` mencione uno.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from shapely import STRtree, make_valid
from shapely.geometry import Point, shape

log = logging.getLogger("geo")


@dataclass(frozen=True)
class Attribution:
    country_id: str | None
    status: str  # 'assigned' | 'unassigned'
    ambiguous: bool = False

    @property
    def flags(self) -> tuple[str, ...]:
        return ("country_boundary_ambiguous",) if self.ambiguous else ()


UNASSIGNED = Attribution(None, "unassigned")


class CountryIndex:
    def __init__(self, features: list[dict]) -> None:
        ids: list[str] = []
        geometries = []
        repaired: list[str] = []
        for feature in features:
            country_id = feature["properties"]["ADM0_A3"]
            geometry = shape(feature["geometry"])
            if not geometry.is_valid:
                geometry = make_valid(geometry)
                repaired.append(country_id)
            ids.append(country_id)
            geometries.append(geometry)
        if len(set(ids)) != len(ids):
            raise ValueError("ADM0_A3 is not unique in the country catalog")
        self.ids = ids
        self.repaired = repaired
        self._tree = STRtree(geometries)
        if repaired:
            log.info("country index: %d geometries, repaired with make_valid: %s", len(ids), repaired)

    @classmethod
    def from_file(cls, path: Path) -> "CountryIndex":
        return cls(json.loads(path.read_text(encoding="utf-8"))["features"])

    def __len__(self) -> int:
        return len(self.ids)

    def locate(self, lon: float, lat: float) -> Attribution:
        hits = self._tree.query(Point(lon, lat), predicate="covered_by")
        if len(hits) == 0:
            return UNASSIGNED
        candidates = sorted(self.ids[i] for i in hits)
        return Attribution(candidates[0], "assigned", ambiguous=len(candidates) > 1)
