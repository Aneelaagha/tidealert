// DEV ONLY (?tour=1 in a Vite dev build). The guided tour: camera choreography, panel highlights and a read-along narration line for
// filming a standalone walkthrough. It changes NO app state: it never clicks, opens a panel, moves the slider or picks a layer. It moves the
// MapLibre camera, scrolls the page, and draws outline boxes in its own overlay layer above the page. Everything a step points at is found
// in the page by a selector; a selector that finds nothing is SKIPPED and reported, and nothing else is highlighted in its place.
//
// Required start (checked before Play; the tour refuses to start otherwise): the Harvey REPLAY at 2017-08-28 05:15 UTC with the
// "Supply access" map colouring selected. Open it by hand first (see TOUR_START).
//
// The narration is read aloud verbatim: it is pinned by tests and must not be edited without approval.
import type { Line, PlayerClock, PlayerStep, Tool } from './TimelinePlayer';

export const TOUR_START_AT = '2017-08-28T05:15:00Z';
export const TOUR_DURATION_S = 84;

// ---------------------------------------------------------------- finding things in the page
/** A selector: CSS, optionally filtered by the element's text, scoped inside another selector, and lifted to an ancestor. */
export interface Sel { css: string; match?: RegExp; scope?: Sel; closest?: string; nth?: number }

const OWN = '[data-dev-player],[data-dev-highlights],[data-dev-caption]';
const squash = (s: string | null) => (s ?? '').replace(/\s+/g, ' ').trim();

/** The first visible element a selector finds, or null. A hidden element (no size) does not count as found. */
export function resolveSel(sel: Sel, doc: Document | Element = document): Element | null {
  const root: Document | Element | null = sel.scope ? resolveSel(sel.scope, doc) : doc;
  if (!root) return null;
  // Never the dev tools' own panel, highlight boxes or caption: their text (the narration) would match selectors meant for the app.
  const found = [...root.querySelectorAll(sel.css)].filter((e) => !e.closest?.(OWN) && (!sel.match || sel.match.test(squash(e.textContent))));
  const el = found[sel.nth ?? 0];
  const target = el ? (sel.closest ? el.closest(sel.closest) : el) : null;
  if (!target) return null;
  const r = target.getBoundingClientRect();
  return r.width > 0 && r.height > 0 ? target : null;
}

export const describeSel = (s: Sel): string =>
  `${s.scope ? `${describeSel(s.scope)} › ` : ''}${s.css}${s.match ? ` /${s.match.source}/` : ''}${s.closest ? ` ⤴ ${s.closest}` : ''}${s.nth ? ` #${s.nth}` : ''}`;

// ---------------------------------------------------------------- the timeline
export type HighlightType = 'pulse' | 'outline' | 'dim' | 'clear';
export interface Highlight { sel: Sel; type: HighlightType; label: string }
/** One camera move inside a step, `frac` of the way through it. fit: the zones' extent or the densest cluster of cut-off zones. */
export type CameraMove =
  | { frac?: number; top: true }
  | { frac?: number; fit: 'zones' | 'cluster'; zoomDelta?: number; jump?: boolean; pan?: 'west' | 'east'; share?: number }
  | { frac?: number; scroll: Sel; label: string };

export interface TourStep {
  at: number; dur: number; id: string;
  narration: string;
  caption?: string;
  camera: CameraMove[]; // empty: hold
  highlights: Highlight[]; // shown one at a time, in order, each for an equal share of the step; empty: none
}

const H1 = { css: 'header h1', match: /^TideAlert$/i } as const;
const BADGE: Sel = { css: 'header span[title]', match: /^REPLAY$/ };
const legend = (re: RegExp, label: string): Highlight => ({ sel: { css: 'span[title$="people recorded in these zones"]', match: re }, type: 'pulse', label });
const section = (heading: RegExp): Sel => ({ css: 'section h2', match: heading, closest: 'section' });
const AERIAL: Sel = { css: 'section[aria-label="Aerial priority"]' };
const CASES: Sel = section(/^Cases/);

