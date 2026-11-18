import { ChangeDetectionStrategy, Component, computed, effect, input, signal } from '@angular/core';
import type { EventCollection } from './models';
import { formatDate } from './event-map.component';

type Row = { id: string; time: number; mag: number | null; depth: number | null; place: string; country: string; lon: number; lat: number };
type SortKey = 'time' | 'mag' | 'depth' | 'place' | 'country';

const PAGE = 25;

/** Tabla consultable de los eventos: alternativa textual al mapa y al color. */
@Component({
  selector: 'app-event-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <p class="meta" aria-live="polite">
      {{ rows().length }} eventos en la tabla
      @if (rows().length > 0) { · mostrando {{ first() }}–{{ last() }} }
    </p>
    <div class="scroll" tabindex="0" role="region" aria-label="Tabla de eventos, desplazable">
      <table>
        <caption class="sr-only">Eventos sísmicos que cumplen los filtros. Magnitud o profundidad «ND» significa no disponible.</caption>
        <thead>
          <tr>
            @for (c of columns; track c.key) {
              <th scope="col" [attr.aria-sort]="ariaSort(c.key)">
                <button type="button" (click)="sortBy(c.key)">{{ c.label }}{{ arrow(c.key) }}</button>
              </th>
            }
            <th scope="col">Coordenadas</th><th scope="col">ID</th>
          </tr>
        </thead>
        <tbody>
          @for (r of page(); track r.id) {
            <tr>
              <td>{{ date(r.time) }}</td>
              <td class="num" [class.nd]="r.mag === null">{{ r.mag === null ? 'ND' : r.mag }}</td>
              <td class="num" [class.nd]="r.depth === null">{{ r.depth === null ? 'ND' : r.depth + ' km' }}</td>
              <td>{{ r.place }}</td>
              <td [class.nd]="r.country === 'Sin país asignado'">{{ r.country }}</td>
              <td class="num">{{ r.lat }}, {{ r.lon }}</td>
              <td class="id">{{ r.id }}</td>
            </tr>
          } @empty {
            <tr><td colspan="7" class="empty">No hay eventos para los filtros seleccionados.</td></tr>
          }
        </tbody>
      </table>
    </div>
    @if (pages() > 1) {
      <nav class="pager" aria-label="Paginación de la tabla">
        <button type="button" (click)="go(-1)" [disabled]="index() === 0">‹ Anterior</button>
        <span>Página {{ index() + 1 }} de {{ pages() }}</span>
        <button type="button" (click)="go(1)" [disabled]="index() >= pages() - 1">Siguiente ›</button>
      </nav>
    }
  `,
  styles: [`
    .meta { margin: 0 0 6px; font-size: .9rem; color: #42596b; }
    .scroll { overflow: auto; max-height: 460px; border: 1px solid #cbd5e1; border-radius: 8px; background: white; }
    table { border-collapse: collapse; width: 100%; font-size: .88rem; }
    th, td { padding: 6px 10px; border-bottom: 1px solid #e2e8f0; text-align: left; white-space: nowrap; }
    thead th { position: sticky; top: 0; background: #f1f5f9; }
    thead button { all: unset; cursor: pointer; font-weight: 700; color: #132b40; } thead button:focus-visible { outline: 2px solid #176b70; outline-offset: 2px; }
    td.num { text-align: right; font-variant-numeric: tabular-nums; } td.nd { color: #64748b; font-style: italic; }
    td.id { color: #64748b; font-size: .8rem; } td.empty { text-align: center; padding: 18px; color: #42596b; font-style: italic; }
    .pager { display: flex; gap: 12px; align-items: center; justify-content: center; margin-top: 8px; }
    .pager button { padding: 4px 12px; }
    .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  `],
})
export class EventTableComponent {
  readonly events = input.required<EventCollection | null>();
  protected readonly columns: { key: SortKey; label: string }[] = [
    { key: 'time', label: 'Fecha UTC' }, { key: 'mag', label: 'Magnitud' }, { key: 'depth', label: 'Profundidad' },
    { key: 'place', label: 'Lugar' }, { key: 'country', label: 'País' },
  ];
  protected readonly sort = signal<{ key: SortKey; dir: 1 | -1 }>({ key: 'time', dir: -1 });
  protected readonly index = signal(0);

  protected readonly rows = computed<Row[]>(() => {
    const collection = this.events();
    if (!collection) return [];
    const rows: Row[] = [];
    for (const f of collection.features) {
      const p = f.properties;
      const [lon, lat, depth] = f.geometry?.type === 'Point' ? f.geometry.coordinates : [];
      if (!p || !Number.isFinite(lon) || !Number.isFinite(lat)) continue; // la API no los envía; se descartan por prudencia, nunca se inventan
      rows.push({
        id: String(f.id ?? 'ND'), time: p.time, mag: typeof p.mag === 'number' && Number.isFinite(p.mag) ? p.mag : null,
        depth: typeof depth === 'number' && Number.isFinite(depth) ? depth : null, place: p.place ?? 'Sin descripción',
        country: p.country_name ?? 'Sin país asignado', lon, lat,
      });
    }
    const { key, dir } = this.sort();
    // Los valores ND siempre al final, sea cual sea el sentido del orden.
    return rows.sort((a, b) => {
      const x = a[key], y = b[key];
      if (x === null && y === null) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      return (typeof x === 'string' ? x.localeCompare(y as string, 'es') : (x as number) - (y as number)) * dir;
    });
  });

  protected readonly pages = computed(() => Math.max(1, Math.ceil(this.rows().length / PAGE)));
  protected readonly page = computed(() => this.rows().slice(this.index() * PAGE, (this.index() + 1) * PAGE));
  protected readonly first = computed(() => this.index() * PAGE + 1);
  protected readonly last = computed(() => Math.min(this.rows().length, (this.index() + 1) * PAGE));

  constructor() {
    effect(() => { this.rows(); this.index.set(0); }); // nuevos datos u orden: volver a la primera página
  }

  protected date = formatDate;

  protected sortBy(key: SortKey): void {
    const current = this.sort();
    this.sort.set({ key, dir: current.key === key ? (current.dir === 1 ? -1 : 1) : key === 'place' || key === 'country' ? 1 : -1 });
    this.index.set(0);
  }
  protected arrow(key: SortKey): string { const s = this.sort(); return s.key === key ? (s.dir === 1 ? ' ▲' : ' ▼') : ''; }
  protected ariaSort(key: SortKey): string { const s = this.sort(); return s.key === key ? (s.dir === 1 ? 'ascending' : 'descending') : 'none'; }
  protected go(step: number): void { this.index.update((i) => Math.min(this.pages() - 1, Math.max(0, i + step))); }
}
