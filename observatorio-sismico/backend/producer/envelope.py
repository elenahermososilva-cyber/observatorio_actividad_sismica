"""Empaqueta un Feature de USGS como mensaje Kafka, sin juzgar su contenido.

El productor publica TODO lo que recibe; el consumidor es el único punto de rechazo y deja el motivo en cuarentena
(D3). Por eso un feature que no supera la validación de `EventMessage` (coordenadas fuera de rango, sin `id`…)
se envía igualmente, en un sobre con el mismo formato y el payload original intacto, para que el consumidor lo ponga
en cuarentena con su motivo en vez de que el productor lo descarte en silencio.

`dedupe` es la clave con la que el productor recuerda qué ya publicó. Un feature sin `id` o `updated` válidos recibe
una clave estable derivada de su contenido: así se pone en cuarentena UNA vez y no cada minuto mientras siga en la
ventana de 24 h del feed.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from backend.producer.schema import EventMessage, IngestionMode, _iso_utc


@dataclass(frozen=True)
class Envelope:
    key: str | None
    value: bytes
    dedupe: tuple[str, int]
    well_formed: bool  # False: el productor no pudo validarlo; el consumidor lo pondrá en cuarentena


def _valid_id(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _valid_updated(properties: object) -> int | None:
    updated = properties.get("updated") if isinstance(properties, dict) else None
    return updated if isinstance(updated, int) and not isinstance(updated, bool) and updated >= 0 else None


def build_envelope(
    feature: object,
    *,
    mode: IngestionMode,
    source: str,
    synthetic_flag: bool,
    ingested_at: datetime,
    replay_at: datetime | None = None,
) -> Envelope:
    payload = feature if isinstance(feature, dict) else {"unparseable_feature": feature}
    event_id = _valid_id(payload.get("id"))
    updated = _valid_updated(payload.get("properties"))

    if event_id is not None and updated is not None:
        dedupe = (event_id, updated)
        try:
            message = EventMessage(
                event_id=event_id, source=source, mode=mode, ingested_at=ingested_at, updated_ms=updated,
                payload=payload, synthetic_flag=synthetic_flag, replay_at=replay_at,
            )
            return Envelope(event_id, message.to_json().encode("utf-8"), dedupe, True)
        except (ValueError, TypeError):
            pass  # no cumple el contrato: se envía sin validar y el consumidor lo rechazará con su motivo
    else:
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        dedupe = (f"invalid:{digest}", 0)

    raw = {
        "event_id": event_id or dedupe[0],
        "source": source,
        "mode": mode.value,
        "ingested_at": _iso_utc(ingested_at),
        "updated": updated if updated is not None else 0,
        "payload": payload,
        "synthetic_flag": synthetic_flag,
    }
    if replay_at is not None:
        raw["replay_at"] = _iso_utc(replay_at)
    return Envelope(event_id, json.dumps(raw, separators=(",", ":"), default=str).encode("utf-8"), dedupe, False)
