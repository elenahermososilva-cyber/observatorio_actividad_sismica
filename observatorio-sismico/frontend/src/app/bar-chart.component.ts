import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

export type Bar = { label: string; value: number; title: string };

type Tick = { y: number; label: string };

/** Gráfico de barras en SVG hecho a mano (sin librerías de gráficos), con alternativa en tabla para lectores de pantalla. */
@Component({
  selector: 'app-bar-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <figure>
      <figcaption>{{ caption() }}</figcaption>
      @if (bars().length === 0) {
        <p class="empty">{{ emptyText() }}</p>
      } @else if (orientation() === 'vertical') {
        <div class="wrap">
        <svg [attr.viewBox]="'0 0 ' + W + ' ' + H" role="img" [attr.aria-label]="ariaLabel()" preserveAspectRatio="xMidYMid meet" (mouseleave)="hover.set(null)">
          @for (t of ticks(); track t.y) {
            <line [attr.x1]="L" [attr.x2]="W - R" [attr.y1]="t.y" [attr.y2]="t.y" class="grid" />
            <text [attr.x]="L - 6" [attr.y]="t.y + 4" text-anchor="end" class="tick">{{ t.label }}</text>
          }
          <line [attr.x1]="L" [attr.x2]="W - R" [attr.y1]="H - B" [attr.y2]="H - B" class="axis" />
          @for (b of vbars(); track $index) {
            <rect [attr.x]="b.x - (slotPad())" [attr.y]="T" [attr.width]="b.w + 2 * slotPad()" [attr.height]="H - B - T" fill="transparent" (mouseenter)="hover.set($index)" />
            <rect [attr.x]="b.x" [attr.y]="b.y" [attr.width]="b.w" [attr.height]="b.h" [attr.fill]="color()" rx="2"
                  [attr.fill-opacity]="hover() === null || hover() === $index ? 1 : 0.45" (mouseenter)="hover.set($index)" class="bar"><title>{{ b.title }}</title></rect>
            @if (b.showLabel) {
              <text [attr.x]="b.x + b.w / 2" [attr.y]="H - B + 14" text-anchor="middle" class="tick">{{ b.label }}</text>
            }
          }
        </svg>
          @if (vtip(); as t) { <div class="tooltip" [style.left.%]="t.left" [style.top.%]="t.top">{{ t.text }}</div> }
        </div>
        <p class="axis-name">{{ xLabel() }}</p>
      } @else {
        <svg [attr.viewBox]="'0 0 ' + W + ' ' + hHeight()" role="img" [attr.aria-label]="ariaLabel()" preserveAspectRatio="xMidYMid meet" (mouseleave)="hover.set(null)">
          @for (b of hbars(); track $index) {
            <text [attr.x]="HL - 8" [attr.y]="b.y + 16" text-anchor="end" class="tick">{{ b.label }}</text>
            <rect x="0" [attr.y]="b.y" [attr.width]="W" height="24" fill="transparent" (mouseenter)="hover.set($index)" />
            <rect [attr.x]="HL" [attr.y]="b.y + 3" [attr.width]="b.w" height="18" rx="2" [attr.fill]="b.accent ? '#64748b' : color()"
                  [attr.fill-opacity]="hover() === null || hover() === $index ? 1 : 0.45" (mouseenter)="hover.set($index)" class="bar"><title>{{ b.title }}</title></rect>
            <text [attr.x]="HL + b.w + 6" [attr.y]="b.y + 16" class="tick" [class.strong]="hover() === $index">{{ b.value }}</text>
          }
        </svg>
      }
      @if (bars().length > 0) {
        <details>
          <summary>Ver los datos como tabla</summary>
          <table>
            <caption class="sr-only">{{ caption() }}</caption>
            <thead><tr><th scope="col">{{ firstColumn() }}</th><th scope="col">{{ valueLabel() }}</th></tr></thead>
            <tbody>
              @for (b of bars(); track $index) {
                <tr><th scope="row">{{ b.label }}</th><td>{{ b.value }}</td></tr>
              }
            </tbody>
          </table>
        </details>
      }
    </figure>
  `,
  styles: [`
    figure { margin: 0; } figcaption { font-weight: 600; margin-bottom: 6px; }
    svg { width: 100%; height: auto; display: block; } .wrap { position: relative; } .bar { transition: fill-opacity .12s; }
    .tooltip { position: absolute; transform: translate(-50%, -115%); background: var(--surface); color: var(--text); border: 1px solid var(--border-strong); padding: 5px 9px; border-radius: 6px;
               font-size: .8rem; pointer-events: none; white-space: nowrap; box-shadow: 0 6px 18px rgba(0,0,0,.5); z-index: 2; }
    .strong { font-weight: 700; fill: #e6edf7; }
    .grid { stroke: #1e2a44; stroke-width: 1; } .axis { stroke: #3b4a6b; stroke-width: 1; }
    .tick { font-size: 12px; fill: #94a3bf; font-family: var(--font-num); } .axis-name { margin: 2px 0 0; text-align: center; font-size: .8rem; color: var(--muted); }
    .empty { color: var(--muted); font-style: italic; margin: 8px 0; }
    details { margin-top: 6px; font-size: .85rem; } summary { cursor: pointer; color: var(--accent); }
    table { border-collapse: collapse; margin-top: 6px; max-height: 220px; display: block; overflow: auto; }
    th, td { border: 1px solid var(--border-strong); padding: 2px 8px; text-align: right; } th[scope=row], thead th { text-align: left; background: var(--surface-2); }
    .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  `],
})
export class BarChartComponent {
  readonly bars = input.required<Bar[]>();
  readonly orientation = input<'vertical' | 'horizontal'>('vertical');
  readonly caption = input.required<string>();
  readonly ariaLabel = input<string>('Gráfico de barras');
  readonly xLabel = input<string>('');
  readonly valueLabel = input<string>('Terremotos');
  readonly firstColumn = input<string>('Intervalo');
  readonly emptyText = input<string>('Sin datos para los filtros seleccionados.');
  readonly color = input<string>('#22d3ee');

  protected readonly W = 520; protected readonly H = 230;
  protected readonly L = 44; protected readonly R = 8; protected readonly T = 10; protected readonly B = 34;
  protected readonly HL = 150;
  protected readonly hover = signal<number | null>(null);

  private readonly yMax = computed(() => niceMax(Math.max(1, ...this.bars().map((b) => b.value))));

  protected readonly ticks = computed<Tick[]>(() => {
    const max = this.yMax();
    const plotH = this.H - this.T - this.B;
    return [0, 1, 2, 3, 4].map((i) => ({ y: this.H - this.B - (plotH * i) / 4, label: String(Math.round((max * i) / 4 * 100) / 100) }));
  });

  protected readonly vbars = computed(() => {
    const bars = this.bars();
    const slot = (this.W - this.L - this.R) / bars.length;
    const w = Math.max(1, slot * 0.8);
    const plotH = this.H - this.T - this.B;
    const every = Math.max(1, Math.ceil(bars.length / 12));
    return bars.map((b, i) => {
      const h = (b.value / this.yMax()) * plotH;
      return { x: this.L + i * slot + (slot - w) / 2, y: this.H - this.B - h, w, h, label: b.label, title: b.title, showLabel: i % every === 0 };
    });
  });

  /** Margen de la zona sensible alrededor de cada barra (para que las barras finas sean fáciles de señalar). */
  protected readonly slotPad = computed(() => {
    const n = this.bars().length;
    const slot = (this.W - this.L - this.R) / Math.max(1, n);
    return slot * 0.1;
  });

  protected readonly vtip = computed(() => {
    const i = this.hover();
    const b = i === null ? undefined : this.vbars()[i];
    if (!b) return null;
    return { left: ((b.x + b.w / 2) / this.W) * 100, top: (Math.min(b.y, this.H - this.B - 4) / this.H) * 100, text: b.title };
  });

  protected readonly hHeight = computed(() => this.bars().length * 24 + 8);

  protected readonly hbars = computed(() => {
    const max = Math.max(1, ...this.bars().map((b) => b.value));
    const room = this.W - this.HL - 50;
    return this.bars().map((b, i) => ({
      y: i * 24, w: Math.max(b.value > 0 ? 2 : 0, (b.value / max) * room), value: b.value, title: b.title,
      label: b.label.length > 20 ? `${b.label.slice(0, 19)}…` : b.label,
      accent: b.label === 'Sin país asignado',
    }));
  });
}

/** Siguiente valor «redondo» (1, 2, 5 × 10^n) que contiene a `value`, para que el eje no acabe en cifras raras. */
export function niceMax(value: number): number {
  const exponent = Math.pow(10, Math.floor(Math.log10(value)));
  for (const step of [1, 2, 4, 5, 10]) if (value <= step * exponent) return step * exponent;
  return 10 * exponent;
}