export const TOUR: TourStep[] = [
  { id: 'the-problem', at: 0, dur: 5, camera: [{ top: true, frac: 0 }, { fit: 'zones', jump: true, frac: 0 }], highlights: [],
    narration: "When a flood hits, the people who need help most are often the ones who can't call for it. Roads go under, phones fail, and nobody knows who is cut off." },
  { id: 'who-it-is-for', at: 5, dur: 5, camera: [],
    highlights: [{ sel: H1, type: 'pulse', label: 'TideAlert logo' }, { sel: BADGE, type: 'pulse', label: 'REPLAY badge' }],
    narration: 'TideAlert is a flood emergency platform for the coordinators who run the response, the responders deciding who to reach first, and the neighbors and relief groups who want to help.' },
  { id: 'harvey', at: 10, dur: 6, camera: [{ fit: 'zones', zoomDelta: 0.3 }],
    highlights: [{ sel: { css: '[data-tour="flood-polygons"]' }, type: 'outline', label: 'the flood polygons' }],
    narration: 'This is Hurricane Harvey. The flood is real: USGS river gauge records, with each gauge showing how fresh its data is and flagging stale readings in red.' },
  { id: 'what-is-synthetic', at: 16, dur: 3, camera: [],
    highlights: [{ sel: BADGE, type: 'pulse', label: 'REPLAY badge' }, { sel: { css: 'div[aria-live="polite"]', match: /synthetic/i }, type: 'outline', label: 'the synthetic-data note in the banner' }],
    narration: 'Anything involving people, like households and responders, is synthetic, and the badge says so.' },
  { id: 'the-colors', at: 19, dur: 12, camera: [{ fit: 'cluster', pan: 'west', frac: 0 }, { fit: 'cluster', pan: 'east', frac: 0.35 }],
    highlights: [legend(/^cut off\b/, 'legend: red, cut off'), legend(/^may be cut off\b/, 'legend: orange, may be cut off'), legend(/^reconnected\b/, 'legend: blue, reconnected'),
                 legend(/^reachable\b/, 'legend: green, reachable (a dry route)'), legend(/^not assessed\b/, 'legend: grey, not assessed')],
    narration: 'Every shape on the map is a street block, built from OpenStreetMap roads, with population estimated from 2020 Census blocks shared out by area. The colors show supply access. Red means no dry road out. Orange means it may be cut off. Blue means reconnected, which is the optimistic bound. Green means a dry route exists. Grey means not assessed, and never safe.' },
  { id: 'a-modeled-result', at: 31, dur: 7, camera: [],
    highlights: [{ sel: { css: '.maplibregl-map' }, type: 'outline', label: 'the map' }, { sel: { css: 'div[aria-live="polite"] b', match: /flagged zone/ }, type: 'pulse', label: 'top banner cut-off count' }],
    narration: "A flood model reads the gauge heights, terrain elevation and the road network to work this out, so it's a modeled result and not an observation. It checks route feasibility only, because we have no depot data." },
  { id: 'last-call', at: 38, dur: 7, camera: [{ scroll: { css: 'section[aria-label="Last call"]' }, label: 'the Last call panel' }],
    highlights: [{ sel: { css: 'section[aria-label="Last call"] .grid' }, type: 'pulse', label: 'lead-time inputs' }, { sel: { css: 'ol[aria-label="Soonest last call first"]' }, type: 'outline', label: 'countdown list' }],
    narration: "Last call is the model's cut-off time minus a lead time you type in. In a replay, those cut-off times are known in hindsight, so a live system would need a river forecast." },
  { id: 'needs-attention', at: 45, dur: 3, camera: [],
    highlights: [{ sel: section(/^Needs attention/), type: 'outline', label: 'Needs attention panel' }],
    narration: 'Needs attention is a display order, not a risk score.' },
  { id: 'aerial-priority', at: 48, dur: 14, camera: [{ scroll: AERIAL, label: 'the Aerial priority panel' }],
    highlights: [{ sel: { css: 'h2', scope: AERIAL }, type: 'pulse', label: 'panel title' }, { sel: { css: 'ol[aria-label="Aerial priority, highest first"]', scope: AERIAL }, type: 'outline', label: 'ranked rows' },
                 { sel: { css: ':scope > p:last-of-type', scope: AERIAL }, type: 'outline', label: 'provenance line' }],
    narration: "Aerial priority answers one question: which cut-off zones should someone look at from the air first? It takes the zones the isolation engine has marked as having no dry road out, and ranks them. On a replay of real data, the ranking is by how long a zone has been cut off. On this mixed run, it's by silent households, which are synthetic here. Cell coverage is not assessed, because we have no coverage data, so the ranking leaves it out instead of guessing. It's a ranking only. No asset is tasked by this system, and a person makes every call." },
  { id: 'a-case', at: 62, dur: 10, camera: [{ scroll: { css: 'div[class*="border-l-4"]', scope: CASES }, label: 'the first Case card' }],
    highlights: [{ sel: { css: 'p.font-sans', scope: CASES }, type: 'dim', label: 'inference sentence' }, { sel: { css: 'div[class*="border-l-4"] > div:first-child > span:first-child', scope: CASES }, type: 'pulse', label: 'confidence word' },
                 { sel: { css: 'summary', match: /^Evidence/ }, type: 'outline', label: 'engine contributions' }],
    narration: 'Each zone can open a Case, which combines what the engines found. Isolation uses the real flood data. The silence and listening engines run on synthetic households here, because no real household registry or SMS exists. Every Case carries a confidence word, never a percentage.' },
  { id: 'responders-needs', at: 72, dur: 8, camera: [{ scroll: { css: '.responder-marker' }, label: 'the responder markers' }],
    highlights: [{ sel: { css: '.responder-marker' }, type: 'pulse', label: 'synthetic responder markers' }, { sel: { css: 'div', match: /^NEEDS\b/ }, type: 'outline', label: 'needs strip' }],
    narration: 'The responders you see are synthetic. Needs are typed in by an operator, and pledges are test entries. No money is stored, no payment is processed, and no personal details are kept.' },
  { id: 'now-the-demo', at: 80, dur: 4, camera: [{ top: true, frac: 0 }, { fit: 'zones', frac: 0 }], highlights: [],
    narration: 'Now let me show you how it works.' },
];

