-- @per-schema
-- Tiempo de reproducción (replay): cuarta marca temporal, distinta de la ocurrencia (payload.properties.time),
-- la actualización de la fuente (updated_ms) y la ingestión (ingested_at). NULL fuera del modo replay.
ALTER TABLE event_message ADD COLUMN IF NOT EXISTS replay_at TIMESTAMPTZ;

-- replay ⇔ tiene replay_at. Las filas existentes (demo/live) cumplen la restricción con replay_at NULL.
ALTER TABLE event_message
    ADD CONSTRAINT ck_event_message_replay_at CHECK ((mode = 'replay') = (replay_at IS NOT NULL));
