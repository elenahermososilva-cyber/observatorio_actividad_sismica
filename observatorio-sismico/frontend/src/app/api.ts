import type { Config, DataMode, Filters } from './models';

/** Error de red o de la API, con un mensaje apto para mostrar al usuario. */
export class ApiFailure extends Error {
  constructor(message: string, readonly httpStatus?: number, readonly code?: string) {
    super(message);
  }
}

export const DAY_MS = 86_400_000;

export async function readJson<T>(url: string, signal: AbortSignal, headers: Record<string, string> = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { headers, cache: 'no-store', signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]) });
  } catch (error) {
    if (signal.aborted) throw error; // cancelación deliberada: no es un fallo del backend
    throw new ApiFailure('No hay conexión con la API (¿túnel cerrado, backend apagado o CORS?)');
  }
  if (!response.ok) {
    let code: string | undefined;
    let message = `La API respondió HTTP ${response.status}`;
    try {
      const body = await response.json();
      code = body?.error?.code;
      if (body?.error?.message) message = `${message}: ${body.error.message}`;
    } catch { /* cuerpo no JSON (p. ej. página de aviso del túnel) */ }
    throw new ApiFailure(message, response.status, code);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiFailure('La respuesta no es JSON válido (¿página de aviso del túnel?)');
  }
}

export function resolveDataMode(config: Config, search: string): DataMode {
  const fromUrl = new URLSearchParams(search).get('mode');
  const wanted = fromUrl ?? config.dataMode ?? 'live';
  return wanted === 'demo' || wanted === 'replay' ? wanted : 'live';
}

/** Filtros iniciales desde la URL (p. ej. ?range=custom&from=2025-01-01&to=2025-01-31&min_mag=5&country=JPN): permite compartir y documentar una vista. */
export function filtersFromUrl(search: string, defaults: Filters): Filters {
  const q = new URLSearchParams(search);
  const range = q.get('range');
  return {
    range: range === '7d' || range === '30d' || range === 'custom' ? range : defaults.range,
    startDate: q.get('from') ?? defaults.startDate,
    endDate: q.get('to') ?? defaults.endDate,
    minMag: q.get('min_mag') ?? defaults.minMag,
    country: q.get('country') ?? defaults.country,
  };
}

export function apiBase(config: Config): string {
  return config.apiUrl.replace(/\/+$/, '');
}

export function apiHeaders(config: Config): Record<string, string> {
  return config.skipNgrokWarning ? { 'ngrok-skip-browser-warning': '1' } : {};
}

/** Rango [start, end) en ms UTC según los filtros. `null` = lo decide la API (últimas 24 h hasta ahora). */
export function periodOf(filters: Filters, now: number): { start: number | null; end: number | null } {
  switch (filters.range) {
    case '24h': return { start: null, end: null };
    case '7d': return { start: now - 7 * DAY_MS, end: null };
    case '30d': return { start: now - 30 * DAY_MS, end: null };
    default: {
      const start = Date.parse(`${filters.startDate}T00:00:00Z`);
      const lastDay = Date.parse(`${filters.endDate}T00:00:00Z`);
      return {
        start: Number.isFinite(start) ? start : null,
        end: Number.isFinite(lastDay) ? lastDay + DAY_MS : null, // «hasta» es inclusivo para la persona, exclusivo para la API
      };
    }
  }
}

/** Mismos parámetros para el mapa y para las estadísticas: así ambos describen exactamente el mismo conjunto. */
export function filterParams(filters: Filters, mode: DataMode, now: number): URLSearchParams {
  const params = new URLSearchParams({ mode });
  const { start, end } = periodOf(filters, now);
  if (start !== null) params.set('start', new Date(start).toISOString());
  if (end !== null) params.set('end', new Date(end).toISOString());
  const minMag = filters.minMag.trim().replace(',', '.');
  if (minMag !== '') params.set('min_mag', minMag);
  if (filters.country !== '') params.set('country_id', filters.country);
  return params;
}

export function validateFilters(filters: Filters): string | null {
  if (filters.minMag.trim() !== '') {
    const value = Number(filters.minMag.trim().replace(',', '.'));
    if (!Number.isFinite(value) || value < -10 || value > 10) return 'La magnitud mínima debe ser un número entre -10 y 10.';
  }
  if (filters.range === 'custom') {
    if (!filters.startDate || !filters.endDate) return 'Indica la fecha de inicio y la de fin.';
    if (filters.startDate > filters.endDate) return 'La fecha de inicio no puede ser posterior a la de fin.';
  }
  return null;
}
