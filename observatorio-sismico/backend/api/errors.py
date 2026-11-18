"""Contrato de errores de la API.

Distingue "sin resultados" (HTTP 200, features: []) de "fallo del servicio" (HTTP 4xx/5xx con cuerpo de error).
Un fallo de base de datos NUNCA se presenta como una colección vacía válida.

Cuerpo de error:  {"error": {"code": "<codigo>", "message": "<texto>"}}

| HTTP | code                  | Cuándo                                              |
|------|-----------------------|-----------------------------------------------------|
| 400  | invalid_parameter     | start/end no ISO8601, start >= end, parámetro ilegal |
| 503  | database_unavailable  | la consulta a PostgreSQL falla o no hay conexión     |
| 500  | internal_error        | error inesperado (sin detalles internos)             |

La API solo informa de lo que observa directamente en su propia consulta. No afirma nada
sobre el estado del consumidor: ese estado no forma parte del contrato.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Las excepciones viven en un módulo sin dependencias (testeable en el host); se reexportan aquí.
from backend.api.exceptions import ApiError, DatabaseUnavailable, InvalidParameter, error_body  # noqa: F401

log = logging.getLogger("api")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(error_body(error.code, error.message), status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, error: RequestValidationError) -> JSONResponse:
        first = error.errors()[0] if error.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", []))
        return JSONResponse(
            error_body("invalid_parameter", f"{where}: {first.get('msg', 'invalid request')}"),
            status_code=400,
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, error: Exception) -> JSONResponse:
        log.exception("unhandled error: %s", error)
        headers = {}
        # ServerErrorMiddleware queda por fuera de CORSMiddleware: sin esto el navegador vería un fallo de CORS y no el 500.
        origin = request.headers.get("origin")
        if origin and origin in getattr(request.app.state, "cors_origins", []):
            headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
        return JSONResponse(error_body("internal_error", "Internal server error"), status_code=500, headers=headers)
