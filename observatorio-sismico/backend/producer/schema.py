import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Self


class IngestionMode(StrEnum):
    DEMO = "demo"
    LIVE = "live"
    REPLAY = "replay"


@dataclass(frozen=True)
class EventMessage:
    event_id: str
    source: str
    mode: IngestionMode
    ingested_at: datetime
    updated_ms: int
    payload: dict[str, object]
    synthetic_flag: bool

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("event_id must be a non-empty string")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a non-empty string")
        if not isinstance(self.mode, IngestionMode):
            raise TypeError("mode must be an IngestionMode")
        if not isinstance(self.ingested_at, datetime):
            raise TypeError("ingested_at must be a datetime")
        if (
            self.ingested_at.tzinfo is None
            or self.ingested_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("ingested_at must be timezone-aware UTC")
        if (
            isinstance(self.updated_ms, bool)
            or not isinstance(self.updated_ms, int)
            or self.updated_ms < 0
        ):
            raise ValueError("updated_ms must be a non-negative integer")
        if not isinstance(self.synthetic_flag, bool):
            raise TypeError("synthetic_flag must be a boolean")
        if self.mode is IngestionMode.DEMO and not self.synthetic_flag:
            raise ValueError("demo messages must be marked synthetic")
        if self.mode is IngestionMode.LIVE and self.synthetic_flag:
            raise ValueError("live messages cannot be marked synthetic")
        self._validate_payload()

    def _validate_payload(self) -> None:
        if not isinstance(self.payload, dict):
            raise TypeError("payload must be a JSON object")
        if self.payload.get("type") != "Feature":
            raise ValueError("payload.type must be Feature")
        if self.payload.get("id") != self.event_id:
            raise ValueError("payload.id must match event_id")

        properties = self.payload.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("payload.properties must be an object")
        updated = properties.get("updated")
        if (
            isinstance(updated, bool)
            or not isinstance(updated, int)
            or updated < 0
        ):
            raise ValueError("payload.properties.updated must be milliseconds")
        if updated != self.updated_ms:
            raise ValueError("updated_ms must match payload.properties.updated")

        geometry = self.payload.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "Point":
            raise ValueError("payload.geometry must be a GeoJSON Point")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) not in (2, 3):
            raise ValueError("Point coordinates must include longitude and latitude")
        for coordinate in coordinates[:2]:
            if (
                isinstance(coordinate, bool)
                or not isinstance(coordinate, (int, float))
                or not math.isfinite(coordinate)
            ):
                raise ValueError("longitude and latitude must be finite numbers")
        longitude, latitude = coordinates[:2]
        if not -180 <= longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if not -90 <= latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if len(coordinates) == 3:
            depth = coordinates[2]
            if depth is not None and (
                isinstance(depth, bool)
                or not isinstance(depth, (int, float))
                or not math.isfinite(depth)
            ):
                raise ValueError("depth must be a finite number or null")

        magnitude = properties.get("mag")
        if magnitude is not None and (
            isinstance(magnitude, bool)
            or not isinstance(magnitude, (int, float))
            or not math.isfinite(magnitude)
        ):
            raise ValueError("payload.properties.mag must be a finite number or null")

        event_time = properties.get("time")
        if (
            isinstance(event_time, bool)
            or not isinstance(event_time, int)
            or event_time < 0
        ):
            raise ValueError("payload.properties.time must be milliseconds")

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "mode": self.mode.value,
            "ingested_at": self.ingested_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "updated": self.updated_ms,
            "payload": self.payload,
            "synthetic_flag": self.synthetic_flag,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if not isinstance(value, dict):
            raise ValueError("message must be a JSON object")

        required = {
            "event_id",
            "source",
            "mode",
            "ingested_at",
            "updated",
            "payload",
            "synthetic_flag",
        }
        missing = required.difference(value)
        if missing:
            raise ValueError(f"message is missing required fields: {sorted(missing)}")

        try:
            mode = IngestionMode(value["mode"])
        except (TypeError, ValueError) as error:
            raise ValueError("mode must be demo, live or replay") from error

        timestamp = value["ingested_at"]
        if not isinstance(timestamp, str):
            raise ValueError("ingested_at must be an ISO 8601 string")
        try:
            ingested_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("ingested_at must be an ISO 8601 string") from error

        updated_ms = value["updated"]
        if isinstance(updated_ms, bool) or not isinstance(updated_ms, int):
            raise ValueError("updated must be an integer Unix timestamp in milliseconds")

        payload = value["payload"]
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")

        return cls(
            event_id=value["event_id"],
            source=value["source"],
            mode=mode,
            ingested_at=ingested_at,
            updated_ms=updated_ms,
            payload=payload,
            synthetic_flag=value["synthetic_flag"],
        )

    @classmethod
    def from_json(cls, raw: str) -> Self:
        def reject_non_finite(value: str) -> None:
            raise ValueError(f"{value} is not a valid JSON number")

        try:
            value = json.loads(raw, parse_constant=reject_non_finite)
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError("message must contain valid JSON") from error
        return cls.from_dict(value)
