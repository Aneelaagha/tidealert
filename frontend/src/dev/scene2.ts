// DEV ONLY (?dev=1, the "Scene 2" tab). One coordinator, one decision, on the MIXED run (the real Harvey flood with synthetic responders): pick a
// zone, read the Case, see a dispatch warning fire, post a need, take a pledge, ask the Copilot for a briefing. It drives the page the way a person
// would: real clicks, the real slider state, real typing into the real fields. Every need and pledge it writes goes through the real services,
// under the markers "Demo Operator" and "Test Donor", which Reset (and only Reset) deletes.
//
// Honesty rules, enforced here: a step whose target is not on the page, or whose data does not satisfy it, is SKIPPED and reported, never
// replaced by something else; the camera holds where a target is unknown; the Copilot is asked through its Briefing button only (never
// free text), which answers from fixed templates; no step touches money, a real name or a different run.
//
// The narration is read aloud: it is pinned verbatim by test/scene2.test.ts.
import { api, post } from '../lib/api';
import type { Line, PlayerClock, PlayerStep, Tool } from './TimelinePlayer';
import { type MapView, createCamera, frameCenter, geometryCentroid, planMove } from './camera';
import { type HighlightType, type Sel, resolveSel } from './tour';
import { type TypeEnv, chooseOption, setNativeValue, typeInto, untypable } from './typing';

export const OPERATOR_NAME = 'Demo Operator';
export const DONOR_NAME = 'Test Donor';
export const SCENE2_DURATION_S = 116;
/** Hunting Bayou's re-isolation on the mixed run (scripts/mixed_harvey_scenario.py): tasks assigned at 02:30, the zone cut off again at 03:45. */
export const HB_FROM = '2017-08-28T02:30:00Z';
export const HB_TO = '2017-08-28T03:45:00Z';
const HB_GAUGE = /08075770/; // the zone names carry the gauge their Case came from; 08075770 is Hunting Bayou

// ---------------------------------------------------------------- what the page tells the scene (read-only), and the few things it may do
export interface Scene2Facts {
  ready: boolean; // zones, Cases, supply access, tasks and needs have all loaded for the step on screen
  runId: string | null;
  mode: string | null;
  atMs: number | null;
  ticks: number[]; // the run's slider stops, ms
  windowEnd: string | null;
  zones: { id: string; name: string; tasks: number; taskStatus: string | null; access: string | null }[];
  ranked: { zoneId: string; name: string; group: number }[]; // Needs attention, in the order shown
  selectedZoneId: string | null;
  needsWritable: boolean | null;
}
export interface Scene2Host {
  /** Open the mixed Harvey run at its recorded peak, frozen, with the page ready for the scene. null when there is no such run. */
  open(): Promise<{ startMs: number } | null>;
  mixedRunId(): string | null;
  goToTick(i: number): void;
  facts(): Scene2Facts;
  extent(): [number, number, number, number] | null;
  zoneGeometry(id: string): { type?: string; coordinates?: unknown } | null;
  active(on: boolean): void;
}

// ---------------------------------------------------------------- steps
export class Skip extends Error {}
const skip = (why: string): never => { throw new Skip(why); };

interface Env { doc: Document; win: Window & { __map?: unknown }; sleep(ms: number): Promise<void>; log(line: string): void }
export interface Ctx {
  host: Scene2Host; env: Env; facts(): Scene2Facts; q(s: Sel): Element | null; all(s: Sel): Element[]; cancelled(): boolean;
  waitFor(pred: () => boolean, ms?: number): Promise<boolean>; typeEnv: TypeEnv;
  camera: ReturnType<typeof createCamera>; state: Record<string, unknown>;
}
type Finder = (c: Ctx) => Element[];
interface Act { at: number; name: string; run(c: Ctx): Promise<string> }
interface Mark { label: string; find: Finder }
export interface Step { at: number; dur: number; hlFrom?: number; id: string; narration: string; acts: Act[]; highlights: Mark[]; need?: (c: Ctx) => string | null }

