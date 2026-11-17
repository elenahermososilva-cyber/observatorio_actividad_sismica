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

log = logging.getLogger("api")


class ApiError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidParameter(ApiError):
    status_code = 400
    code = "invalid_parameter"


class DatabaseUnavailable(ApiError):
    status_code = 503
    code = "database_unavailable"


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


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
    async def _unexpected(_: Request, error: Exception) -> JSONResponse:
        log.exception("unhandled error: %s", error)
        return JSONResponse(error_body("internal_error", "Internal server error"), status_code=500)
