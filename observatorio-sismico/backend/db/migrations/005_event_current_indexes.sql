-- @per-schema
-- Índices justificados por las consultas de la API:
--  * ix_event_current_time:         ventana temporal (start/end) y ventanas de una hora UTC; ORDER BY time_ms DESC.
--  * ix_event_current_country_time: filtro por país + tiempo, y recuentos por país y hora.
--  * ix_event_current_mag:          filtro min_mag. Parcial: la magnitud nula nunca cumple min_mag,
--                                   así que no hace falta indexarla (índice más pequeño).
--  * ix_event_current_status:       recuento de eventos «Sin país asignado» / pendientes.
CREATE INDEX IF NOT EXISTS ix_event_current_time ON event_current (time_ms DESC);
CREATE INDEX IF NOT EXISTS ix_event_current_country_time ON event_current (country_id, time_ms DESC);
CREATE INDEX IF NOT EXISTS ix_event_current_mag ON event_current (mag) WHERE mag IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_event_current_status ON event_current (country_status);
