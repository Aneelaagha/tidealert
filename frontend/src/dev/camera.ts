// DEV ONLY (the conductor, ?dev=1). The camera layer for the conductor's beats: every step that talks about a place moves the MapLibre camera there
// once, then holds. Where it goes comes from the loaded data (a zone's own centroid, the run's extent), never from a typed coordinate; if a step's
// target is unknown the camera HOLDS and the skip is logged. The guided tour has its own camera path (tour.ts) and does not use this.
//
// Rules, all enforced here: zoom is capped at 16; pitch is 0 and bearing 0 unless a step sets them; a move starts at least 800 ms after the
// previous one ended (a later move replaces one still waiting); a short move eases and a long one flies unless the step names its verb.

export const ZOOM_CEILING = 16;
export const MIN_HOLD_MS = 800;
export const DEFAULT_DURATION_MS = 1200;
export const FLY_ABOVE_ZOOM_DELTA = 1; // longer than one zoom level: flyTo, else easeTo

export type Frame = 'metro' | 'metro-north' | 'zone' | 'zones';
/** A step's camera, in words: where to look (a frame resolved from the data), how close, and how. */
export interface CameraSpec {
  frame: Frame;
  zoom: number;
  pitch?: number; // default 0
  bearing?: number; // default 0
  duration?: number; // ms, default 1200
  easing?: 'ease-out' | 'ease-in-out' | 'linear'; // default 'ease-out'
  mode?: 'fly' | 'ease' | 'jump'; // default: chosen from the zoom change
}
export interface CameraMove { center: [number, number]; zoom: number; pitch: number; bearing: number; duration: number; easing: NonNullable<CameraSpec['easing']>; mode: 'fly' | 'ease' | 'jump' }

/** What a frame needs from the page: the run's zone extent and a zone's centroid. */
export interface Places { extent(): [number, number, number, number] | null; zoneCenter(zoneId: string): [number, number] | null }

/** Where a frame points, from the data; null when the data does not say. */
export function frameCenter(frame: Frame, zoneIds: string[], p: Places): [number, number] | null {
  if (frame === 'metro' || frame === 'metro-north') {
    const e = p.extent();
    if (!e) return null;
    const cx = (e[0] + e[2]) / 2;
    return frame === 'metro' ? [cx, (e[1] + e[3]) / 2] : [cx, (((e[1] + e[3]) / 2) + e[3]) / 2]; // the northern half's centre
  }
  if (zoneIds.length === 0) return null;
  const cs = zoneIds.map((z) => p.zoneCenter(z));
  if (cs.some((c) => c === null)) return null;
  const pts = cs as [number, number][];
  if (frame === 'zone') return pts[0];
  return [pts.reduce((a, c) => a + c[0], 0) / pts.length, pts.reduce((a, c) => a + c[1], 0) / pts.length]; // 'zones': the midpoint of them all
}

/** Turn a spec into a move: clamp the zoom, fill the defaults, pick fly or ease from the zoom change. */
export function planMove(spec: CameraSpec, center: [number, number], currentZoom: number): CameraMove {
  const zoom = Math.min(spec.zoom, ZOOM_CEILING);
  const mode = spec.mode ?? (Math.abs(zoom - currentZoom) > FLY_ABOVE_ZOOM_DELTA ? 'fly' : 'ease');
  return { center, zoom, pitch: spec.pitch ?? 0, bearing: spec.bearing ?? 0, duration: spec.duration ?? DEFAULT_DURATION_MS, easing: spec.easing ?? 'ease-out', mode };
}

const EASE = { 'ease-out': (t: number) => 1 - (1 - t) ** 3, 'ease-in-out': (t: number) => (t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2), linear: (t: number) => t };

/** The geometric centroid of a zone's polygon (its largest ring for a multipolygon), from its own coordinates. */
export function geometryCentroid(geom: { type?: string; coordinates?: unknown } | null | undefined): [number, number] | null {
  const rings: number[][][] = [];
  const c = geom?.coordinates as unknown;
  if (geom?.type === 'Polygon' && Array.isArray(c)) rings.push(c[0] as number[][]);
  else if (geom?.type === 'MultiPolygon' && Array.isArray(c)) for (const poly of c as number[][][][]) rings.push(poly[0]);
  let best: { area: number; cx: number; cy: number } | null = null;
  for (const r of rings) {
    let a = 0, cx = 0, cy = 0;
    for (let i = 0; i < r.length - 1; i++) {
      const [x0, y0] = r[i], [x1, y1] = r[i + 1];
      const f = x0 * y1 - x1 * y0;
      a += f; cx += (x0 + x1) * f; cy += (y0 + y1) * f;
    }
    if (a === 0) continue;
    const cand = { area: Math.abs(a / 2), cx: cx / (3 * a), cy: cy / (3 * a) };
    if (!best || cand.area > best.area) best = cand;
  }
  return best ? [best.cx, best.cy] : null;
}

export interface MapView {
  getZoom(): number; getCenter(): { lng: number; lat: number }; getPitch(): number; getBearing(): number;
  flyTo(o: Record<string, unknown>): void; easeTo(o: Record<string, unknown>): void; jumpTo(o: Record<string, unknown>): void; stop(): void;
}
export interface Done { label: string; move: CameraMove | null; note?: string }

/** Runs moves on a map with the hold rule. `now` and `later` are injectable so tests control time. */
export function createCamera(getMap: () => MapView | null, log: (done: Done) => void = () => {}, now: () => number = () => performance.now(),
                             later: (fn: () => void, ms: number) => unknown = (fn, ms) => setTimeout(fn, ms), cancel: (h: unknown) => void = (h) => clearTimeout(h as ReturnType<typeof setTimeout>)) {
  let busyUntil = -Infinity; // when the last move ends
  let pending: { label: string; move: CameraMove; timer: unknown } | null = null;
  const moves: Done[] = [];

  function run(label: string, m: CameraMove) {
    const map = getMap();
    if (!map) { const d = { label, move: null, note: 'no map' }; moves.push(d); log(d); return; }
    const to = { center: m.center, zoom: m.zoom, pitch: m.pitch, bearing: m.bearing, duration: m.duration, easing: EASE[m.easing], essential: true };
    if (m.mode === 'jump' || m.duration === 0) { map.jumpTo(to); busyUntil = now(); }
    else { (m.mode === 'fly' ? map.flyTo : map.easeTo).call(map, to); busyUntil = now() + m.duration; }
    const d = { label, move: m }; moves.push(d); log(d);
  }
  return {
    /** Move now, or after the hold if the last move ended less than MIN_HOLD_MS ago. A move still waiting is replaced by this one. */
    go(label: string, m: CameraMove) {
      if (pending) { cancel(pending.timer); const d = { label: pending.label, move: null, note: `replaced by ${label} before it started` }; moves.push(d); log(d); pending = null; }
      const wait = m.mode === 'jump' || m.duration === 0 ? 0 : Math.max(busyUntil + MIN_HOLD_MS - now(), 0);
      if (wait === 0) { run(label, m); return; }
      pending = { label, move: m, timer: later(() => { pending = null; run(label, m); }, wait) };
    },
    /** The target is unknown: hold the view and say so. */
    hold(label: string, why: string) { const d = { label, move: null, note: `held: ${why}` }; moves.push(d); log(d); },
    stop() { if (pending) { cancel(pending.timer); pending = null; } getMap()?.stop(); busyUntil = -Infinity; },
    moves: () => [...moves],
    clear() { moves.length = 0; },
  };
}
