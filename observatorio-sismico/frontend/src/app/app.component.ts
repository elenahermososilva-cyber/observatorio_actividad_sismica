import { ChangeDetectionStrategy, Component, OnDestroy, computed, signal } from '@angular/core';
import type { FeatureCollection } from 'geojson';
import {
  ApiFailure, apiBase, apiHeaders, filterParams, filtersFromUrl, readJson, resolveDataMode, validateFilters,
} from './api';
import { Bar, BarChartComponent } from './bar-chart.component';
import { EventMapComponent, formatDate } from './event-map.component';
import { EventTableComponent } from './event-table.component';
import { EventDetailComponent } from './event-detail.component';
import { ScatterChartComponent } from './scatter-chart.component';
import type {
  Config, CountryOption, DataMode, EventCollection, EventFeature, Filters, Health, HistFilters, Statistics, Tab,
} from './models';

const DEFAULT_FILTERS: Filters = { range: '24h', startDate: '', endDate: '', minMag: '', country: '' };
const DEFAULT_HIST: HistFilters = { startDate: '2025-01-01', endDate: '2025-12-31', minMag: '', country: '', pageSize: 25 };
const TABS: { id: Tab; label: string }[] = [
  { id: 'resumen', label: 'Resumen' }, { id: 'analisis', label: 'Análisis' }, { id: 'eventos', label: 'Eventos' },
  { id: 'historico', label: 'Histórico 2025' }, { id: 'estado', label: 'Estado del sistema' },
];
const tabFromHash = (hash: string): Tab => (TABS.find((t) => `#${t.id}` === hash)?.id ?? 'resumen');
const fmt = (value: number, digits = 1) => value.toLocaleString('es-ES', { maximumFractionDigits: digits });
const signed = (value: number, digits = 1) => (value > 0 ? '+' : '') + fmt(value, digits);

