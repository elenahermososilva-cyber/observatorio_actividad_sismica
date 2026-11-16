from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class EventVersion:
    event_id: str
    updated_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str):
            raise TypeError("event_id must be a string")
        if not self.event_id.strip():
            raise ValueError("event_id must not be empty")
        if isinstance(self.updated_ms, bool) or not isinstance(self.updated_ms, int):
            raise TypeError("updated_ms must be an integer Unix timestamp in milliseconds")
        if self.updated_ms < 0:
            raise ValueError("updated_ms must not be negative")


class VersionDecision(Enum):
    NEW = "new"
    DUPLICATE = "duplicate"
    REVISION = "revision"
    STALE = "stale"


def classify_version(
    incoming: EventVersion,
    current: EventVersion | None,
) -> VersionDecision:
    if current is None:
        return VersionDecision.NEW
    if incoming.event_id != current.event_id:
        raise ValueError("versions must belong to the same event")
    if incoming.updated_ms == current.updated_ms:
        return VersionDecision.DUPLICATE
    if incoming.updated_ms > current.updated_ms:
        return VersionDecision.REVISION
    return VersionDecision.STALE