export const TOUR_STEPS: PlayerStep[] = TOUR.map((s) => ({ at: s.at, label: s.id }));

// ---------------------------------------------------------------- the start check
export interface StartState { mode: string | null; event: string | null; at: string | null; layer: string | null; ready: boolean; runId: string | null }

/** The reason the tour cannot start from this page, or null when it can. Tells the person exactly what to open. */
export function refusal(s: StartState, pathname = '/ui/'): string | null {
  const url = s.runId ? `${pathname}?tour=1&run=${s.runId}&at=${encodeURIComponent('2017-08-28T05:15:00.000Z')}` : `${pathname}?tour=1`;
  const found: string[] = [];
  if (s.mode !== 'replay' || !s.event?.includes('Harvey')) found.push(`the run on screen is ${s.mode ? `a ${s.mode.toUpperCase()} run${s.event ? ` (${s.event})` : ''}` : 'not loaded yet'}, not the Harvey REPLAY`);
  else if (!s.at || Date.parse(s.at) !== Date.parse(TOUR_START_AT)) found.push(`the time on screen is ${s.at ? new Date(s.at).toISOString().slice(0, 16).replace('T', ' ') : 'not loaded'} UTC, not 2017-08-28 05:15 UTC`);
  else if (s.layer !== 'supply') found.push('the map is not coloured by Supply access');
  else if (!s.ready) found.push('the page is still loading this time step');
  return found.length === 0 ? null
    : `The guided tour starts only on the Harvey REPLAY at 2017-08-28 05:15 UTC with "Colour zones by: Supply access". Here ${found[0]}. Open ${url}, choose Supply access, then press Play. Nothing was changed.`;
}

