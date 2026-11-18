"""Excepciones y cuerpo de error de la API, sin dependencias externas (testeables en el host)."""


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
