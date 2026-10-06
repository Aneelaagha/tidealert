// The map: the run's zones as of the slider time, styled from each zone's own fields (COLORS), plus one task marker
// per zone with an active task at the API's task_anchor. Shapes come from the database geometry and the view from
// the run's extent. The grid texture and radar sweep on top are decoration and never block clicks.

import maplibregl, { type GeoJSONSource, type StyleSpecification } from 'maplibre-gl';
import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import type { DepotAccess, Run, SupplyAccess, ZonesResponse } from '../lib/api';
import { onPulse } from '../lib/pulse';
import { DEM_TILES, EASE_MS, PITCH_3D, loadThreeD, saveThreeD, terrainSpec } from '../lib/terrain';
import { GAP_COLOR, SELECTED_COLOR, TASK_RADIUS, TASK_VERIFY_EDGE, matchColor } from '../lib/colors';

const STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster', tileSize: 256,
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  },
  // OSM tiles darkened and desaturated for the dark theme.
  layers: [{ id: 'osm', type: 'raster', source: 'osm',
             paint: { 'raster-saturation': -0.85, 'raster-brightness-max': 0.38, 'raster-contrast': 0.1 } }],
};

const EMPTY = { type: 'FeatureCollection' as const, features: [] };

/** The "3D" button, in the same group as the zoom buttons. Its on/off state lives in the component; this is only the button. */
class ThreeDControl implements maplibregl.IControl {
  private el: HTMLDivElement | null = null;
  constructor(private onToggle: (on: boolean) => void, private initial: boolean) {}
  onAdd() {
    const el = document.createElement('div');
    el.className = 'maplibregl-ctrl maplibregl-ctrl-group';
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'map3d-btn'; b.textContent = '3D'; b.setAttribute('aria-label', '3D terrain');
    b.setAttribute('aria-pressed', String(this.initial));
    let on = this.initial;
    b.addEventListener('click', () => { on = b.getAttribute('aria-pressed') !== 'true'; this.onToggle(on); });
    el.appendChild(b);
    this.el = el;
    return el;
  }
  onRemove() { this.el?.remove(); this.el = null; }
}

function hatchImage() {
  const size = 8, data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    if ((x + y) % size < 2) data.set([139, 152, 169, 210], (y * size + x) * 4);
  }
  return { width: size, height: size, data };
}

function addLayers(map: maplibregl.Map) {
  map.addSource('zones', { type: 'geojson', data: EMPTY, promoteId: 'zone_id' });
  map.addImage('hatch', hatchImage());
  const color = (f: Parameters<typeof matchColor>[0]) => matchColor(f) as maplibregl.ExpressionSpecification;
  map.addLayer({ id: 'zone-fill', type: 'fill', source: 'zones', paint: {
    'fill-color': color('risk_level'),
    'fill-opacity': ['case', ['==', ['get', 'risk_level'], 'unknown'], 0.12, 0.45],
  } });
  // Coverage gap: hatched and dashed, so a zone without real signal looks different instead of being left out.
  map.addLayer({ id: 'zone-gap-hatch', type: 'fill', source: 'zones', filter: ['==', ['get', 'coverage_gap_active'], true],
    paint: { 'fill-pattern': 'hatch', 'fill-opacity': 0.55 } });
  map.addLayer({ id: 'zone-edge', type: 'line', source: 'zones',
    paint: { 'line-color': '#64748b', 'line-width': 0.4, 'line-opacity': 0.7 } });
  map.addLayer({ id: 'zone-gap-edge', type: 'line', source: 'zones', filter: ['==', ['get', 'coverage_gap_active'], true],
    paint: { 'line-color': GAP_COLOR, 'line-width': 1, 'line-dasharray': [2, 2] } });
  map.addLayer({ id: 'case-outline', type: 'line', source: 'zones',
    filter: ['all', ['>', ['get', 'case_count'], 0], ['!=', ['get', 'confidence_word'], 'stale_verify']],
    paint: { 'line-color': color('confidence_word'), 'line-width': 3 } });
  map.addLayer({ id: 'case-outline-stale', type: 'line', source: 'zones',
    filter: ['all', ['>', ['get', 'case_count'], 0], ['==', ['get', 'confidence_word'], 'stale_verify']],
    paint: { 'line-color': color('confidence_word'), 'line-width': 2.5, 'line-dasharray': [1.5, 1] } });
  map.addLayer({ id: 'zone-selected', type: 'line', source: 'zones', filter: ['==', ['get', 'zone_id'], ''],
    paint: { 'line-color': SELECTED_COLOR, 'line-width': 3 } });
  map.addSource('tasks', { type: 'geojson', data: EMPTY });
  map.addLayer({ id: 'task-marker', type: 'circle', source: 'tasks', paint: {
    'circle-color': color('task_status'),
    'circle-radius': ['match', ['get', 'task_priority'], ...Object.entries(TASK_RADIUS).flat(), 7] as unknown as maplibregl.ExpressionSpecification,
    'circle-stroke-color': ['case', ['get', 'task_verify'], TASK_VERIFY_EDGE, '#0f172a'],
    'circle-stroke-width': ['case', ['get', 'task_verify'], 3, 1.5],
  } });
}

