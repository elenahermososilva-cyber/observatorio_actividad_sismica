import { ChangeDetectionStrategy, Component, NgZone, effect, inject, input, output, signal } from '@angular/core';
import { LeafletDirective } from '@bluehalo/ngx-leaflet';
import * as L from 'leaflet';
import type { FeatureCollection } from 'geojson';
import type { EventCollection, EventFeature } from './models';

export const NO_DATA_COLOR = '#64748b';

/** Mapa base oscuro «Canvas Dark Gray» de Esri (ArcGIS Online). Se consulta sin clave de API; los mapas de CARTO ya la exigen. */
export const DARK_TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
/** Solo se piden teselas dentro del mundo: fuera de él Esri devolvería losas grises. */
export const WORLD = L.latLngBounds([-85.06, -180], [85.06, 180]);
export const DARK_ATTRIBUTION = 'Mapa base &copy; <a href="https://www.esri.com">Esri</a>, HERE, Garmin, &copy; OpenStreetMap contributors';

export function depthColor(depth: number | null): string {
  if (depth === null) return NO_DATA_COLOR;
  return depth < 70 ? '#fde047' : depth < 300 ? '#fb923c' : '#c084fc';
}

export function radiusFor(magnitude: number | null): number {
  return magnitude === null ? 4 : Math.max(3, Math.min(18, 3 + (magnitude + 1) * 2));
}

export function formatDate(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'ND';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'ND' : date.toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC');
}

