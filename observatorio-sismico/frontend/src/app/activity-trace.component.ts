import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import type { EventCollection, EventFeature } from './models';
import { formatDate } from './event-map.component';

const W = 600, H = 64, BASE = 30, HOUR = 3_600_000, DAY = 86_400_000;
const PEAK_AFTER_PX = 14; // longitud del «coletazo» tras la llegada de cada evento

type Peak = { x: number; amp: number; mag: number; feature: EventFeature };

/** Amplitud (px) de la oscilación de un evento según su magnitud. Es una escala visual, no una medida física. */
export function amplitudeFor(mag: number): number {
  return Math.min(26, 1.5 + Math.pow(Math.max(0, mag), 1.7) * 1.6);
}

/**
 * Trazo de actividad estilo sismograma construido con los eventos que recibe el panel: eje horizontal = periodo consultado,
 * cada terremoto es una oscilación en el instante en que ocurrió y su altura depende de la magnitud. No es una señal sísmica
 * medida. Los eventos sin magnitud (ND) no se dibujan y se cuentan aparte.
 */
@Component({
  selector: 'app-activity-trace',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="trace">
      <div class="head">
        <span class="title">Actividad en el periodo consultado</span>
        <span class="how">cada pico es un terremoto · altura según su magnitud</span>
      </div>
      @if (model(); as m) {
        <div class="plot" (mouseleave)="hover.set(null)">
          <svg [attr.viewBox]="'0 0 ' + W + ' ' + H" role="img" [attr.aria-label]="m.aria">
            <line [attr.x1]="0" [attr.x2]="W" [attr.y1]="BASE" [attr.y2]="BASE" class="axis" />
            @for (t of m.ticks; track $index) { <line [attr.x1]="t.x" [attr.x2]="t.x" [attr.y1]="H - 6" [attr.y2]="H" class="axis" /> }
            <polyline [attr.points]="m.points" class="wave" vector-effect="non-scaling-stroke" />
            @for (p of m.marks; track p.feature.id; let i = $index) {
              <circle [attr.cx]="p.x" [attr.cy]="BASE" [attr.r]="hover() === i ? 5 : 3" class="mark" vector-effect="non-scaling-stroke"
                      (mouseenter)="hover.set(i)" (click)="picked.emit(p.feature)"><title>{{ p.tip }}</title></circle>
            }
          </svg>
          @if (m.top; as t) { <span class="top" [style.left.%]="t.left">M {{ t.mag }}</span> }
          @if (tip(); as t) { <div class="tooltip" [style.left.%]="t.left">{{ t.text }}<br /><em>Pulsa para ver la ficha</em></div> }
        </div>
        <div class="labels">@for (t of m.ticks; track $index) { <span>{{ t.label }}</span> }</div>
        <p class="note">{{ m.note }}</p>
      } @else {
        <p class="note">Sin eventos con magnitud para trazar con estos filtros.</p>
      }
    </div>
  `,
  styles: [`
    .trace { display: flex; flex-direction: column; gap: 4px; }
    .head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
    .title { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
    .how { font-size: 11px; color: var(--muted); }
    .plot { position: relative; }
    svg { width: 100%; height: auto; display: block; overflow: visible; }
    .axis { stroke: var(--border-strong); stroke-width: 1; vector-effect: non-scaling-stroke; }
    .wave { fill: none; stroke: var(--accent); stroke-width: 1.3; stroke-linejoin: round; }
    .mark { fill: var(--accent); stroke: var(--bg); stroke-width: 1; cursor: pointer; }
    .top { position: absolute; top: -2px; transform: translateX(-50%); font-family: var(--font-num); font-size: 11px; font-weight: 700; color: var(--accent);
           background: var(--bg); padding: 0 4px; pointer-events: none; }
    .tooltip { position: absolute; top: -8px; transform: translate(-50%, -100%); background: var(--surface); color: var(--text); border: 1px solid var(--border-strong);
               padding: 6px 10px; border-radius: 6px; font-size: .78rem; white-space: nowrap; pointer-events: none; z-index: 5; box-shadow: 0 6px 18px rgba(0,0,0,.5); }
    .tooltip em { color: var(--muted); font-size: .72rem; }
    .labels { display: flex; justify-content: space-between; font-family: var(--font-num); font-size: 10px; color: var(--muted); }
    .note { margin: 2px 0 0; font-size: .74rem; color: var(--muted); }
  `],
})
export class ActivityTraceComponent {
  readonly events = input.required<EventCollection | null>();
  readonly picked = output<EventFeature>();
  protected readonly hover = signal<number | null>(null);
  protected readonly W = W; protected readonly H = H; protected readonly BASE = BASE;

  protected readonly model = computed(() => {
    const data = this.events();
    const meta = data?.metadata;
    if (!data || meta?.start == null) return null;
    const start = meta.start;
    const end = meta.end ?? meta.generated ?? Date.now();
    if (!(end > start)) return null;
    const span = end - start;

    const peaks: Peak[] = [];
    let noMag = 0;
    for (const f of data.features as EventFeature[]) {
      const mag = f.properties.mag;
      const t = f.properties.time;
      if (typeof mag !== 'number' || !Number.isFinite(mag)) { noMag++; continue; }
      if (t < start || t > end) continue;
      peaks.push({ x: ((t - start) / span) * W, amp: amplitudeFor(mag), mag, feature: f });
    }
    if (peaks.length === 0) return null;

    // Se suma la respuesta de cada evento en las muestras cercanas (2 por píxel): llegada brusca y oscilación que se apaga.
    const STEP = 0.5, N = Math.round(W / STEP) + 1;
    const y = new Float64Array(N);
    for (const p of peaks) {
      const i0 = Math.max(0, Math.floor((p.x - 1) / STEP)), i1 = Math.min(N - 1, Math.ceil((p.x + PEAK_AFTER_PX) / STEP));
      for (let i = i0; i <= i1; i++) {
        const dx = Math.max(0, i * STEP - p.x);
        y[i] += p.amp * Math.exp(-dx / 3.2) * Math.sin(dx * 2.4 + 0.3);
      }
    }
    const lo = -BASE + 2, hi = H - BASE - 2;
    let points = '';
    for (let i = 0; i < N; i++) points += `${(i * STEP).toFixed(1)},${(BASE - Math.max(lo, Math.min(hi, y[i]))).toFixed(1)} `;

    // Marcas (con tooltip y ficha) solo para los más intensos: con muchos eventos serían ilegibles.
    const strongest = [...peaks].sort((a, b) => b.mag - a.mag);
    const marks = strongest.slice(0, 40).sort((a, b) => a.x - b.x).map((p) => ({
      x: p.x, feature: p.feature,
      tip: `M ${p.mag} · ${p.feature.properties.place ?? 'Sin descripción'} · ${formatDate(p.feature.properties.time)}`,
    }));
    const top = strongest[0];

    // Etiquetas del eje: relativas si el periodo está abierto por la derecha y es corto; absolutas (UTC) en los demás casos.
    const relative = meta.end == null && span <= 2 * DAY;
    const ticks = [0, 1, 2, 3, 4].map((k) => {
      const t = start + (span * k) / 4;
      const iso = new Date(t).toISOString();
      const label = relative
        ? (k === 4 ? 'ahora' : `−${Math.round((span * (4 - k)) / 4 / HOUR)} h`)
        : span <= 2 * DAY ? `${iso.slice(11, 16)}` : `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
      return { x: (W * k) / 4, label };
    });

    const notes = [`${peaks.length} terremotos con magnitud`];
    if (noMag > 0) notes.push(`${noMag} sin magnitud (ND) no se dibujan`);
    if (meta.truncated) notes.push(`muestra: la API devolvió ${meta.count} de ${meta.total} eventos`);
    if (span > 2 * DAY) notes.push('con periodos largos los picos cercanos se solapan');
    const note = notes.join(' · ') + (relative ? '' : ' · horas en UTC');
    return {
      points: points.trim(), marks, ticks, note,
      top: { mag: top.mag, left: Math.min(94, Math.max(6, (top.x / W) * 100)) },
      aria: `Trazo de actividad con ${peaks.length} terremotos; el mayor, de magnitud ${top.mag}`,
      peaks,
    };
  });

  protected readonly tip = computed(() => {
    const i = this.hover();
    const m = this.model();
    if (i === null || !m) return null;
    const p = m.marks[i];
    return p ? { left: Math.min(88, Math.max(12, (p.x / W) * 100)), text: p.tip } : null;
  });
}