interface Props {
  run: Run | null;
  zones: ZonesResponse | null;
  selectedZoneId: string | null;
  onSelectZone: (zoneId: string | null) => void;
  layer: 'risk' | 'supply' | 'depot'; // what the zone fill shows
  depot?: DepotAccess | null; // the depot-access answer for the same run and time (needed when layer is 'depot')
  refit?: number; // bump to frame the zones again (the Start here preset)
  flat?: boolean; // force the flat 2D camera (the auto-advance demo runs in 2D)
  pulseNew?: boolean; // ring a zone's marker when its first task appears (only while the replay clock is moving)
  children?: ReactNode; // overlays drawn on the map (the legend)
  supply: SupplyAccess | null; // the supply-access answer for the same run and time (needed when layer is 'supply')
}

const FILL_OPACITY: Record<'risk' | 'supply' | 'depot', unknown[]> = {
  depot: ['case', ['in', ['get', 'depot_access'], ['literal', ['not_evaluated', 'outside_network']]], 0.12, ['==', ['get', 'depot_access'], null], 0, 0.55],
  risk: ['case', ['==', ['get', 'risk_level'], 'unknown'], 0.12, 0.45],
  // null = this zone has no entry yet (the answer for this time is still loading): not drawn rather than guessed.
  supply: ['case', ['==', ['get', 'supply_access'], 'not_evaluated'], 0.12, ['==', ['get', 'supply_access'], null], 0, 0.55],
};

/** The west, south, east, north of every zone drawn, or null when there are none. */
export function boundsOf(zones: ZonesResponse): [number, number, number, number] | null {
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  const visit = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === 'number') {
      const [x, y] = c as number[];
      w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y);
    } else if (Array.isArray(c)) c.forEach(visit);
  };
  for (const f of zones.features) visit((f.geometry as { coordinates?: unknown }).coordinates);
  return Number.isFinite(w) ? [w, s, e, n] : null;
}