const sec = (h: RegExp): Sel => ({ css: 'section h2', match: h, closest: 'section' });
const ATT = sec(/^Needs attention/);
const ZONE = sec(/^Zone$/);
const RESP = sec(/^Responders/);
const COPILOT = sec(/^Copilot/);
const DIALOG = '[role="dialog"][aria-label="Donation portal"]';
const one = (s: Sel): Finder => (c) => { const e = c.q(s); return e ? [e] : []; };
const ddOf = (term: string): Finder => (c) => {
  const dt = c.q({ css: 'dt', match: new RegExp(`^${term}$`), scope: ZONE });
  const dd = dt?.nextElementSibling;
  return dd && dd.getBoundingClientRect().height > 0 ? [dd] : [];
};
const sinceIn = (term: string): Finder => (c) => {
  const dd = ddOf(term)(c)[0];
  const el = dd ? [...dd.querySelectorAll('span')].find((s) => /^since /.test((s.textContent ?? '').trim()) && s.getBoundingClientRect().height > 0) : undefined;
  return el ? [el] : [];
};
const operatorInput: Sel = { css: 'input[placeholder="your name"]' };
const operatorBar = (c: Ctx): Element[] => { const i = c.q(operatorInput); const bar = i?.closest('label')?.parentElement; return bar ? [bar] : []; };
const mapSection = (c: Ctx): Element | null => c.env.doc.querySelector('.maplibregl-canvas')?.closest('section') ?? null;

const huntingIds = (f: Scene2Facts): string[] => f.zones.filter((z) => HB_GAUGE.test(z.name) && z.taskStatus === 'assigned').map((z) => z.id).sort();
const nameOf = (f: Scene2Facts, id: string): string => f.zones.find((z) => z.id === id)?.name ?? id.slice(0, 8);

