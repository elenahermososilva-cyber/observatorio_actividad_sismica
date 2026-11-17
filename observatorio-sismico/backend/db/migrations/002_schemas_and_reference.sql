-- D2: un esquema PostgreSQL por modo, con el mismo DDL, para aislar demo / live / replay / histórico.
-- `ingest` guarda el estado del productor (D1) y `ref` los datos de referencia compartidos.
CREATE SCHEMA IF NOT EXISTS demo;
CREATE SCHEMA IF NOT EXISTS live;
CREATE SCHEMA IF NOT EXISTS replay;
CREATE SCHEMA IF NOT EXISTS historico;
CREATE SCHEMA IF NOT EXISTS ingest;
CREATE SCHEMA IF NOT EXISTS ref;

-- Las tablas de la migración 001 (public) solo pudieron recibir datos del modo demo
-- (live y replay no existían): se mueven tal cual a `demo`, con sus restricciones, índices y datos.
DO $$
BEGIN
    IF to_regclass('public.event_message') IS NOT NULL
       AND to_regclass('demo.event_message') IS NULL THEN
        ALTER TABLE public.event_message SET SCHEMA demo;
        ALTER TABLE public.event_current SET SCHEMA demo;
        ALTER TABLE public.quarantine_record SET SCHEMA demo;
    END IF;
END
$$;

-- Dimensión país (Natural Earth). Solo atributos: la geometría permanece en el GeoJSON
-- y se indexa en memoria (STRtree) para el punto-en-polígono. `country_id` = ADM0_A3 (unicidad comprobada al cargar).
CREATE TABLE IF NOT EXISTS ref.dim_country (
    country_id TEXT PRIMARY KEY CHECK (length(trim(country_id)) > 0),
    name_es TEXT,
    admin TEXT,
    continent TEXT,
    subregion TEXT,
    source_sha256 TEXT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
