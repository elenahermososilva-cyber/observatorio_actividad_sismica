-- @per-schema
-- Calidad: avisos y transformaciones por evento, para poder CONTAR cuántos registros afecta cada regla.
-- NULL = todavía no evaluado (filas anteriores a esta migración); '{}' = evaluado y sin incidencias.
-- Los códigos están documentados en backend/consumer/quality.py.
ALTER TABLE event_current ADD COLUMN IF NOT EXISTS quality_flags TEXT[];

-- Modo `historical`: instantánea del catálogo USGS cargada por history_loader (no llega por Kafka).
ALTER TABLE event_message DROP CONSTRAINT IF EXISTS event_message_mode_check;
ALTER TABLE event_message
    ADD CONSTRAINT event_message_mode_check CHECK (mode IN ('demo', 'live', 'replay', 'historical'));