async function tickTo(c: Ctx, iso: string): Promise<number> {
  const f = c.facts();
  const want = Date.parse(iso);
  const i = f.ticks.indexOf(want);
  if (i < 0) return skip(`the run has no slider stop at ${iso.slice(11, 16)} UTC`);
  c.host.goToTick(i);
  if (!(await c.waitFor(() => { const g = c.facts(); return g.ready && g.atMs === want; }, 9000))) skip(`the page did not finish loading ${iso.slice(11, 16)} UTC`);
  return i;
}
/** Bring a thing into view, smoothly. */
async function scrollTo(el: Element | null, why: string): Promise<void> {
  if (!el) return skip(`${why} is not on the page`);
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
const scrollMap = (c: Ctx) => scrollTo(mapSection(c), 'the map');

/** Move the map to a place computed from the loaded data, or hold (and say so) when the data does not give one. */
async function mapTo(c: Ctx, label: string, where: () => [number, number] | null, zoom: number, mode: 'fly' | 'ease', duration: number): Promise<string> {
  await scrollMap(c);
  const center = where();
  if (!center) { c.camera.hold(label, 'the loaded data does not give this target'); return `held (no target)`; }
  const map = c.env.win.__map as MapView | undefined;
  c.camera.go(label, planMove({ frame: 'zone', zoom, mode, duration }, center, map?.getZoom() ?? zoom));
  return `${mode} to zoom ${zoom} at ${center[0].toFixed(4)}, ${center[1].toFixed(4)}`;
}
const places = (c: Ctx) => ({ extent: () => c.host.extent(), zoneCenter: (id: string) => geometryCentroid(c.host.zoneGeometry(id)) });
const zoneCentre = (c: Ctx, id: string | undefined) => (id ? geometryCentroid(c.host.zoneGeometry(id)) : null);

async function click(el: Element | null, what: string): Promise<void> {
  if (!el) return skip(`${what} is not on the page`);
  if ((el as HTMLButtonElement).disabled) return skip(`${what} is disabled${(el as HTMLElement).title ? `: ${(el as HTMLElement).title}` : ''}`);
  (el as HTMLElement).click();
}
const button = (scope: Sel | null, text: RegExp): Sel => ({ css: 'button', match: text, ...(scope ? { scope } : {}) });
const field = (css: string, scope?: Sel): Sel => ({ css, ...(scope ? { scope } : {}) });

/** A real click on the map at a zone: found by asking the map what is drawn under the point, so only a zone that can really be clicked is clicked. */
async function clickZoneOnMap(c: Ctx, id: string): Promise<string> {
  const map = c.env.win.__map as (MapView & { project(p: [number, number]): { x: number; y: number }; getCanvas(): HTMLCanvasElement;
    queryRenderedFeatures(p: { x: number; y: number }): { properties?: Record<string, unknown> }[] }) | undefined;
  const geom = c.host.zoneGeometry(id) as { coordinates?: unknown } | null;
  const centre = zoneCentre(c, id);
  if (!map || !geom || !centre) return skip('the zone has no drawn shape to click');
  const ring: number[][] = [];
  const dig = (x: unknown): void => { if (Array.isArray(x) && typeof x[0] === 'number') ring.push(x as number[]); else if (Array.isArray(x) && ring.length < 12) x.forEach(dig); };
  dig(geom.coordinates);
  const candidates: [number, number][] = [centre, ...ring.slice(0, 8).map((v): [number, number] => [(v[0] + centre[0]) / 2, (v[1] + centre[1]) / 2])];
  const canvas = map.getCanvas();
  for (const cand of candidates) {
    const p = map.project(cand);
    if (!map.queryRenderedFeatures(p).some((f) => f.properties?.zone_id === id)) continue;
    const r = canvas.getBoundingClientRect();
    const o = { bubbles: true, cancelable: true, button: 0, clientX: r.left + p.x, clientY: r.top + p.y, view: c.env.win };
    for (const type of ['mousedown', 'mouseup', 'click']) canvas.dispatchEvent(new MouseEvent(type, o));
    if (await c.waitFor(() => c.facts().selectedZoneId === id, 2500)) return `clicked the map at the zone ${nameOf(c.facts(), id)}`;
  }
  return skip('no point of the zone could be clicked on the map at this zoom');
}

export const SCENE2: Step[] = [
  { at: 0, dur: 6, id: 'needs-attention', narration: "Let's follow one coordinator through one decision.",
    acts: [{ at: 0, name: 'scroll to Needs attention', run: async (c) => { await scrollTo(c.q(ATT), 'the Needs attention panel'); return 'in view'; } }],
    highlights: [{ label: 'needs-attention-panel', find: one(ATT) }, { label: 'top-zone-row', find: one({ css: 'li button', scope: ATT, nth: 0 }) }] },
  { at: 6, dur: 8, id: 'display-order', narration: "Needs attention puts first the zones that are cut off with nobody assigned, then cut off with someone assigned, then zones that may be cut off. It's a display order, not a risk score.",
    acts: [],
    highlights: [
      { label: 'group-cut-off-nobody', find: one({ css: 'span', match: /^Cut off, nobody assigned$/, scope: ATT }) },
      { label: 'group-cut-off-assigned', find: one({ css: 'span', match: /^Cut off, responder assigned$/, scope: ATT }) },
      { label: 'group-may-be-cut-off', find: one({ css: 'span', match: /^May be cut off$/, scope: ATT }) }] },
  { at: 14, dur: 3, id: 'open-top-zone', narration: "Let's open the first one.",
    acts: [
      { at: 0, name: 'click the top zone row', run: async (c) => {
        const top = c.facts().ranked[0];
        if (!top) return skip('nothing is flagged, so there is no top zone');
        await click(c.q({ css: 'li button', scope: ATT, nth: 0 }), 'the top zone row');
        c.state.top = top.zoneId;
        return `opened ${top.name}`;
      } },
      { at: 0.4, name: 'ease to the zone', run: (c) => mapTo(c, 'open-top-zone', () => zoneCentre(c, c.state.top as string), 13, 'ease', 1400) }],
    highlights: [] },
  { at: 17, dur: 10, id: 'read-the-case', narration: 'Estimated population. Whether a dry route exists. When the road was lost. How sure we are. The Case shows which engine found it and a confidence word. Where data is stale, it says verify.',
    acts: [],
    highlights: [
      { label: 'population', find: ddOf('Population') },
      { label: 'dry-route-status', find: ddOf('Supply access') },
      { label: 'road-lost-time', find: sinceIn('Supply access') },
      { label: 'confidence-word', find: one({ css: 'b', match: /^(corroborated|single_source|stale_verify)$/, scope: ZONE }) },
      { label: 'engine-contributions', find: ddOf('Engines') }] },
  { at: 27, dur: 4, id: 'safety-line', narration: 'Nothing is shown as safe just because we lack data.',
    acts: [],
    highlights: [
      { label: 'confidence-word', find: one({ css: 'b', match: /^(corroborated|single_source|stale_verify)$/, scope: ZONE }) },
      { label: 'stale-verify-marker', find: one({ css: 'b,span', match: /^(stale_verify|verify before dispatch)$/, scope: ZONE }) }] },
  { at: 31, dur: 6, id: 'move-to-hunting-bayou', narration: 'Now dispatch. This is Hunting Bayou.',
    acts: [
      { at: 0, name: `slider to ${HB_FROM.slice(11, 16)}`, run: async (c) => { await tickTo(c, HB_FROM); return `slider at ${HB_FROM.slice(11, 16)} UTC`; } },
      { at: 0.5, name: 'fly to Hunting Bayou', run: (c) => {
        const ids = huntingIds(c.facts());
        return mapTo(c, 'move-to-hunting-bayou', () => (ids.length ? frameCenter('zones', ids, places(c)) : null), 13, 'fly', 1600);
      } }],
    highlights: [] },
  { at: 37, dur: 6, id: 'three-tasks', narration: 'At 2:30, three tasks were assigned, because the zone had reconnected at 2:15.',
    acts: [],
    need: (c) => { const n = huntingIds(c.facts()).length; return n === 3 ? null : `${n} Hunting Bayou zones have an assigned task at 02:30, not three`; },
    highlights: [{ label: 'responders-panel', find: one(RESP) }] },
  // (hlFrom: the boxes start once the slider has arrived and the warnings have loaded)
  { at: 43, dur: 10, hlFrom: 3, id: 'warning-fires', narration: "By 3:45 it's cut off again, and the task shows a warning: isolated after assignment. A responder is told before driving in, not after.",
    acts: [{ at: 0, name: `slider ${HB_FROM.slice(11, 16)} to ${HB_TO.slice(11, 16)}`, run: async (c) => {
      const f = c.facts();
      const from = f.ticks.indexOf(Date.parse(HB_FROM)), to = f.ticks.indexOf(Date.parse(HB_TO));
      if (from < 0 || to <= from) return skip('the run has no slider stops for 02:30 to 03:45');
      const n = to - from;
      for (let i = from + 1; i <= to; i++) { if (c.cancelled()) break; c.host.goToTick(i); await c.env.sleep(2000 / n); }
      if (!(await c.waitFor(() => { const g = c.facts(); return g.ready && g.atMs === Date.parse(HB_TO); }, 9000))) return skip('the page did not finish loading 03:45 UTC');
      return `${n} ticks of 15 min over 2 s, ending at ${HB_TO.slice(11, 16)} UTC`;
    } }],
    highlights: [0, 1, 2].map((n) => ({ label: `isolated-after-assignment-${n + 1}`, find: one({ css: 'span', match: /after the responder was assigned/, scope: RESP, closest: 'div', nth: n }) })) },
  { at: 53, dur: 6, id: 'verify-rule', narration: "Whenever a zone reconnects, its tasks are flagged verify before dispatch. A reopened road isn't the same as a safe road.",
    acts: [], highlights: [] },
  { at: 59, dur: 4, id: 'honesty-label', narration: 'These assignments are scripted and synthetic. The flood they respond to is real.',
    acts: [{ at: 0, name: 'scroll to the top', run: async (c) => { c.env.win.scrollTo({ top: 0, behavior: 'smooth' }); return 'top of the page'; } }],
    highlights: [{ label: 'mixed-badge', find: one({ css: 'header span[title]', match: /^MIXED: REAL FLOOD \+ SYNTHETIC RESPONDERS$/ }) }] },
  { at: 63, dur: 6, id: 'operator-name', narration: 'People in a cut-off zone need more than a dispatch decision. They need supplies.',
    acts: [
      { at: 0, name: 'scroll to the Operator bar', run: async (c) => { await scrollTo(operatorBar(c)[0] ?? null, 'the Operator bar'); return 'in view'; } },
      { at: 0.7, name: `type "${OPERATOR_NAME}"`, run: async (c) => `typed ${JSON.stringify(await typeInto(c.q(operatorInput), OPERATOR_NAME, 2000, c.typeEnv, 'Operator'))}` }],
    highlights: [{ label: 'operator-bar', find: operatorBar }] },
  { at: 69, dur: 5, id: 'open-cut-off-zone', narration: 'The operator opens the zone and posts a need.',
    acts: [
      { at: 0, name: 'scroll to the map', run: async (c) => { await scrollMap(c); return 'in view'; } },
      { at: 0.8, name: 'click a cut-off zone on the map', run: async (c) => {
        const f = c.facts();
        const cut = f.zones.filter((z) => z.access === 'isolated').map((z) => z.id).sort();
        const pick = huntingIds(f).find((id) => cut.includes(id)) ?? cut[0];
        if (!pick) return skip('no zone is cut off at this time');
        const said = await clickZoneOnMap(c, pick);
        c.state.cutOff = pick;
        return said;
      } }],
    highlights: [] },
  { at: 74, dur: 8, id: 'post-a-need', narration: 'Water, forty units. Recorded as entered by an operator, not measured.',
    acts: [{ at: 0, name: 'enter a need for water', run: async (c) => {
      const id = c.state.cutOff as string | undefined;
      if (!id) return skip('no cut-off zone was opened');
      if (!(await c.waitFor(() => !!c.q(field('select[aria-label="Item"]', ZONE)) && c.facts().needsWritable === true, 5000))) return skip('the needs form is not on the page, or the run refuses entries');
      const item = c.q(field('select[aria-label="Item"]', ZONE)) as HTMLSelectElement;
      if (!chooseOption(item, 'water')) return skip('the item list has no water');
      await c.env.sleep(300);
      const typed = await typeInto(c.q(field('input[aria-label="Quantity"]', ZONE)), '40', 1000, c.typeEnv, 'Quantity');
      await c.env.sleep(250);
      await click(c.q(button(ZONE, /^Enter$/)), 'the Enter button');
      if (!(await c.waitFor(() => /40 open/.test(c.q({ css: 'ul', match: /water/i, scope: ZONE })?.textContent ?? ''), 5000))) return skip('the new need did not appear in the zone panel');
      return `water ${typed} in ${nameOf(c.facts(), id)}, stamped with the slider time`;
    } }],
    highlights: [{ label: 'needs-block', find: one({ css: 'b', match: /^Needs$/, scope: ZONE, closest: 'div.my-2' }) }] },
  { at: 82, dur: 5, id: 'open-the-portal', narration: 'The portal lists open needs, cut-off zones first.',
    acts: [{ at: 0, name: 'click the donation portal button', run: async (c) => {
      await click(c.q(button(null, /Donation portal/)), 'the portal button');
      if (!(await c.waitFor(() => !!c.env.doc.querySelector(DIALOG), 3000))) return skip('the portal did not open');
      return 'portal open';
    } }],
    highlights: [] },
  { at: 87, dur: 8, id: 'pledge', narration: 'A neighbor picks a need, enters a quantity, and pledges. It records a pledge, not a delivery.',
    acts: [{ at: 0, name: `pledge as "${DONOR_NAME}"`, run: async (c) => {
      const id = c.state.cutOff as string | undefined;
      if (!id) return skip('no cut-off zone was opened');
      const dialog: Sel = { css: DIALOG };
      if (!(await c.waitFor(() => !!c.q(dialog), 3000))) return skip('the portal is not open');
      const zone = nameOf(c.facts(), id);
      const rowQty = field(`input[aria-label="Quantity of water for ${zone}"]`, dialog);
      if (!c.q(rowQty)) return skip('the portal lists no open water need for that zone');
      const row = c.q(rowQty)!.closest('li');
      const before = /(\d[\d,]*) still needed/.exec(row?.textContent ?? '')?.[1] ?? 'unknown';
      const offersBefore = Number(/Offers \((\d+)\)/.exec(c.env.doc.querySelector(DIALOG)?.textContent ?? '')?.[1] ?? NaN);
      const donor = await typeInto(c.q(field('input[placeholder^="shown with your offer"]', dialog)), DONOR_NAME, 1000, c.typeEnv, 'Donor');
      await c.env.sleep(250);
      const qty = await typeInto(c.q(rowQty), '25', 1000, c.typeEnv, 'Pledge quantity');
      await c.env.sleep(250);
      const offer = [...(row?.querySelectorAll('button') ?? [])].find((b) => /^Offer$/.test((b.textContent ?? '').trim())) ?? null;
      await click(offer, 'the Offer button');
      const offers = () => Number(/Offers \((\d+)\)/.exec(c.env.doc.querySelector(DIALOG)?.textContent ?? '')?.[1] ?? NaN);
      if (!(await c.waitFor(() => offers() === offersBefore + 1, 5000))) return skip('the pledge did not appear in the portal');
      const after = /(\d[\d,]*) still needed/.exec(c.q(field(`input[aria-label="Quantity of water for ${zone}"]`, dialog))?.closest('li')?.textContent ?? '')?.[1] ?? 'none left';
      return `${donor} offered ${qty} water; still needed ${before} -> ${after}`;
    } }],
    highlights: [] },
  { at: 95, dur: 6, id: 'honesty-banner', narration: 'No money, no card, no donor name, no leaderboard.',
    acts: [],
    highlights: [{ label: 'portal-banner', find: one({ css: 'p', match: /No money is taken/, scope: { css: DIALOG } }) }] },
  { at: 101, dur: 4, id: 'payoff', narration: 'This is where goodwill becomes something a coordinator can plan around.',
    acts: [
      { at: 0, name: 'close the portal', run: async (c) => {
        await click(c.q({ css: 'button[aria-label="Close"]', scope: { css: DIALOG } }), 'the portal Close button');
        if (!(await c.waitFor(() => !c.env.doc.querySelector(DIALOG), 2000))) return skip('the portal did not close');
        return 'portal closed';
      } },
      { at: 0.4, name: 'ease out to the metro', run: (c) => mapTo(c, 'payoff', () => frameCenter('metro', [], places(c)), 10, 'ease', 2000) }],
    highlights: [] },
  { at: 105, dur: 6, id: 'copilot-briefing', narration: "The coordinator can ask the Copilot for a briefing. It answers only from this run's data, so it can't invent a status.",
    acts: [
      { at: 0, name: 'scroll to the Copilot', run: async (c) => { await scrollTo(c.q(COPILOT), 'the Copilot panel'); return 'in view'; } },
      { at: 1, name: 'click the Briefing button', run: async (c) => {
        const b = c.q({ css: 'button', match: /^briefing$/i, scope: COPILOT });
        await click(b, 'the Briefing button');
        if (!(await c.waitFor(() => /DRAFT RESPONDER BRIEFING/.test(c.q(COPILOT)?.textContent ?? ''), 8000))) return skip('the briefing did not come back');
        return 'template briefing returned (no model call)';
      } }],
    highlights: [] },
  { at: 111, dur: 5, id: 'close', narration: "TideAlert doesn't promise rescue. It helps people decide, and it says what it doesn't know.",
    acts: [{ at: 0, name: 'ease out to the full metro', run: (c) => mapTo(c, 'close', () => frameCenter('metro', [], places(c)), 10, 'ease', 1800) }],
    highlights: [] },
];

export const SCENE2_STEPS: PlayerStep[] = SCENE2.map((s) => ({ at: s.at, label: s.id }));

// ---------------------------------------------------------------- the runner
export interface LogRow { step: string; kind: 'act' | 'highlight'; name: string; ok: boolean; value: string }
export interface Scene2 extends Tool { log(): LogRow[]; reset(): Promise<string>; precheck(): Promise<string | null> }
export interface Scene2Ui { highlight(items: { el: Element; type: HighlightType; label: string }[]): void }

/** True when part of an element is outside the window, or outside a scrolling panel it sits in: its highlight box would point at blank space. */
export function clippedBy(el: Element, win: Pick<Window, 'innerHeight' | 'getComputedStyle'>): boolean {
  const r = el.getBoundingClientRect();
  if (r.top < 0 || r.bottom > win.innerHeight) return true;
  for (let p = el.parentElement; p; p = p.parentElement) {
    const o = win.getComputedStyle(p).overflowY;
    if (o !== 'auto' && o !== 'scroll' && o !== 'hidden') continue;
    const pr = p.getBoundingClientRect();
    if (r.top < pr.top - 1 || r.bottom > pr.bottom + 1) return true;
  }
  return false;
}

export function createScene2(host: Scene2Host, ui: Scene2Ui, clock: PlayerClock, steps: Step[] = SCENE2, env?: Partial<Env>): Scene2 {
  const e: Env = {
    doc: env?.doc ?? document, win: env?.win ?? (window as Env['win']),
    sleep: env?.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms))),
    log: env?.log ?? ((l) => console.info(l)),
  };
  let cancelled = false;
  let gen = 0; // bumped on stop, so a step still running from the last play cannot touch the next one
  const rows: LogRow[] = [];
  const started = new Set<number>();
  const skippedSteps = new Set<string>();
  const seen = new Map<string, Set<number>>();
  const reportedHl = new Set<string>();
  let shown = '';
  const state: Record<string, unknown> = {};
  const camera = createCamera(() => (e.win.__map as MapView | undefined) ?? null, (d) => {
    const line = `[scene2] camera ${d.label}: ${d.move ? `${d.move.mode} to zoom ${d.move.zoom} over ${d.move.duration} ms` : d.note}`;
    if (d.move) e.log(line); else console.warn(line);
  }, () => performance.now());
  const typeEnv: TypeEnv = { sleep: e.sleep, log: e.log, cancelled: () => cancelled };
  const ctx: Ctx = {
    host, env: e, facts: () => host.facts(), q: (s) => resolveSel(s, e.doc),
    all: (s) => { const out: Element[] = []; for (let n = 0; n < 12; n++) { const x = resolveSel({ ...s, nth: n }, e.doc); if (!x) break; out.push(x); } return out; },
    cancelled: () => cancelled, typeEnv, camera, state,
    async waitFor(pred, ms = 4000) { const end = performance.now() + ms; while (performance.now() < end) { if (cancelled) return false; if (pred()) return true; await e.sleep(80); } return pred(); },
  };

  function record(step: string, kind: LogRow['kind'], name: string, ok: boolean, value: string) {
    rows.push({ step, kind, name, ok, value });
    const line = `[scene2] ${step} ${kind} ${name}: ${ok ? value : `SKIPPED, ${value}`}`;
    if (ok) e.log(line); else console.warn(line);
  }

  async function runActs(i: number, g: number) {
    const step = steps[i];
    const reason = step.need?.(ctx) ?? null; // checked when the step starts, against the data on screen
    if (reason) { skippedSteps.add(step.id); record(step.id, 'highlight', 'step', false, reason); }
    for (const act of step.acts) {
      while (!cancelled && g === gen && clock.time() < step.at + act.at) await e.sleep(40);
      if (cancelled || g !== gen) return;
      try { record(step.id, 'act', act.name, true, await act.run(ctx)); }
      catch (err) {
        skippedSteps.add(step.id);
        record(step.id, 'act', act.name, false, err instanceof Skip ? err.message : `failed: ${err instanceof Error ? err.message : String(err)}`);
        if (!(err instanceof Skip)) throw err;
      }
    }
  }

  function showHighlights(t: number) {
    const i = steps.findIndex((s) => t >= s.at && t < s.at + s.dur);
    if (i < 0 || (skippedSteps.has(steps[i].id) && steps[i].need)) { if (shown) { ui.highlight([]); shown = ''; } return; }
    const s = steps[i];
    if (!s.highlights.length) { if (shown) { ui.highlight([]); shown = ''; } return; }
    const from = s.hlFrom ?? 0;
    if (t - s.at < from) { if (shown) { ui.highlight([]); shown = ''; } return; }
    const k = Math.min(Math.floor(((t - s.at - from) / (s.dur - from)) * s.highlights.length), s.highlights.length - 1);
    const m = s.highlights[k];
    const els = m.find(ctx);
    if (els.length) {
      const set = seen.get(s.id) ?? new Set<number>(); set.add(k); seen.set(s.id, set);
      const key = `${s.id}:${k}:${els.length}`;
      if (key !== shown) {
        shown = key;
        if (clippedBy(els[0], e.win)) els[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
        ui.highlight(els.map((el, n) => ({ el, type: 'outline' as HighlightType, label: els.length > 1 ? `${m.label} ${n + 1}` : m.label })));
      }
    } else if (shown) { ui.highlight([]); shown = ''; }
  }
  function settleHighlights(t: number) {
    for (const s of steps) {
      if (t < s.at + s.dur) continue;
      s.highlights.forEach((m, k) => {
        const key = `${s.id}:${k}`;
        if (reportedHl.has(key) || seen.get(s.id)?.has(k) || (s.need && skippedSteps.has(s.id))) return;
        reportedHl.add(key);
        record(s.id, 'highlight', m.label, false, 'the element was not on the page when its turn came');
      });
    }
  }

  const g0 = () => gen;
  return {
    title: 'Scene 2',
    steps: SCENE2_STEPS,
    duration: SCENE2_DURATION_S,
    start() { cancelled = false; gen += 1; started.clear(); skippedSteps.clear(); seen.clear(); reportedHl.clear(); rows.length = 0; shown = ''; for (const k of Object.keys(state)) delete state[k]; camera.clear(); },
    tick() {
      const t = clock.time();
      steps.forEach((s, i) => { if (t >= s.at && !started.has(i)) { started.add(i); void runActs(i, g0()).catch((err) => console.error('[scene2] step failed', s.id, err)); } });
      showHighlights(t);
      settleHighlights(t);
    },
    seek() { /* a scene that writes rows is played from the top: Restart, not skip */ },
    stop() { cancelled = true; gen += 1; ui.highlight([]); shown = ''; camera.stop(); },
    line(t: number): Line | null {
      let i = -1;
      steps.forEach((s, k) => { if (s.at <= t) i = k; });
      if (i < 0) return null;
      return { text: steps[i].narration, skipped: skippedSteps.has(steps[i].id) };
    },
    finished: () => clock.time() >= SCENE2_DURATION_S,
    log: () => [...rows],
    async precheck() {
      // The scene's rows are tagged; if an earlier play's rows are still there the numbers on screen would not match the narration.
      const runId = host.mixedRunId();
      if (!runId) return 'There is no mixed Harvey run in this database.';
      const f = host.facts();
      const board = await api.needs(runId, f.windowEnd);
      const zones = Object.values(board.zones);
      const left = zones.reduce((n, z) => n + z.events.filter((x) => x.actor === OPERATOR_NAME).length + z.pledges.filter((p) => p.donor === DONOR_NAME).length, 0);
      return left > 0 ? `${left} demo rows from an earlier play are still on the board. Press Reset first, so the numbers match the narration.` : null;
    },
    async reset() { return resetDemo(host, e.doc); },
  };
}

/** Delete the rows the scene wrote (the server deletes by the two markers only) and clear the Operator field if it still holds the demo name. */
export async function resetDemo(host: Scene2Host, doc: Document = document): Promise<string> {
  const runId = host.mixedRunId();
  if (!runId) return 'There is no mixed Harvey run to reset.';
  try {
    const r = await post<{ pledges_deleted: number; need_entries_deleted: number }>('/needs/dev-reset', { run_id: runId });
    const input = doc.querySelector<HTMLInputElement>('input[placeholder="your name"]');
    if (input && input.value === OPERATOR_NAME && !untypable(input)) setNativeValue(input, '');
    const line = `Reset: removed ${r.need_entries_deleted} need entries and ${r.pledges_deleted} pledges written as "${OPERATOR_NAME}" / "${DONOR_NAME}". Anything else was left alone.`;
    console.info(`[scene2] ${line}`);
    return line;
  } catch (err) {
    const m = err instanceof Error ? err.message : String(err);
    return /404|Not found/i.test(m) ? 'Reset is off: start the API with TIDEALERT_DEV_RESET=1.' : `Reset failed: ${m}`;
  }
}
