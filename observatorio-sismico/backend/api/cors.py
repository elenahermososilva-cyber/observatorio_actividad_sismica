"""Configuración de CORS desde la variable de entorno CORS_ORIGINS (sin dependencias externas).

El enunciado exige autorizar el ORIGEN EXACTO del panel (Netlify) y el de desarrollo, no un comodín. CORS no es
autenticación: solo indica al navegador qué páginas pueden leer la respuesta. Para añadir el dominio de Netlify cuando
exista, basta añadirlo a CORS_ORIGINS y recrear el servicio `api`:

    CORS_ORIGINS=http://localhost:4200,https://mi-sitio.netlify.app
"""

import logging
import re

DEFAULT_ORIGINS = ("http://localhost:4200",)
ALLOWED_METHODS = ["GET", "OPTIONS"]
# Cabecera personalizada que envía el panel para saltar la página intermedia de ngrok.
ALLOWED_HEADERS = ["ngrok-skip-browser-warning"]
_ORIGIN = re.compile(r"^https?://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:\d{1,5})?$")

log = logging.getLogger("api")


class CorsConfigError(ValueError):
    pass


def parse_origins(raw: str | None) -> list[str]:
    """Lista de orígenes exactos. Vacío → solo desarrollo local. Un comodín o un origen mal formado es un error de arranque."""
    if raw is None or not raw.strip():
        return list(DEFAULT_ORIGINS)
    origins: list[str] = []
    for item in raw.split(","):
        origin = item.strip()
        if not origin:
            continue
        if origin == "*":
            raise CorsConfigError("CORS_ORIGINS must list exact origins; '*' is not allowed")
        normalized = origin.rstrip("/")  # error típico: «https://sitio.netlify.app/» nunca coincide con el Origin del navegador
        if normalized != origin:
            log.warning("CORS_ORIGINS: removed trailing slash from %r", origin)
        if not _ORIGIN.match(normalized):
            raise CorsConfigError(
                f"CORS_ORIGINS entry {origin!r} is not a valid origin (expected scheme://host[:port], no path)"
            )
        if normalized not in origins:
            origins.append(normalized)
    if not origins:
        raise CorsConfigError("CORS_ORIGINS contains no origins")
    return origins
