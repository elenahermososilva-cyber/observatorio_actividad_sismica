-- Aislamiento por modo reforzado en la propia base de datos (D2): cada esquema solo admite mensajes de su modo.
-- Hasta ahora lo garantizaba el consumidor (rechazo `mode_mismatch`); ahora ni un INSERT directo puede mezclarlos.
ALTER TABLE demo.event_message      ADD CONSTRAINT ck_event_message_schema_mode CHECK (mode = 'demo');
ALTER TABLE live.event_message      ADD CONSTRAINT ck_event_message_schema_mode CHECK (mode = 'live');
ALTER TABLE replay.event_message    ADD CONSTRAINT ck_event_message_schema_mode CHECK (mode = 'replay');
ALTER TABLE historico.event_message ADD CONSTRAINT ck_event_message_schema_mode CHECK (mode = 'historical');