/** Mapa Leaflet con fondo, fronteras y terremotos en capas independientes. Solo dibuja lo que recibe de la API. */
@Component({
  selector: 'app-event-map',
  standalone: true,
  imports: [LeafletDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="map" leaflet [leafletOptions]="options" (leafletMapReady)="onMapReady($event)" role="region"
         aria-label="Mapa interactivo de terremotos. La tabla de eventos ofrece los mismos datos en formato de texto."></div>
    <div class="legend" aria-label="Leyenda del mapa">
      <strong>Profundidad (color)</strong>
      <span><i class="dot" style="background:#fde047"></i>Menos de 70 km</span>
      <span><i class="dot" style="background:#fb923c"></i>70–299,99 km</span>
      <span><i class="dot" style="background:#c084fc"></i>300 km o más</span>
      <span><i class="dot" style="background:#64748b"></i>Profundidad ND</span>
      <strong>Magnitud (tamaño)</strong>
      <span><i class="dot" style="width:8px;height:8px;background:#94a3bf"></i>M 3</span>
      <span><i class="dot" style="width:14px;height:14px;background:#94a3bf"></i>M 5</span>
      <span><i class="dot" style="width:22px;height:22px;background:#94a3bf"></i>M 7</span>
      <span><i class="dot nd"></i><b>ND</b>: magnitud no disponible (círculo hueco de radio mínimo)</span>
    </div>
    <p class="note">El tamaño crece con la magnitud, pero no representa energía ni área afectada. El mapa base y las fronteras se pueden desactivar en el selector de capas.</p>
  `,
  styles: [`
    .map { height: 56vh; min-height: 340px; background: var(--ocean); border: 1px solid var(--border); border-radius: 12px; }
    .legend { display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: center; padding: 10px 0 0; font-size: .88rem; color: var(--muted); }
    .legend strong { color: var(--text); }
    .legend span { display: inline-flex; align-items: center; gap: 6px; }
    .dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; border: 1px solid #0a0f1c; }
    .dot.nd { width: 10px; height: 10px; background: transparent; border: 2px solid #64748b; }
    .note { font-size: .82rem; color: var(--muted); margin: 6px 0 0; }
  `],
})
export class EventMapComponent {
  readonly events = input.required<EventCollection | null>();
  readonly countries = input<FeatureCollection | null>(null);
  /** Número de eventos con coordenadas inválidas que no se pudieron dibujar. */
  readonly omitted = output<number>();
  /** Evento elegido desde su ventana emergente («Ver ficha»). */
  readonly picked = output<EventFeature>();
  /** Si el mapa está en una pestaña oculta, Leaflet no conoce su tamaño: al volver a mostrarse se recalcula. */
  readonly visible = input<boolean>(true);
  private readonly zone = inject(NgZone);
  readonly drawn = signal(0);

  readonly options: L.MapOptions = { center: L.latLng(18, 0), zoom: 2, minZoom: 2, maxZoom: 8, preferCanvas: true, worldCopyJump: false };

  private readonly map = signal<L.Map | null>(null);
  private readonly eventLayer = L.layerGroup();
  private readonly borders = L.geoJSON(undefined, {
    style: { color: '#7c8db0', weight: 0.8, opacity: 0.55, fill: false },
    onEachFeature: (feature, layer) => {
      const name = document.createElement('span');
      name.textContent = feature.properties?.NAME_ES ?? feature.properties?.ADMIN ?? 'Sin nombre';
      layer.bindTooltip(name);
    },
  });

  constructor() {
    effect(() => {
      const catalogue = this.countries();
      if (!this.map() || !catalogue) return;
      this.borders.clearLayers();
      this.borders.addData(catalogue);
    });
    effect(() => {
      const map = this.map();
      if (map && this.visible()) setTimeout(() => map.invalidateSize(), 0);
    });
    effect(() => {
      const collection = this.events();
      if (!this.map() || !collection) return;
      this.draw(collection);
    });
  }

  onMapReady(map: L.Map): void {
    const base = L.tileLayer(DARK_TILES, { maxZoom: 8, maxNativeZoom: 16, noWrap: true, bounds: WORLD, attribution: DARK_ATTRIBUTION }).addTo(map);
    this.borders.addTo(map);
    this.eventLayer.addTo(map);
    L.control.layers({ 'Esri Canvas Dark Gray': base }, { 'Países (Natural Earth)': this.borders, 'Terremotos': this.eventLayer }).addTo(map);
    map.attributionControl.addAttribution('Fronteras: Natural Earth · Datos: USGS');
    this.map.set(map);
  }

  private draw(collection: EventCollection): void {
    // Se construye la capa nueva completa antes de sustituir la anterior: si algo falla, se conserva la que había.
    const next = L.layerGroup();
    let omitted = 0;
    let count = 0;
    for (const feature of collection.features) {
      const p = feature.properties;
      const [lon, lat, rawDepth] = feature.geometry?.type === 'Point' ? feature.geometry.coordinates : [];
      if (!p || !Number.isFinite(lon) || !Number.isFinite(lat) || Math.abs(lon) > 180 || Math.abs(lat) > 90) { omitted++; continue; }
      const magnitude = typeof p.mag === 'number' && Number.isFinite(p.mag) ? p.mag : null;
      const depth = typeof rawDepth === 'number' && Number.isFinite(rawDepth) ? rawDepth : null;
      const color = depthColor(depth);
      const popup = document.createElement('div');
      const text = document.createElement('div');
      text.style.whiteSpace = 'pre-line';
      popup.appendChild(text);
      const more = document.createElement('button');
      more.type = 'button';
      more.textContent = 'Ver ficha completa →';
      more.style.cssText = 'margin-top:8px;padding:5px 12px;border:1px solid #22d3ee;border-radius:8px;background:#22d3ee;color:#062a33;cursor:pointer;font:inherit;font-weight:700';
      more.addEventListener('click', () => this.zone.run(() => this.picked.emit(feature as EventFeature)));
      popup.appendChild(more);
      text.textContent =
        `${p.place ?? 'Sin descripción'}\nMagnitud: ${magnitude ?? 'ND'}${p.magType ? ' (' + p.magType + ')' : ''}\n` +
        `Profundidad: ${depth === null ? 'ND' : depth + ' km'}\nFecha UTC: ${formatDate(p.time)}\n` +
        `Última actualización UTC: ${formatDate(p.updated)}\nPaís: ${p.country_name ?? 'Sin país asignado'}\nID: ${feature.id ?? 'ND'}`;
      L.circleMarker([lat, lon], {
        // Borde oscuro de 1 px y relleno casi opaco: cada epicentro se ve nítido y separado de los vecinos (sin halo difuso).
        radius: radiusFor(magnitude), color: magnitude === null ? color : '#0a0f1c', fillColor: color, weight: magnitude === null ? 2 : 1,
        fillOpacity: magnitude === null ? 0 : 0.92, opacity: 1, dashArray: magnitude === null ? '3 2' : undefined,
      }).bindPopup(popup).addTo(next);
      count++;
    }
    this.eventLayer.clearLayers();
    this.eventLayer.addLayer(next);
    this.drawn.set(count);
    this.omitted.emit(omitted);
  }
}
