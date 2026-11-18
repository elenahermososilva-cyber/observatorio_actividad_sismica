import type { FeatureCollection, Point } from 'geojson';

/** Contenido de public/config.json. Es público: nunca debe contener secretos. */
export type Config = {
  mode: 'demo' | 'api';
  apiUrl: string;
  refreshMs: number;
  skipNgrokWarning: boolean;
  /** Conjunto de datos que se consulta a la API: live (por defecto), demo o replay. También admite ?mode= en la URL. */
  dataMode?: DataMode;
};

export type DataMode = 'live' | 'demo' | 'replay';

export type EventProperties = {
  mag: number | null;
  magType?: string | null;
  place: string | null;
  time: number;
  updated: number;
  country_id?: string | null;
  country_name?: string | null;
};

export type EventsMetadata = {
  generated?: number;
  last_ingestion?: number | null;
  mode?: string;
  count?: number;
  truncated?: boolean;
  total?: number;
  limit?: number;
  offset?: number;
  next_offset?: number | null;
  null_mag_count?: number;
  null_mag_excluded?: number;
  start?: number | null;
  end?: number | null;
};

export type EventCollection = FeatureCollection<Point, EventProperties> & { metadata?: EventsMetadata };

export type Period = { start: number | null; end: number | null };
export type Missing = Record<string, number>;
export type Bin = { from: number; to: number; count: number };
export type HourPoint = { hour: number; count: number };
export type GroupTotal = { key: string | null; name: string; count: number };
export type GroupHour = { hour: number; key: string | null; name: string; count: number };

export type Distribution = { unit: string; bin_width: number; bins: Bin[]; with_value: number; missing: Missing; period: Period };

export type Baseline =
  | { available: false; reason: string }
  | {
      available: true; year: number; events: number; days: number; days_with_events: number; days_without_events: number;
      mean_per_day: number; median_per_day: number | null; min_per_day: number | null; max_per_day: number | null;
      missing: Missing;
    };

export type Comparison = {
  unit: string;
  filters: { min_mag: number | null; country_id: string | null };
  last_24h: { period: Period; count: number; missing: Missing };
  baseline: Baseline;
  ratio_vs_daily_mean: number | null;
  same_filters_note: string;
  caveats: string[];
};

export type Statistics = {
  metadata: { generated: number; last_ingestion: number | null; mode: string };
  totals: { period: Period; unit: string; events: number; missing: { magnitude: number; depth: number } };
  hourly: { unit: string; zero_filled: boolean; series: HourPoint[] };
  groups: { by: string; no_country_label: string; hourly: GroupHour[]; totals: GroupTotal[] };
  distributions: { magnitude: Distribution; depth_km: Distribution };
  historical_comparison: Comparison;
};

export type Health = {
  status: 'ok' | 'stale' | 'error';
  database: string;
  mode: string;
  last_ingestion: number | null;
  stale: boolean | null;
  stale_after_seconds?: number;
  seconds_since_last_ingestion?: number | null;
  stale_reason?: string | null;
};

/** Filtros compartidos por mapa, tabla y gráficos: se envían idénticos a /api/eventos y /api/estadisticas. */
export type Filters = {
  range: '24h' | '7d' | '30d' | 'custom';
  startDate: string; // YYYY-MM-DD (UTC), solo con range = custom
  endDate: string; // YYYY-MM-DD (UTC, inclusivo en la interfaz), solo con range = custom
  minMag: string; // '' = sin filtro
  country: string; // '' = todos, 'none' = sin país asignado, o ADM0_A3
};

export type CountryOption = { id: string; name: string };
