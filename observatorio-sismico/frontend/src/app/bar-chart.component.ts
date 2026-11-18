import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

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
        <svg [attr.viewBox]="'0 0 ' + W + ' ' + H" role="img" [attr.aria-label]="ariaLabel()" preserveAspectRatio="xMidYMid meet">
          @for (t of ticks(); track t.y) {
            <line [attr.x1]="L" [attr.x2]="W - R" [attr.y1]="t.y" [attr.y2]="t.y" class="grid" />
            <text [attr.x]="L - 6" [attr.y]="t.y + 4" text-anchor="end" class="tick">{{ t.label }}</text>
          }
          <line [attr.x1]="L" [attr.x2]="W - R" [attr.y1]="H - B" [attr.y2]="H - B" class="axis" />
          @for (b of vbars(); track $index) {
            <rect [attr.x]="b.x" [attr.y]="b.y" [attr.width]="b.w" [attr.height]="b.h" [attr.fill]="color()"><title>{{ b.title }}</title></rect>
            @if (b.showLabel) {
              <text [attr.x]="b.x + b.w / 2" [attr.y]="H - B + 14" text-anchor="middle" class="tick">{{ b.label }}</text>
            }
          }
        </svg>
        <p class="axis-name">{{ xLabel() }}</p>
      } @else {
        <svg [attr.viewBox]="'0 0 ' + W + ' ' + hHeight()" role="img" [attr.aria-label]="ariaLabel()" preserveAspectRatio="xMidYMid meet">
          @for (b of hbars(); track $index) {
            <text [attr.x]="HL - 8" [attr.y]="b.y + 16" text-anchor="end" class="tick">{{ b.label }}</text>
            <rect [attr.x]="HL" [attr.y]="b.y + 3" [attr.width]="b.w" height="18" [attr.fill]="b.accent ? '#64748b' : color()"><title>{{ b.title }}</title></rect>
            <text [attr.x]="HL + b.w + 6" [attr.y]="b.y + 16" class="tick">{{ b.value }}</text>
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
    svg { width: 100%; height: auto; display: block; }
    .grid { stroke: #dbe4ea; stroke-width: 1; } .axis { stroke: #64748b; stroke-width: 1; }
    .tick { font-size: 12px; fill: #42596b; } .axis-name { margin: 2px 0 0; text-align: center; font-size: .8rem; color: #42596b; }
    .empty { color: #42596b; font-style: italic; margin: 8px 0; }
    details { margin-top: 6px; font-size: .85rem; } summary { cursor: pointer; color: #176b70; }
    table { border-collapse: collapse; margin-top: 6px; max-height: 220px; display: block; overflow: auto; }
    th, td { border: 1px solid #cbd5e1; padding: 2px 8px; text-align: right; } th[scope=row], thead th { text-align: left; background: #f1f5f9; }
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
  readonly color = input<string>('#176b70');

  protected readonly W = 520; protected readonly H = 230;
  protected readonly L = 44; protected readonly R = 8; protected readonly T = 10; protected readonly B = 34;
  protected readonly HL = 150;

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