@Component({
  selector: 'app-root', standalone: true,
  imports: [EventMapComponent, EventTableComponent, BarChartComponent, ScatterChartComponent, EventDetailComponent],
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

  // ---- navegación por pestañas (se refleja en la URL: #resumen, #analisis…) y ficha de un evento
  protected readonly tabs = TABS;
  protected readonly tab = signal<Tab>(tabFromHash(window.location.hash));
  protected readonly selected = signal<{ feature: EventFeature; source: string } | null>(null);
  protected readonly usesFilters = computed(() => ['resumen', 'analisis', 'eventos'].includes(this.tab()));

  // ---- histórico 2025: consulta paginada en el servidor (modo `historico`, solo lectura). No se refresca: no cambia.
  protected readonly histDraft = signal<HistFilters>({ ...DEFAULT_HIST });
  protected readonly histApplied = signal<HistFilters>({ ...DEFAULT_HIST });
  protected readonly histPage = signal(0);
  protected readonly histData = signal<EventCollection | null>(null);
  protected readonly histStats = signal<Statistics | null>(null);
  protected readonly histLoading = signal(false);
  protected readonly histError = signal<string | null>(null);
  protected readonly histFilterError = signal<string | null>(null);
  private histController = new AbortController();
  protected readonly histPages = computed(() => {
    const total = this.histData()?.metadata?.total ?? 0;
    return Math.max(1, Math.ceil(total / this.histApplied().pageSize));
  });
  protected readonly histCountryBars = computed<Bar[]>(() =>
    (this.histStats()?.groups.totals ?? []).slice(0, 12).map((g) => ({ label: g.name, value: g.count, title: `${g.name}: ${fmt(g.count, 0)} terremotos` })));

  protected readonly histNoCountryPct = computed(() => {
    const s = this.histStats();
    if (!s || s.totals.events === 0) return 'ND';
    const none = s.groups.totals.find((g) => g.key === null)?.count ?? 0;
    return fmt((none / s.totals.events) * 100, 0) + ' %';
  });

  // ---- indicadores del resumen (sobre los mismos filtros que el mapa)
  protected readonly summary = computed(() => {
    const data = this.events();
    const s = this.stats();
    if (!data) return null;
    const features = data.features as EventFeature[];
    let latest: EventFeature | null = null;
    let strongest: EventFeature | null = null;
    for (const f of features) {
      if (!latest || f.properties.time > latest.properties.time) latest = f;
      const m = f.properties.mag;
      if (typeof m === 'number' && Number.isFinite(m) && (!strongest || m > (strongest.properties.mag as number))) strongest = f;
    }
    const total = s?.totals.events ?? data.metadata?.total ?? features.length;
    // Si hay estadísticas pero ningún grupo «sin país» (p. ej. filtrando por un país), son 0 eventos, no «no disponible».
    const noCountry = s ? (s.groups.totals.find((g) => g.key === null)?.count ?? 0) : null;
    return {
      total, latest, strongest, truncated: data.metadata?.truncated === true,
      noCountryPct: noCountry === null || !s || s.totals.events === 0 ? 'ND' : fmt((noCountry / s.totals.events) * 100, 0) + ' %',
      noCountry, nullMag: data.metadata?.null_mag_count ?? 0,
    };
  });

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

  private readonly onHash = () => this.tab.set(tabFromHash(window.location.hash));

  constructor() {
    this.clock = setInterval(() => this.now.set(Date.now()), 1000);
    window.addEventListener('hashchange', this.onHash);
    if (this.tab() === 'historico') void this.loadHistory(true);
    void this.start();
  }

  // ------------------------------------------------------------------ pestañas y ficha
  protected setTab(id: Tab): void {
    this.selected.set(null);
    this.tab.set(id);
    history.replaceState(null, '', `${window.location.pathname}${window.location.search}#${id}`);
    if (id === 'historico' && this.histData() === null && !this.histLoading()) void this.loadHistory(true);
  }
  protected openDetail(feature: EventFeature, source: string): void {
    this.selected.set({ feature, source });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  protected closeDetail(): void { this.selected.set(null); }
  protected liveSource(): string {
    return this.replay() ? 'Reproducción histórica' : this.synthetic() ? 'Demostración' : 'Evento en vivo (USGS)';
  }

  // ------------------------------------------------------------------ histórico 2025
  protected histInput(key: keyof HistFilters, event: Event): void {
    const raw = (event.target as HTMLInputElement | HTMLSelectElement).value;
    this.histDraft.update((d) => ({ ...d, [key]: key === 'pageSize' ? Number(raw) : raw }));
  }
  protected applyHistory(event?: Event): void {
    event?.preventDefault();
    const d = this.histDraft();
    const problem = validateFilters({ range: 'custom', startDate: d.startDate, endDate: d.endDate, minMag: d.minMag, country: d.country });
    this.histFilterError.set(problem);
    if (problem) return;
    this.histApplied.set({ ...d });
    this.histPage.set(0);
    void this.loadHistory(true);
  }
  protected resetHistory(): void {
    this.histDraft.set({ ...DEFAULT_HIST });
    this.histFilterError.set(null);
    this.histApplied.set({ ...DEFAULT_HIST });
    this.histPage.set(0);
    void this.loadHistory(true);
  }
  protected goHistory(step: number): void {
    const next = Math.min(this.histPages() - 1, Math.max(0, this.histPage() + step));
    if (next === this.histPage()) return;
    this.histPage.set(next);
    void this.loadHistory(false);
  }
  /** `withStats`: al cambiar los filtros también se recalculan los totales por país; al pasar de página, no. */
  private async loadHistory(withStats: boolean): Promise<void> {
    const config = this.config() ?? (await this.waitForConfig());
    if (!config || config.mode !== 'api') return;
    this.histController.abort();
    this.histController = new AbortController();
    const { signal } = this.histController;
    const f = this.histApplied();
    const params = filterParams({ range: 'custom', startDate: f.startDate, endDate: f.endDate, minMag: f.minMag, country: f.country }, 'live', Date.now());
    params.set('mode', 'historico');
    const page = new URLSearchParams(params);
    page.set('limit', String(f.pageSize));
    page.set('offset', String(this.histPage() * f.pageSize));
    const statsParams = new URLSearchParams(params);
    statsParams.set('group', 'country');
    this.histLoading.set(true);
    try {
      const [events, stats] = await Promise.all([
        readJson<EventCollection>(`${apiBase(config)}/api/eventos?${page}`, signal, apiHeaders(config)),
        withStats ? readJson<Statistics>(`${apiBase(config)}/api/estadisticas?${statsParams}`, signal, apiHeaders(config)) : Promise.resolve(null),
      ]);
      if (signal.aborted) return;
      this.histData.set(events);
      if (stats) this.histStats.set(stats);
      this.histError.set(null);
    } catch (error) {
      if (!signal.aborted) this.histError.set(this.describe(error));
    } finally {
      if (!signal.aborted) this.histLoading.set(false);
    }
  }
  private waitForConfig(): Promise<Config | null> {
    return new Promise((resolve) => {
      let tries = 0;
      const poll = setInterval(() => {
        const c = this.config();
        if (c || this.configError() || ++tries > 100) { clearInterval(poll); resolve(c); }
      }, 100);
    });
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    clearTimeout(this.timer);
    clearInterval(this.clock);
    this.controller.abort();
    this.histController.abort();
    window.removeEventListener('hashchange', this.onHash);
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
  protected fmtNum = fmt;
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
