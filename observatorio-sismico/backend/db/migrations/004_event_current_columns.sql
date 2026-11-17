-- @per-schema
-- Columnas desnormalizadas del estado actual: permiten filtrar y agregar con índices en lugar de
-- extraer campos del JSONB en cada consulta. El payload original sigue en event_message.
-- Unidades: tiempos en ms Unix UTC, magnitud sin unidad, profundidad en km, lon/lat en grados WGS84.
ALTER TABLE event_current
    ADD COLUMN IF NOT EXISTS time_ms BIGINT,                       -- ocurrencia (properties.time)
    ADD COLUMN IF NOT EXISTS mag DOUBLE PRECISION,                 -- NULL = magnitud no disponible (ND)
    ADD COLUMN IF NOT EXISTS mag_type TEXT,
    ADD COLUMN IF NOT EXISTS depth_km DOUBLE PRECISION,            -- NULL = profundidad no disponible
    ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS place TEXT,                           -- texto descriptivo; NUNCA se usa para el país
    ADD COLUMN IF NOT EXISTS event_type TEXT,
    ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS country_id TEXT,                      -- ADM0_A3 si country_status = 'assigned'
    ADD COLUMN IF NOT EXISTS country_status TEXT NOT NULL DEFAULT 'pending';

-- Relleno de filas existentes desde la versión actual guardada.
UPDATE event_current c
SET time_ms     = (m.payload->'properties'->>'time')::bigint,
    mag         = CASE WHEN jsonb_typeof(m.payload->'properties'->'mag') = 'number'
                       THEN (m.payload->'properties'->>'mag')::double precision END,
    mag_type    = CASE WHEN jsonb_typeof(m.payload->'properties'->'magType') = 'string'
                       THEN m.payload->'properties'->>'magType' END,
    depth_km    = CASE WHEN jsonb_typeof(m.payload->'geometry'->'coordinates'->2) = 'number'
                       THEN (m.payload->'geometry'->'coordinates'->>2)::double precision END,
    lon         = (m.payload->'geometry'->'coordinates'->>0)::double precision,
    lat         = (m.payload->'geometry'->'coordinates'->>1)::double precision,
    place       = CASE WHEN jsonb_typeof(m.payload->'properties'->'place') = 'string'
                       THEN m.payload->'properties'->>'place' END,
    event_type  = m.payload->'properties'->>'type',
    ingested_at = m.ingested_at
FROM event_message m
WHERE m.message_id = c.message_id AND c.time_ms IS NULL;

ALTER TABLE event_current
    ALTER COLUMN time_ms SET NOT NULL,
    ALTER COLUMN lon SET NOT NULL,
    ALTER COLUMN lat SET NOT NULL,
    ALTER COLUMN event_type SET NOT NULL,
    ALTER COLUMN ingested_at SET NOT NULL,
    ADD CONSTRAINT ck_event_current_lon CHECK (lon BETWEEN -180 AND 180),
    ADD CONSTRAINT ck_event_current_lat CHECK (lat BETWEEN -90 AND 90),
    ADD CONSTRAINT ck_event_current_time CHECK (time_ms >= 0),
    -- pending: aún sin atribución; unassigned: fuera de todo país («Sin país asignado», no es un error);
    -- assigned: country_id presente. Nunca se asigna por proximidad ni por el texto de `place`.
    ADD CONSTRAINT ck_event_current_country_status
        CHECK (country_status IN ('pending', 'unassigned', 'assigned')),
    ADD CONSTRAINT ck_event_current_country_consistency
        CHECK ((country_status = 'assigned') = (country_id IS NOT NULL)),
    ADD CONSTRAINT fk_event_current_country
        FOREIGN KEY (country_id) REFERENCES ref.dim_country (country_id);
