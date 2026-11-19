import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import type { EventCollection, EventFeature } from './models';
import { depthColor, formatDate } from './event-map.component';
import { niceMax } from './bar-chart.component';

type Dot = { x: number; y: number; color: string; feature: EventFeature; tip: string };

/** Dispersión magnitud–profundidad en SVG hecho a mano. Al pasar el ratón muestra el evento; al pulsar abre su ficha. */
@Component({
  selector: 'app-scatter-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <figure>
      <figcaption>{{ caption() }}</figcaption>
      @if (plot().dots.length === 0) {
        <p class="empty">Sin eventos con magnitud y profundidad para los filtros seleccionados.</p>
      } @else {
        <div class="wrap">
          <svg [attr.viewBox]="'0 0 ' + W + ' ' + H" role="img" aria-label="Dispersión de magnitud frente a profundidad" (mouseleave)="hover.set(null)">
            @for (t of plot().yTicks; track t.v) {
              <line [attr.x1]="L" [attr.x2]="W - R" [attr.y1]="t.y" [attr.y2]="t.y" class="grid" />
              <text [attr.x]="L - 6" [attr.y]="t.y + 4" text-anchor="end" class="tick">{{ t.v }}</text>
            }
            @for (t of plot().xTicks; track t.v) {
              <line [attr.x1]="t.x" [attr.x2]="t.x" [attr.y1]="T" [attr.y2]="H - B" class="grid" />
              <text [attr.x]="t.x" [attr.y]="H - B + 16" text-anchor="middle" class="tick">{{ t.v }}</text>
            }
            @for (d of plot().dots; track $index) {
              <circle [attr.cx]="d.x" [attr.cy]="d.y" [attr.r]="hover() === $index ? 7 : 4" [attr.fill]="d.color"
                      [attr.fill-opacity]="hover() === null || hover() === $index ? 0.8 : 0.35" [attr.stroke]="hover() === $index ? '#132b40' : 'none'"
                      class="dot" (mouseenter)="hover.set($index)" (click)="picked.emit(d.feature)"><title>{{ d.tip }}</title></circle>
            }
          </svg>
          @if (tip(); as t) {
            <div class="tooltip" [style.left.%]="t.left" [style.top.%]="t.top">{{ t.text }}<br /><em>Pulsa para ver la ficha</em></div>
          }
        </div>
        <p class="axis-name">Magnitud (tipos de magnitud mixtos) · eje vertical: profundidad en km, hacia abajo como en el subsuelo</p>
      }
      <p class="help">{{ plot().note }}</p>
    </figure>
  `,
  styles: [`
    figure { margin: 0; } figcaption { font-weight: 600; margin-bottom: 6px; }
    .wrap { position: relative; } svg { width: 100%; height: auto; display: block; }
    .grid { stroke: #e2e8f0; stroke-width: 1; } .tick { font-size: 12px; fill: #42596b; } .dot { cursor: pointer; transition: r .1s; }
    .tooltip { position: absolute; transform: translate(-50%, -120%); background: #132b40; color: white; padding: 6px 10px; border-radius: 6px;
               font-size: .8rem; pointer-events: none; white-space: nowrap; box-shadow: 0 2px 8px rgba(0,0,0,.25); z-index: 2; }
    .tooltip em { opacity: .75; font-size: .75rem; }
    .axis-name { margin: 2px 0 0; text-align: center; font-size: .8rem; color: #42596b; }
    .empty { color: #42596b; font-style: italic; margin: 8px 0; } .help { font-size: .8rem; color: #42596b; margin: 6px 0 0; }
  `],
})
export class ScatterChartComponent {
  readonly events = input.required<EventCollection | null>();
  readonly caption = input<string>('Magnitud frente a profundidad');
  readonly picked = output<EventFeature>();
  protected readonly hover = signal<number | null>(null);

  protected readonly W = 520; protected readonly H = 260;
  protected readonly L = 44; protected readonly R = 10; protected readonly T = 10; protected readonly B = 28;

  protected readonly plot = computed(() => {
    const features = this.events()?.features ?? [];
    const valid: { mag: number; depth: number; f: EventFeature }[] = [];
    let missing = 0;
    for (const f of features) {
      const mag = f.properties?.mag;
      const depth = f.geometry?.coordinates?.[2];
      if (typeof mag === 'number' && Number.isFinite(mag) && typeof depth === 'number' && Number.isFinite(depth)) valid.push({ mag, depth, f });
      else missing++;
    }
    const meta = this.events()?.metadata;
    const truncated = meta?.truncated === true;
    let note = `${valid.length} eventos dibujados`;
    if (missing > 0) note += ` · ${missing} sin magnitud o sin profundidad (ND), que no se pueden situar`;
    if (truncated) note += ` · muestra: la API devolvió ${meta?.count} de ${meta?.total} eventos, así que este gráfico no representa a todos`;
    if (valid.length === 0) return { dots: [] as Dot[], xTicks: [], yTicks: [], note };

    const magMin = Math.floor(Math.min(...valid.map((v) => v.mag)));
    const magMax = Math.ceil(Math.max(...valid.map((v) => v.mag)));
    const span = Math.max(1, magMax - magMin);
    const depthMax = niceMax(Math.max(10, ...valid.map((v) => v.depth)));
    const depthMin = Math.min(0, ...valid.map((v) => v.depth)); // USGS admite profundidades ligeramente negativas
    const px = (m: number) => this.L + ((m - magMin) / span) * (this.W - this.L - this.R);
    const py = (d: number) => this.T + ((d - depthMin) / (depthMax - depthMin)) * (this.H - this.T - this.B);
    const step = span > 6 ? 2 : 1;
    const xTicks = [];
    for (let m = magMin; m <= magMax; m += step) xTicks.push({ v: m, x: px(m) });
    const yTicks = [0, 1, 2, 3, 4].map((i) => {
      const v = Math.round(depthMin + ((depthMax - depthMin) * i) / 4);
      return { v, y: py(v) };
    });
    const dots: Dot[] = valid.map(({ mag, depth, f }) => ({
      x: px(mag), y: py(depth), color: depthColor(depth), feature: f,
      tip: `M ${mag} · ${Math.round(depth * 10) / 10} km · ${f.properties.place ?? 'Sin descripción'} · ${formatDate(f.properties.time)}`,
    }));
    return { dots, xTicks, yTicks, note };
  });

  protected readonly tip = computed(() => {
    const i = this.hover();
    const d = i === null ? undefined : this.plot().dots[i];
    if (!d) return null;
    return { left: (d.x / this.W) * 100, top: (d.y / this.H) * 100, text: d.tip };
  });
}
