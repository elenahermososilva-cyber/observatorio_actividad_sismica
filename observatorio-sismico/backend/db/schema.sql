CREATE TABLE IF NOT EXISTS event_message (
    event_id text NOT NULL,
    source text NOT NULL,
    mode text NOT NULL,
    source_time_ms bigint NOT NULL CHECK (source_time_ms >= 0),
    source_updated_ms bigint NOT NULL CHECK (source_updated_ms >= 0),
    ingested_at timestamptz NOT NULL,
    replayed_at timestamptz,
    synthetic_flag boolean NOT NULL,
    payload jsonb NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, source_updated_ms)
);

CREATE TABLE IF NOT EXISTS event_current (
    event_id text PRIMARY KEY,
    source text NOT NULL,
    mode text NOT NULL,
    current_version_ms bigint NOT NULL CHECK (current_version_ms >= 0),
    source_time_ms bigint NOT NULL CHECK (source_time_ms >= 0),
    source_updated_ms bigint NOT NULL CHECK (source_updated_ms >= 0),
    ingested_at timestamptz NOT NULL,
    replayed_at timestamptz,
    synthetic_flag boolean NOT NULL,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status = 'active'),
    last_seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS event_current_source_time_idx
    ON event_current (source_time_ms);

CREATE INDEX IF NOT EXISTS event_current_ingested_at_idx
    ON event_current (ingested_at);

CREATE TABLE IF NOT EXISTS quarantine_record (
    quarantine_id bigserial PRIMARY KEY,
    event_id text,
    source text,
    reason text NOT NULL CHECK (length(trim(reason)) > 0),
    original_reference text NOT NULL,
    original_payload jsonb NOT NULL,
    kafka_topic text NOT NULL,
    kafka_partition integer NOT NULL,
    kafka_offset bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (kafka_topic, kafka_partition, kafka_offset)
);
