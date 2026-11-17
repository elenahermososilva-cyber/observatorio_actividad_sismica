"""Validación del mensaje crudo de Kafka sin dependencias externas (testeable en local).

Convierte bytes en un `EventMessage` válido o en un `Rejection` con motivo explícito.
Nada se descarta en silencio: todo `Rejection` termina en `quarantine_record`.
"""

import json
from dataclasses import dataclass
from enum import StrEnum

from backend.producer.schema import (
    EventMessage,
    InvalidGeometryError,
    InvalidJsonError,
)

EARTHQUAKE_TYPE = "earthquake"


class RejectionReason(StrEnum):
    INVALID_JSON = "invalid_json"
    SCHEMA_VIOLATION = "schema_violation"
    INVALID_COORDINATES = "invalid_coordinates"
    NON_EARTHQUAKE_TYPE = "non_earthquake_type"
    PERSISTENCE_CONSTRAINT = "persistence_constraint"
    # El mensaje declara un modo distinto del que corresponde al topic: se rechaza para no mezclar modos.
    MODE_MISMATCH = "mode_mismatch"


@dataclass(frozen=True)
class Rejection:
    reason: RejectionReason
    detail: str
    event_id: str | None = None
    source: str | None = None

    @property
    def text(self) -> str:
        return f"{self.reason.value}: {self.detail}"


def _best_effort_identity(raw: bytes) -> tuple[str | None, str | None]:
    """Recupera event_id/source de un mensaje aunque sea inválido, para trazabilidad."""
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, None
    if not isinstance(value, dict):
        return None, None
    event_id, source = value.get("event_id"), value.get("source")
    return (
        event_id if isinstance(event_id, str) and event_id.strip() else None,
        source if isinstance(source, str) and source.strip() else None,
    )


def parse_message(raw: bytes) -> EventMessage | Rejection:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        return Rejection(RejectionReason.INVALID_JSON, f"message is not valid UTF-8: {error.reason}")

    event_id, source = _best_effort_identity(raw)
    try:
        message = EventMessage.from_json(text)
    except InvalidJsonError as error:
        return Rejection(RejectionReason.INVALID_JSON, str(error))
    except InvalidGeometryError as error:
        return Rejection(RejectionReason.INVALID_COORDINATES, str(error), event_id, source)
    except (ValueError, TypeError) as error:
        return Rejection(RejectionReason.SCHEMA_VIOLATION, str(error), event_id, source)

    properties = message.payload.get("properties", {})
    event_type = properties.get("type") if isinstance(properties, dict) else None
    if event_type != EARTHQUAKE_TYPE:
        return Rejection(
            RejectionReason.NON_EARTHQUAKE_TYPE,
            f"properties.type={event_type!r}, expected {EARTHQUAKE_TYPE!r}",
            message.event_id,
            message.source,
        )
    return message