// ---------------------------------------------------------------- where the camera goes, from the data
/** The densest cluster of points on a grid of `cell` degrees: its bounds [w, s, e, n]. Ties go to the first cell in key order, so it is the same every run. */
export function densestCluster(points: [number, number][], cell = 0.04): [number, number, number, number] | null {
  const bins = new Map<string, [number, number][]>();
  for (const p of points) { const k = `${Math.floor(p[0] / cell)}:${Math.floor(p[1] / cell)}`; bins.set(k, [...(bins.get(k) ?? []), p]); }
  let best: { k: string; pts: [number, number][] } | null = null;
  for (const [k, pts] of [...bins].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) if (!best || pts.length > best.pts.length) best = { k, pts };
  if (!best) return null;
  const xs = best.pts.map((p) => p[0]), ys = best.pts.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

// ---------------------------------------------------------------- the runner
export interface MapLike {
  cameraForBounds(b: [[number, number], [number, number]], o: { padding: number; maxZoom: number }): { center: unknown; zoom: number } | undefined;
  flyTo(o: Record<string, unknown>): void; easeTo(o: Record<string, unknown>): void; jumpTo(o: Record<string, unknown>): void; stop(): void;
  getCenter(): { lng: number; lat: number }; getZoom(): number; getPitch(): number; getBearing(): number;
}
export interface TourHost {
  start(): StartState;
  map(): MapLike | null;
  extent(): [number, number, number, number] | null; // the run's zones' extent (from /runs)
  cutOffPoints(): [number, number][]; // a point inside each zone the engine finds cut off at this time
}
export interface TourUi { highlight(items: { el: Element; type: HighlightType; label: string }[]): void; caption(text: string | null): void }
export interface ReportRow { step: number; id: string; kind: 'highlight' | 'camera'; label: string; selector: string; resolved: boolean }
export interface Snap { step: number; center: [number, number]; zoom: number; pitch: number; bearing: number; scrollY: number; shown: string[] }
export interface Tour extends Tool { report(): ReportRow[]; snaps(): Snap[]; refusal(): string | null }

const PAD = 40; // the same padding the map uses when it frames the zones
const r6 = (n: number) => Math.round(n * 1e5) / 1e5; // 1 m: the camera animation settles to within a millionth of a degree between runs

export interface Env { win: { scrollTo(o: ScrollToOptions): void; scrollY: number }; doc: Document | Element }

export function createTour(host: TourHost, ui: TourUi, clock: PlayerClock, steps: TourStep[] = TOUR, env?: Env): Tour {
  const { win, doc } = env ?? { win: window, doc: document };
  let entered = -1;
  let shownIdx = -1;
  let shown: string[] = [];
  let over = false;
  let rows: ReportRow[] = [];
  let snaps: Snap[] = [];
  const timers: ReturnType<typeof setTimeout>[] = [];
  const clearTimers = () => { while (timers.length) clearTimeout(timers.pop()!); };

  const note = (n: number, kind: ReportRow['kind'], label: string, sel: Sel, resolved: boolean) => {
    rows = [...rows.filter((r) => !(r.step === n && r.kind === kind && r.label === label)), { step: n, id: steps[n].id, kind, label, selector: describeSel(sel), resolved }];
  };

  function snap(n: number) {
    const m = host.map();
    if (!m || n < 0) return;
    const c = m.getCenter();
    snaps = [...snaps.filter((s) => s.step !== n), { step: n, center: [r6(c.lng), r6(c.lat)], zoom: r6(m.getZoom()), pitch: r6(m.getPitch()), bearing: r6(m.getBearing()), scrollY: Math.round(win.scrollY), shown: [...shown] }];
  }

  function target(move: Extract<CameraMove, { fit: unknown }>): { center: [number, number]; zoom: number } | null {
    const m = host.map();
    const bounds = move.fit === 'zones' ? host.extent() : densestCluster(host.cutOffPoints());
    if (!m || !bounds) return null;
    const cam = m.cameraForBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], { padding: PAD, maxZoom: 15 });
    if (!cam) return null;
    let c = cam.center as { lng: number; lat: number } | [number, number];
    c = Array.isArray(c) ? c : [c.lng, c.lat];
    const span = bounds[2] - bounds[0];
    const share = move.share ?? 0.25;
    const lng = move.pan === 'west' ? bounds[0] + span * share : move.pan === 'east' ? bounds[2] - span * share : c[0];
    return { center: [lng, c[1]], zoom: cam.zoom + (move.zoomDelta ?? 0) };
  }

  function move(n: number, mv: CameraMove, jump: boolean) {
    const step = steps[n];
    const ms = (frac: number) => Math.max(step.dur * 1000 * frac / clock.speed, 400);
    if ('top' in mv) { win.scrollTo({ top: 0, behavior: jump ? 'auto' : 'smooth' }); return; }
    if ('scroll' in mv) {
      const el = resolveSel(mv.scroll, doc);
      note(n, 'camera', mv.label, mv.scroll, !!el);
      if (el) el.scrollIntoView({ behavior: jump ? 'auto' : 'smooth', block: 'center' });
      return;
    }
    const t = target(mv);
    note(n, 'camera', mv.pan ? `fit ${mv.fit} (${mv.pan})` : `fit ${mv.fit}`, { css: `map: ${mv.fit}` }, !!t);
    const m = host.map();
    if (!t || !m) return;
    const to = { center: t.center, zoom: t.zoom, pitch: 0, bearing: 0 };
    if (jump || mv.jump) m.jumpTo(to);
    else if (mv.pan) m.easeTo({ ...to, duration: ms(mv.frac === 0 ? 0.3 : 1 - (mv.frac ?? 0)), essential: true });
    else m.flyTo({ ...to, duration: ms(0.8), essential: true });
  }

  function showHighlight(n: number, k: number) {
    const h = steps[n].highlights[k];
    if (!h) { shown = []; ui.highlight([]); return; }
    const el = h.type === 'clear' ? null : resolveSel(h.sel, doc);
    note(n, 'highlight', h.label, h.sel, h.type === 'clear' || !!el);
    shown = el ? [h.label] : [];
    ui.highlight(el && h.type !== 'clear' ? [{ el, type: h.type, label: h.label }] : []);
  }

  function enter(n: number, jump: boolean) {
    clearTimers();
    if (entered >= 0 && entered !== n) snap(entered);
    entered = n; shownIdx = -1; shown = [];
    ui.highlight([]);
    ui.caption(steps[n].caption ?? null);
    const step = steps[n];
    for (const mv of step.camera) {
      const at = jump ? 0 : (mv.frac ?? 0) * step.dur * 1000 / clock.speed;
      if (at <= 0) move(n, mv, jump); else timers.push(setTimeout(() => move(n, mv, false), at));
    }
  }

  return {
    title: 'Guided tour',
    steps: TOUR_STEPS,
    duration: TOUR_DURATION_S,
    refusal: () => refusal(host.start()),
    report: () => [...rows].sort((a, b) => a.step - b.step),
    snaps: () => [...snaps].sort((a, b) => a.step - b.step),
    start() { rows = []; snaps = []; over = false; host.map()?.stop(); enter(0, true); },
    tick() {
      if (over || !clock.isPlaying) return;
      const t = clock.time();
      if (t >= TOUR_DURATION_S) { snap(entered); clearTimers(); ui.highlight([]); ui.caption(null); over = true; return; }
      let n = -1;
      for (let i = 0; i < steps.length; i++) if (steps[i].at <= t) n = i;
      if (n < 0) return;
      if (n !== entered) enter(n, false);
      const hs = steps[n].highlights;
      if (hs.length === 0) { if (shownIdx !== -2) { shownIdx = -2; ui.highlight([]); } return; }
      const k = Math.min(Math.floor((t - steps[n].at) / (steps[n].dur / hs.length)), hs.length - 1);
      if (k !== shownIdx) { shownIdx = k; showHighlight(n, k); }
    },
    seek(i) {
      host.map()?.stop(); over = false;
      clock.seek(steps[i].at);
      enter(i, true);
    },
    stop() { clearTimers(); host.map()?.stop(); ui.highlight([]); ui.caption(null); entered = -1; shownIdx = -1; shown = []; over = true; },
    line(t): Line | null {
      let n = -1;
      for (let i = 0; i < steps.length; i++) if (steps[i].at <= t) n = i;
      return n < 0 ? null : { text: steps[n].narration, sub: undefined };
    },
    finished: () => over,
  };
}
