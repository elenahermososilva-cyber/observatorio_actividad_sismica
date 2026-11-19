import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { LeafletDirective } from '@bluehalo/ngx-leaflet';
import * as L from 'leaflet';
import type { EventFeature } from './models';
import { depthColor, formatDate, radiusFor } from './event-map.component';

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
    .back { margin-bottom: 12px; }
    .detail { display: grid; grid-template-columns: minmax(280px, 1fr) minmax(320px, 1.4fr); gap: 20px; align-items: start; }
    .facts { background: white; border-radius: 10px; padding: 16px 18px; }
    .eyebrow { letter-spacing: .12em; font-size: .72rem; font-weight: 700; color: #176b70; margin: 0; text-transform: uppercase; }
    h2 { margin: 4px 0 14px; font-size: 1.35rem; }
    dl { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 20px; margin: 0 0 12px; }
    dt { font-size: .75rem; color: #42596b; text-transform: uppercase; letter-spacing: .04em; } dd { margin: 2px 0 0; overflow-wrap: anywhere; }
    .big { font-size: 1.6rem; font-weight: 700; color: #132b40; } dd.nd, dd.nd .big { color: #64748b; font-style: italic; }
    .id { font-family: ui-monospace, monospace; font-size: .9rem; }
    .help { font-size: .82rem; color: #42596b; } a { color: #176b70; font-weight: 600; }
    .map { height: 420px; border-radius: 10px; background: #dceaf1; }
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
      radius: Math.max(8, radiusFor(mag)), color, fillColor: color, weight: 2, fillOpacity: mag === null ? 0 : 0.7,
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
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        }),
        marker,
      ] as L.Layer[],
    };
  });
}
