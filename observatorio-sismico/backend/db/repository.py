from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from producer.schema import EventMessage


class PostgresRepository:
    def __init__(self, dsn: str | None) -> None:
        self._dsn = dsn

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        if not self._dsn:
            raise RuntimeError("DATABASE_URL is not configured")
        return psycopg.connect(self._dsn, row_factory=psycopg.rows.dict_row)

    def persist_event(self, event: EventMessage) -> bool:
        envelope = event.model_dump(mode="json")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO event_message (
                        event_id, source, mode, source_time_ms, source_updated_ms,
                        ingested_at, replayed_at, synthetic_flag, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id, source_updated_ms) DO NOTHING
                    """,
                    (
                        event.event_id,
                        event.source,
                        event.mode,
                        event.time,
                        event.updated,
                        event.ingested_at,
                        event.replayed_at,
                        event.synthetic_flag,
                        Jsonb(envelope),
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO event_current (
                        event_id, source, mode, current_version_ms, source_time_ms,
                        source_updated_ms, ingested_at, replayed_at, synthetic_flag, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO UPDATE SET
                        source = EXCLUDED.source,
                        mode = EXCLUDED.mode,
                        current_version_ms = EXCLUDED.current_version_ms,
                        source_time_ms = EXCLUDED.source_time_ms,
                        source_updated_ms = EXCLUDED.source_updated_ms,
                        ingested_at = EXCLUDED.ingested_at,
                        replayed_at = EXCLUDED.replayed_at,
                        synthetic_flag = EXCLUDED.synthetic_flag,
                        payload = EXCLUDED.payload,
                        last_seen_at = now()
                    WHERE event_current.current_version_ms < EXCLUDED.current_version_ms
                    """,
                    (
                        event.event_id,
                        event.source,
                        event.mode,
                        event.updated,
                        event.time,
                        event.updated,
                        event.ingested_at,
                        event.replayed_at,
                        event.synthetic_flag,
                        Jsonb(envelope),
                    ),
                )
                changed = cursor.rowcount == 1
        return changed

    def get_current_events(
        self, since_ms: int
    ) -> tuple[list[dict[str, Any]], datetime | None]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT event_id, payload, source_time_ms, source_updated_ms
                    FROM event_current
                    WHERE source_time_ms >= %s
                    ORDER BY source_time_ms, event_id
                    """,
                    (since_ms,),
                )
                events = cursor.fetchall()
                cursor.execute("SELECT MAX(ingested_at) AS last_ingestion FROM event_message")
                last_ingestion = cursor.fetchone()["last_ingestion"]
        return events, last_ingestion

    def check_connection(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