export function ZoneMap({ run, zones, selectedZoneId, onSelectZone, layer, supply, depot = null, refit = 0, pulseNew = false, flat = false, children }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const onSelect = useRef(onSelectZone);
  onSelect.current = onSelectZone;
  const [ready, setReady] = useState(false);
  // 3D terrain: off by default, remembered across reloads, and always off while `flat` (the demo driver). The elevation source is
  // added at style load but only fetches tiles while terrain is on.
  const [threeD, setThreeD] = useState(loadThreeD);
  const camera2d = useRef<{ pitch: number; bearing: number } | null>(null);

  useEffect(() => {
    const map = new maplibregl.Map({ container: container.current!, style: STYLE, center: [0, 0], zoom: 1 });
    map.addControl(new maplibregl.NavigationControl(), 'top-left');
    map.addControl(new ThreeDControl((on) => { setThreeD(on); saveThreeD(on); }, loadThreeD()), 'top-left');
    // Start on "style.load", not "load": "load" waits for a rendered frame, which a background tab never draws.
    map.once('style.load', () => {
      map.addSource('dem', { type: 'raster-dem', encoding: 'terrarium', tiles: [DEM_TILES], tileSize: 256, maxzoom: 15,
                             attribution: 'Terrain: <a href="https://registry.opendata.aws/terrain-tiles/">AWS Terrain Tiles</a>' });
      addLayers(map);
      const pick = (e: maplibregl.MapLayerMouseEvent) => onSelect.current(String(e.features?.[0]?.properties?.zone_id ?? ''));
      map.on('click', 'task-marker', pick);
      map.on('click', 'zone-fill', pick);
      map.on('mouseenter', 'zone-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'zone-fill', () => { map.getCanvas().style.cursor = ''; });
      setReady(true);
    });
    mapRef.current = map;
    if (import.meta.env.DEV) (window as unknown as { __map?: maplibregl.Map }).__map = map; // dev only: lets a browser check read the camera
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  const on3d = threeD && !flat;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (on3d) {
      camera2d.current ??= { pitch: map.getPitch(), bearing: map.getBearing() };
      map.setTerrain(terrainSpec());
      map.easeTo({ pitch: PITCH_3D, duration: EASE_MS });
    } else if (map.getTerrain()) {
      map.setTerrain(null);
      map.easeTo({ pitch: camera2d.current?.pitch ?? 0, bearing: camera2d.current?.bearing ?? map.getBearing(), duration: EASE_MS });
      camera2d.current = null;
    }
    const b = container.current?.querySelector<HTMLButtonElement>('.map3d-btn');
    if (b) { b.setAttribute('aria-pressed', String(on3d)); b.classList.toggle('map3d-on', on3d); b.disabled = flat; b.title = flat ? '3D is off while the demo runs' : on3d ? 'Back to the flat map' : 'Tilt the map: terrain, 55° pitch'; }
  }, [on3d, flat, ready]);

  // Fit the view to the zones that loaded for the run (once per run, not on every slider tick). The run's extent
  // is only a first guess: the zones are what is drawn. A run with no zones has nothing to frame (see `note`).
  const fitted = useRef<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => { fitted.current = null; setNote(null); }, [run?.id, refit]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !run || !zones || zones.run_id !== run.id) return;
    const box = boundsOf(zones);
    if (!box) { setNote('No zones to show for this run.'); return; }
    // Synthetic scenario zones are placed at about 0°N 0°E: they have no real-world location, and a basemap there is
    // open ocean. Say so rather than show an empty globe.
    setNote(box[0] > -1 && box[2] < 1 && box[1] > -1 && box[3] < 1 ? 'Synthetic zones: they have no real-world location, so there is no basemap here.' : null);
    if (fitted.current === run.id) return;
    fitted.current = run.id;
    map.fitBounds([[box[0], box[1]], [box[2], box[3]]], { padding: 40, duration: 0, maxZoom: 15 });
  }, [zones, run]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    // The supply layer joins the second API answer to the zones by id; a zone it has no entry for stays null and
    // draws UNSTYLED, so a gap in the answer is visible, never given a state.
    const joinTo = (prop: string, value: (id: string) => string | null) => zones && ({ ...zones, features: zones.features.map((f) => ({ ...f,
      properties: { ...f.properties, [prop]: value(f.properties.zone_id) } })) });
    const supplyOk = !!supply && !!zones && supply.run_id === zones.run_id && supply.at === zones.at;
    // A depot answer covers the zones of one basin's network; a zone it has no entry for is "outside_network", and while the
    // answer for this time is loading it is null (not drawn) rather than guessed.
    const depotOk = !!depot && !!zones && depot.run_id === zones.run_id && Date.parse(depot.at) === Date.parse(zones.at);
    const shown = layer === 'supply' ? joinTo('supply_access', (id) => (supplyOk ? supply!.zones[id]?.zone_access ?? null : null))
      : layer === 'depot' ? joinTo('depot_access', (id) => (depotOk ? depot!.zones[id] ?? 'outside_network' : null))
      : zones;
    (map.getSource('zones') as GeoJSONSource).setData((shown ?? EMPTY) as GeoJSON.FeatureCollection);
    const withTask = (zones?.features ?? []).filter((f) => f.properties.task_count > 0 && f.properties.task_anchor);
    (map.getSource('tasks') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: withTask.map((f) => ({
        type: 'Feature', geometry: { type: 'Point', coordinates: f.properties.task_anchor! },
        properties: { zone_id: f.properties.zone_id, task_status: f.properties.task_status,
                      task_priority: f.properties.task_priority, task_verify: f.properties.task_verify },
      })),
    });
  }, [zones, ready, layer, supply, depot]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const field = layer === 'supply' ? 'supply_access' : layer === 'depot' ? 'depot_access' : 'risk_level';
    map.setPaintProperty('zone-fill', 'fill-color', matchColor(field) as maplibregl.ExpressionSpecification);
    map.setPaintProperty('zone-fill', 'fill-opacity', FILL_OPACITY[layer] as maplibregl.ExpressionSpecification);
  }, [layer, ready]);

  // One-shot rings: from the marker of a zone whose first task just appeared while the playhead moves, and on request (lib/pulse).
  const [rings, setRings] = useState<{ key: number; x: number; y: number }[]>([]);
  const ringKey = useRef(0);
  const anchors = useRef(new Map<string, [number, number]>());
  const taskZones = useRef<Set<string> | null>(null);
  const ring = useCallback((zoneId: string) => {
    const map = mapRef.current, a = anchors.current.get(zoneId);
    if (!map || !a) return;
    const p = map.project(a);
    const key = ++ringKey.current;
    setRings((rs) => [...rs.slice(-11), { key, x: p.x, y: p.y }]);
    window.setTimeout(() => setRings((rs) => rs.filter((r) => r.key !== key)), 1200);
  }, []);
  useEffect(() => onPulse(ring), [ring]);
  useEffect(() => {
    anchors.current = new Map((zones?.features ?? []).filter((f) => f.properties.task_count > 0 && f.properties.task_anchor)
      .map((f) => [f.properties.zone_id, f.properties.task_anchor as [number, number]]));
    const now = new Set(anchors.current.keys());
    if (pulseNew && taskZones.current) [...now].filter((z) => !taskZones.current!.has(z)).slice(0, 12).forEach(ring);
    taskZones.current = now;
  }, [zones, pulseNew, ring]);
  useEffect(() => { taskZones.current = null; }, [run?.id]);

  useEffect(() => {
    if (ready) mapRef.current?.setFilter('zone-selected', ['==', ['get', 'zone_id'], selectedZoneId ?? '']);
  }, [selectedZoneId, ready]);

  return (
    <div className="relative h-full w-full overflow-hidden bg-navy-deep">
      {/* h-full, not absolute: MapLibre's CSS sets position: relative on its container. */}
      <div ref={container} className="h-full w-full" />
      <div className="pointer-events-none absolute inset-0 cyber-grid opacity-40" aria-hidden="true" />
      {children}
      {rings.map((r) => <span key={r.key} className="pulse-ring" style={{ left: r.x, top: r.y }} aria-hidden="true" />)}
      {note && (
        <div className="pointer-events-none absolute inset-x-0 top-4 flex justify-center px-4">
          <p className="rounded border border-white/15 bg-navy-deep/90 px-3 py-1.5 text-center text-xs text-slate-300">{note}</p>
        </div>
      )}
    </div>
  );
}
