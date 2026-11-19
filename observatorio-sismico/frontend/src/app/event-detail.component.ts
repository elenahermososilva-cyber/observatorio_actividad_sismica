import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { LeafletDirective } from '@bluehalo/ngx-leaflet';
import * as L from 'leaflet';
import type { EventFeature } from './models';
import { DARK_ATTRIBUTION, DARK_TILES, depthColor, formatDate, radiusFor } from './event-map.component';

/** Ficha de un evento: todos sus campos tal como los devuelve la API y un mapa centrado en el epicentro. */
@Component({
  selector: 'app-event-detail',
  standalone: true,
  imports: [LeafletDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button type="button" class="back" (click)="closed.emit()">← Volver</button>
    @if (view(); as v) {
      <div class="detail">
        <div class="facts">
          <p class="eyebrow">{{ v.source }}</p>
          <h2>{{ v.place }}</h2>
          <dl>
            <div><dt>País</dt><dd [class.nd]="v.country === 'Sin país asignado'">{{ v.country }}</dd></div>
            <div><dt>Magnitud</dt><dd [class.nd]="v.mag === 'ND'"><span class="big">{{ v.mag }}</span> {{ v.magType }}</dd></div>
            <div><dt>Profundidad</dt><dd [class.nd]="v.depth === 'ND'"><span class="big">{{ v.depth }}</span>@if (v.depth !== 'ND') { km }</dd></div>
            <div><dt>Ocurrencia (UTC)</dt><dd>{{ v.time }}</dd></div>
            <div><dt>Última versión en USGS (UTC)</dt><dd>{{ v.updated }}</dd></div>
            <div><dt>Coordenadas</dt><dd>{{ v.lat }}, {{ v.lon }}</dd></div>
            <div><dt>Identificador</dt><dd class="id">{{ v.id }}</dd></div>
          </dl>
          <p class="help">El país se asigna por punto en polígono contra Natural Earth; «Sin país asignado» significa que el epicentro
            cae fuera de todo polígono (normalmente en el mar). Magnitud o profundidad «ND»: la fuente no la proporciona.</p>
          <a [href]="v.usgs" target="_blank" rel="noopener noreferrer">Ver la ficha oficial en USGS ↗</a>
        </div>
        <div class="map" leaflet [leafletOptions]="v.options" (leafletMapReady)="ready($event, v.layers)" role="region"
             [attr.aria-label]="'Mapa del epicentro de ' + v.place"></div>
      </div>
    }
  `,
  styles: [`
    .back { margin-bottom: 12px; font: inherit; padding: 7px 14px; color: var(--text); background: var(--surface); border: 1px solid var(--border-strong); border-radius: 8px; cursor: pointer; }
    .back:hover { background: var(--border); }
    .back:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
    .detail { display: grid; grid-template-columns: minmax(280px, 1fr) minmax(320px, 1.4fr); gap: 20px; align-items: start; }
    .facts { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }
    .eyebrow { letter-spacing: .12em; font-size: .72rem; font-weight: 700; color: var(--accent); margin: 0; text-transform: uppercase; }
    h2 { margin: 4px 0 14px; font-size: 1.35rem; }
    dl { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 20px; margin: 0 0 12px; }
    dt { font-size: .75rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; } dd { margin: 2px 0 0; overflow-wrap: anywhere; }
    .big { font-family: var(--font-num); font-size: 1.6rem; font-weight: 700; color: var(--text); } dd.nd, dd.nd .big { color: #7b8aa8; font-style: italic; }
    .id { font-family: var(--font-num); font-size: .9rem; }
    .help { font-size: .82rem; color: var(--muted); } a { color: var(--accent); font-weight: 600; }
    .map { height: 420px; border-radius: 12px; border: 1px solid var(--border); background: var(--ocean); }
    @media (max-width: 760px) { .detail { grid-template-columns: 1fr; } .map { height: 300px; } }
  `],
})
export class EventDetailComponent {
  readonly feature = input.required<EventFeature>();
  /** De qué conjunto procede (aparece encima del título). */
  readonly source = input<string>('Evento');
  readonly closed = output<void>();

  protected ready(map: L.Map, layers: L.Layer[]): void {
    for (const layer of layers) layer.addTo(map);
    setTimeout(() => map.invalidateSize(), 0);
  }

  protected readonly view = computed(() => {
    const f = this.feature();
    const p = f.properties;
    const [lon, lat, rawDepth] = f.geometry.coordinates;
    const mag = typeof p.mag === 'number' && Number.isFinite(p.mag) ? p.mag : null;
    const depth = typeof rawDepth === 'number' && Number.isFinite(rawDepth) ? rawDepth : null;
    const color = depthColor(depth);
    const marker = L.circleMarker([lat, lon], {
      radius: Math.max(8, radiusFor(mag)), color: mag === null ? color : '#0a0f1c', fillColor: color, weight: mag === null ? 2 : 1.5, fillOpacity: mag === null ? 0 : 0.92,
    });
    const id = String(f.id ?? 'ND');
    return {
      id, source: this.source(), place: p.place ?? 'Sin descripción',
      country: p.country_name ?? 'Sin país asignado',
      mag: mag === null ? 'ND' : String(mag), magType: mag !== null && p.magType ? `(${p.magType})` : '',
      depth: depth === null ? 'ND' : String(Math.round(depth * 100) / 100),
      time: formatDate(p.time), updated: formatDate(p.updated),
      lat: Math.round(lat * 1e4) / 1e4, lon: Math.round(lon * 1e4) / 1e4,
      usgs: `https://earthquake.usgs.gov/earthquakes/eventpage/${encodeURIComponent(id)}`,
      options: { center: L.latLng(lat, lon), zoom: 6, minZoom: 2, maxZoom: 12 } as L.MapOptions,
      layers: [
        L.tileLayer(DARK_TILES, { maxZoom: 12, maxNativeZoom: 16, attribution: DARK_ATTRIBUTION }),
        marker,
      ] as L.Layer[],
    };
  });
}
