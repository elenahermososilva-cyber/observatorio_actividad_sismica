import { ChangeDetectionStrategy, Component, OnDestroy, computed, signal } from '@angular/core';
import type { FeatureCollection } from 'geojson';
import {
  ApiFailure, apiBase, apiHeaders, filterParams, filtersFromUrl, readJson, resolveDataMode, validateFilters,
} from './api';
import { Bar, BarChartComponent } from './bar-chart.component';
import { EventMapComponent, formatDate } from './event-map.component';
import { EventTableComponent } from './event-table.component';
import type { Config, CountryOption, DataMode, EventCollection, Filters, Health, Statistics } from './models';

const DEFAULT_FILTERS: Filters = { range: '24h', startDate: '', endDate: '', minMag: '', country: '' };
const fmt = (value: number, digits = 1) => value.toLocaleString('es-ES', { maximumFractionDigits: digits });
const signed = (value: number, digits = 1) => (value > 0 ? '+' : '') + fmt(value, digits);

@Component({
  selector: 'app-root', standalone: true, imports: [EventMapComponent, EventTableComponent, BarChartComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './app.component.html', styleUrl: './app.component.css',
})
export class AppComponent implements OnDestroy {
  // ---- configuración y filtros
  protected readonly config = signal<Config | null>(null);
  protected readonly dataMode = signal<DataMode>('live');
  protected readonly configError = signal<string | null>(null);
  protected readonly draft = signal<Filters>({ ...DEFAULT_FILTERS });
  protected readonly applied = signal<Filters>({ ...DEFAULT_FILTERS });
  protected readonly filterError = signal<string | null>(null);
  protected readonly groupBy = signal<'country' | 'subregion'>('country');
  protected readonly hourGroup = signal<string>('');
  protected readonly countries = signal<FeatureCollection | null>(null);
  protected readonly countryOptions = signal<CountryOption[]>([]);
  protected readonly countriesStatus = signal('Cargando catálogo de países…');

  // ---- última lectura buena de cada recurso (se conserva si una consulta posterior falla)
  protected readonly events = signal<EventCollection | null>(null);
  protected readonly stats = signal<Statistics | null>(null);
  protected readonly health = signal<Health | null>(null);
  protected readonly lastOkAt = signal<number | null>(null); // reloj del navegador de la última consulta correcta de eventos
  protected readonly loading = signal(false);
  protected readonly eventsError = signal<string | null>(null);
  protected readonly statsError = signal<string | null>(null);
  protected readonly healthError = signal<string | null>(null);
  protected readonly omitted = signal(0);
  protected readonly now = signal(Date.now());

  protected readonly isDemoFile = computed(() => this.config()?.mode === 'demo');
  protected readonly replay = computed(() => (this.events()?.metadata?.mode ?? this.dataMode()) === 'replay');
  protected readonly synthetic = computed(() => this.isDemoFile() || (this.events()?.metadata?.mode ?? this.dataMode()) === 'demo');
  protected readonly backendDown = computed(() => this.eventsError() !== null);
  protected readonly stale = computed(() => this.health()?.stale === true);
  protected readonly truncated = computed(() => this.events()?.metadata?.truncated === true);

  protected readonly modeLabel = computed(() => {
    if (this.isDemoFile()) return 'DEMOSTRACIÓN · archivo estático con datos ficticios';
    if (this.replay()) return 'REPRODUCCIÓN · datos históricos reproducidos por Kafka';
    if (this.synthetic()) return 'DEMOSTRACIÓN · datos sintéticos del backend';
    return 'EN VIVO · datos reales de USGS vía backend';
  });

  protected readonly period = computed(() => {
    const meta = this.events()?.metadata;
    if (!meta) return 'Sin consulta todavía';
    const start = meta.start != null ? formatDate(meta.start) : 'inicio';
    const end = meta.end != null ? `${formatDate(meta.end)} (exclusivo)` : 'ahora';
    return `${start} → ${end}`;
  });

  protected readonly hourlyBars = computed<Bar[]>(() => {
    const s = this.stats();
    if (!s) return [];
    const series = s.hourly.series;
    const spanHours = series.length;
    const selected = this.hourGroup();
    const perHour = new Map<number, number>();
    if (selected !== '') {
      for (const g of s.groups.hourly) if ((g.key ?? 'none') === selected) perHour.set(g.hour, g.count);
    }
    return series.map((point) => {
      const date = new Date(point.hour);
      const iso = date.toISOString();
      const count = selected === '' ? point.count : perHour.get(point.hour) ?? 0;
      const label = spanHours <= 48 ? iso.slice(11, 13) : iso.slice(8, 10) + '/' + iso.slice(5, 7);
      return { label, value: count, title: `${iso.slice(0, 10)} ${iso.slice(11, 13)}:00–${iso.slice(11, 13)}:59 UTC · ${count} terremotos` };
    });
  });

  protected readonly hourlyIsSparse = computed(() => this.stats()?.hourly.zero_filled === false);

  protected readonly groupBars = computed<Bar[]>(() => {
    const s = this.stats();
    if (!s) return [];
    return s.groups.totals.slice(0, 15).map((g) => ({ label: g.name, value: g.count, title: `${g.name}: ${g.count} terremotos` }));
  });
  protected readonly groupsHidden = computed(() => Math.max(0, (this.stats()?.groups.totals.length ?? 0) - 15));
  protected readonly groupOptions = computed(() =>
    (this.stats()?.groups.totals ?? []).map((g) => ({ id: g.key ?? 'none', name: g.name })));

  protected readonly magnitudeBars = computed<Bar[]>(() => this.distBars(this.stats()?.distributions.magnitude, 'M'));
  protected readonly depthBars = computed<Bar[]>(() => this.distBars(this.stats()?.distributions.depth_km, 'km'));

  protected readonly comparison = computed(() => {
    const c = this.stats()?.historical_comparison;
    if (!c) return null;
    const base = c.baseline.available ? c.baseline : null;
    return {
      count: c.last_24h.count,
      period: `${formatDate(c.last_24h.period.start)} → ${formatDate(c.last_24h.period.end)}`,
      baseline: base && {
        year: base.year, events: base.events, days: base.days, zeroDays: base.days_without_events,
        mean: fmt(base.mean_per_day), median: base.median_per_day === null ? 'ND' : fmt(base.median_per_day),
        min: base.min_per_day ?? 'ND', max: base.max_per_day ?? 'ND',
      },
      ratio: c.ratio_vs_daily_mean === null ? null : fmt(c.ratio_vs_daily_mean, 2),
      // Diferencia y variación porcentual respecto a la media diaria (FAQ 23). Con media 0 la variación no está definida: ND.
      diff: base ? signed(c.last_24h.count - base.mean_per_day, 1) : 'ND',
      pct: base && base.mean_per_day > 0 ? signed(((c.last_24h.count - base.mean_per_day) / base.mean_per_day) * 100, 0) + ' %' : 'ND',
      note: c.same_filters_note, caveats: c.caveats,
      filters: c.filters,
    };
  });

  protected readonly staleText = computed(() => {
    const h = this.health();
    if (!h?.stale) return '';
    if (h.last_ingestion === null) return 'El productor live todavía no ha completado ninguna consulta correcta a USGS.';
    return `La última consulta correcta a USGS fue ${formatDate(h.last_ingestion)} (hace ${this.age(h.last_ingestion)}).`;
  });

  private timer?: ReturnType<typeof setTimeout>;
  private clock?: ReturnType<typeof setInterval>;
  private controller = new AbortController();
  private destroyed = false;
  private generation = 0;

  constructor() {
    this.clock = setInterval(() => this.now.set(Date.now()), 1000);
    void this.start();
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    clearTimeout(this.timer);
    clearInterval(this.clock);
    this.controller.abort();
  }

  // ------------------------------------------------------------------ arranque
  private async start(): Promise<void> {
    const boot = new AbortController();
    const catalogue = readJson<FeatureCollection>('datos/paises.geojson', boot.signal)
      .then((data) => {
        this.countries.set(data);
        const seen = new Map<string, string>();
        for (const f of data.features) {
          const id = f.properties?.['ADM0_A3'];
          if (typeof id === 'string' && !seen.has(id)) seen.set(id, f.properties?.['NAME_ES'] ?? f.properties?.['ADMIN'] ?? id);
        }
        this.countryOptions.set([...seen].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name, 'es')));
        this.countriesStatus.set(`Catálogo de países cargado (${seen.size})`);
      })
      .catch(() => this.countriesStatus.set('No se pudo cargar el catálogo de países'));
    try {
      const config = await readJson<Config>('config.json', boot.signal);
      if (!['demo', 'api'].includes(config.mode)) throw new Error('Modo inválido');
      this.config.set(config);
      this.dataMode.set(resolveDataMode(config, window.location.search));
      const initial = filtersFromUrl(window.location.search, DEFAULT_FILTERS);
      if (validateFilters(initial) === null) { this.draft.set(initial); this.applied.set(initial); }
    } catch {
      this.configError.set('Error: revisa public/config.json');
      return;
    }
    await catalogue;
    if (!this.destroyed) await this.refresh();
  }

  // ------------------------------------------------------------------ filtros
  protected setDraft<K extends keyof Filters>(key: K, value: Filters[K]): void {
    this.draft.update((d) => ({ ...d, [key]: value }));
  }
  protected input(key: keyof Filters, event: Event): void {
    this.setDraft(key, (event.target as HTMLInputElement | HTMLSelectElement).value as never);
  }

  protected applyFilters(event?: Event): void {
    event?.preventDefault();
    const draft = this.draft();
    const problem = validateFilters(draft);
    this.filterError.set(problem);
    if (problem) return;
    this.applied.set({ ...draft });
    this.hourGroup.set('');
    void this.refresh();
  }

  protected resetFilters(): void {
    this.draft.set({ ...DEFAULT_FILTERS });
    this.filterError.set(null);
    this.applied.set({ ...DEFAULT_FILTERS });
    this.hourGroup.set('');
    void this.refresh();
  }

  protected setGroupBy(value: 'country' | 'subregion'): void {
    this.groupBy.set(value);
    this.hourGroup.set('');
    void this.refresh();
  }

  protected setHourGroup(event: Event): void {
    this.hourGroup.set((event.target as HTMLSelectElement).value);
  }

  // ------------------------------------------------------------------ lectura de datos
  protected async refresh(): Promise<void> {
    const config = this.config();
    if (!config || this.destroyed) return;
    clearTimeout(this.timer);
    this.controller.abort();
    this.controller = new AbortController();
    const { signal } = this.controller;
    const ticket = ++this.generation;
    this.loading.set(true);
    try {
      if (config.mode === 'demo') {
        await this.readDemoFile(signal, ticket);
      } else {
        await this.readApi(config, signal, ticket);
      }
    } finally {
      if (ticket === this.generation && !this.destroyed) {
        this.loading.set(false);
        if (config.mode === 'api') {
          this.timer = setTimeout(() => void this.refresh(), Math.max(30000, Number(config.refreshMs) || 60000));
        }
      }
    }
  }

  private async readDemoFile(signal: AbortSignal, ticket: number): Promise<void> {
    try {
      const data = await readJson<EventCollection>('datos/terremotos-demo.geojson', signal);
      if (ticket !== this.generation) return;
      this.events.set(data);
      this.eventsError.set(null);
      this.lastOkAt.set(Date.now());
    } catch (error) {
      if (ticket === this.generation && !signal.aborted) this.eventsError.set(this.describe(error));
    }
  }

  private async readApi(config: Config, signal: AbortSignal, ticket: number): Promise<void> {
    const base = apiBase(config);
    const headers = apiHeaders(config);
    const mode = this.dataMode();
    const filters = this.applied();
    const now = Date.now();
    // Mismos filtros para el mapa y para los gráficos: se construyen una sola vez y se reutilizan.
    const common = filterParams(filters, mode, now);
    const statsParams = new URLSearchParams(common);
    statsParams.set('group', this.groupBy());
    const [events, stats, health] = await Promise.allSettled([
      readJson<EventCollection>(`${base}/api/eventos?${common}`, signal, headers),
      readJson<Statistics>(`${base}/api/estadisticas?${statsParams}`, signal, headers),
      readJson<Health>(`${base}/api/salud?mode=${mode}`, signal, headers),
    ]);
    if (ticket !== this.generation || signal.aborted) return; // llegó tarde: una consulta más reciente manda

    if (events.status === 'fulfilled') {
      const data = events.value;
      if (data.type === 'FeatureCollection' && Array.isArray(data.features)) {
        this.events.set(data);
        this.eventsError.set(null);
        this.lastOkAt.set(Date.now());
      } else {
        this.eventsError.set('La respuesta de la API no es una FeatureCollection');
      }
    } else {
      this.eventsError.set(this.describe(events.reason));
    }
    if (stats.status === 'fulfilled') { this.stats.set(stats.value); this.statsError.set(null); } else { this.statsError.set(this.describe(stats.reason)); }
    if (health.status === 'fulfilled') { this.health.set(health.value); this.healthError.set(null); }
    else {
      this.healthError.set(this.describe(health.reason));
      // /api/salud devuelve 503 con cuerpo útil cuando la base no responde; no se conserva un «ok» antiguo.
      this.health.set(null);
    }
  }

  private describe(error: unknown): string {
    if (error instanceof ApiFailure) return error.message;
    return 'Error inesperado al consultar la API';
  }

  // ------------------------------------------------------------------ utilidades de presentación
  protected date = formatDate;
  protected age(ms: number | null | undefined): string {
    if (ms == null) return 'ND';
    const seconds = Math.max(0, Math.round((this.now() - ms) / 1000));
    if (seconds < 90) return `${seconds} s`;
    if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
    if (seconds < 172800) return `${Math.round(seconds / 3600)} h`;
    return `${Math.round(seconds / 86400)} días`;
  }
  protected onOmitted(count: number): void { this.omitted.set(count); }
  private distBars(dist: { bins: { from: number; to: number; count: number }[] } | undefined, unit: string): Bar[] {
    if (!dist || dist.bins.length === 0) return [];
    // La API solo devuelve los intervalos con eventos: se rellenan los vacíos con 0 para que el eje sea continuo y honesto.
    const width = dist.bins[0].to - dist.bins[0].from;
    const byStart = new Map(dist.bins.map((b) => [Math.round(b.from / width), b.count]));
    const first = Math.round(dist.bins[0].from / width);
    const last = Math.round(dist.bins[dist.bins.length - 1].from / width);
    const bars: Bar[] = [];
    for (let i = first; i <= last; i++) {
      const from = i * width, count = byStart.get(i) ?? 0;
      bars.push({ label: fmt(from, 2), value: count, title: `${fmt(from, 2)} a menos de ${fmt(from + width, 2)} ${unit}: ${count} terremotos` });
    }
    return bars;
  }
}
