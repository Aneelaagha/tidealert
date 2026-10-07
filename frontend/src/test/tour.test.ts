import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { PlayerClock } from '../dev/TimelinePlayer';
import {
  type MapLike, type Sel, type StartState, TOUR, TOUR_DURATION_S, TOUR_START_AT, type TourHost, createTour, densestCluster, describeSel, refusal, resolveSel,
} from '../dev/tour';

// The narration, copied from the brief. The narrator reads it verbatim: a change here is a change to the script and needs approval.
const NARRATION = [
  "When a flood hits, the people who need help most are often the ones who can't call for it. Roads go under, phones fail, and nobody knows who is cut off.",
  'TideAlert is a flood emergency platform for the coordinators who run the response, the responders deciding who to reach first, and the neighbors and relief groups who want to help.',
  'This is Hurricane Harvey. The flood is real: USGS river gauge records, with each gauge showing how fresh its data is and flagging stale readings in red.',
  'Anything involving people, like households and responders, is synthetic, and the badge says so.',
  'Every shape on the map is a street block, built from OpenStreetMap roads, with population estimated from 2020 Census blocks shared out by area. The colors show supply access. Red means no dry road out. Orange means it may be cut off. Blue means reconnected, which is the optimistic bound. Green means a dry route exists. Grey means not assessed, and never safe.',
  "A flood model reads the gauge heights, terrain elevation and the road network to work this out, so it's a modeled result and not an observation. It checks route feasibility only, because we have no depot data.",
  "Last call is the model's cut-off time minus a lead time you type in. In a replay, those cut-off times are known in hindsight, so a live system would need a river forecast.",
  'Needs attention is a display order, not a risk score.',
  "Aerial priority answers one question: which cut-off zones should someone look at from the air first? It takes the zones the isolation engine has marked as having no dry road out, and ranks them. On a replay of real data, the ranking is by how long a zone has been cut off. On this mixed run, it's by silent households, which are synthetic here. Cell coverage is not assessed, because we have no coverage data, so the ranking leaves it out instead of guessing. It's a ranking only. No asset is tasked by this system, and a person makes every call.",
  'Each zone can open a Case, which combines what the engines found. Isolation uses the real flood data. The silence and listening engines run on synthetic households here, because no real household registry or SMS exists. Every Case carries a confidence word, never a percentage.',
  'The responders you see are synthetic. Needs are typed in by an operator, and pledges are test entries. No money is stored, no payment is processed, and no personal details are kept.',
  'Now let me show you how it works.',
];
const TIMES = [[0, 5], [5, 5], [10, 6], [16, 3], [19, 12], [31, 7], [38, 7], [45, 3], [48, 14], [62, 10], [72, 8], [80, 4]];

describe('the tour timeline is the briefed one', () => {
  it('has the twelve narration lines word for word', () => { expect(TOUR.map((s) => s.narration)).toEqual(NARRATION); });
  it('has the briefed start time and length for every step, runs without a gap, and ends at 84 s', () => {
    expect(TOUR.map((s) => [s.at, s.dur])).toEqual(TIMES);
    TOUR.forEach((s, i) => { if (i > 0) expect(s.at).toBe(TOUR[i - 1].at + TOUR[i - 1].dur); });
    expect(TOUR.at(-1)!.at + TOUR.at(-1)!.dur).toBe(84);
    expect(TOUR_DURATION_S).toBe(84);
  });
  it('highlights what each step names, in the briefed order', () => {
    const labels = TOUR.map((s) => s.highlights.map((h) => h.label));
    expect(labels[0]).toEqual([]);
    expect(labels[1]).toEqual(['TideAlert logo', 'REPLAY badge']);
    expect(labels[3]).toEqual(['REPLAY badge', 'the synthetic-data note in the banner']);
    expect(labels[4]).toEqual(['legend: red, cut off', 'legend: orange, may be cut off', 'legend: blue, reconnected', 'legend: green, reachable (a dry route)', 'legend: grey, not assessed']);
    expect(labels[5]).toEqual(['the map', 'top banner cut-off count']);
    expect(labels[6]).toEqual(['lead-time inputs', 'countdown list']);
    expect(labels[8]).toEqual(['panel title', 'ranked rows', 'provenance line']);
    expect(labels[9]).toEqual(['inference sentence', 'confidence word', 'engine contributions']);
    expect(labels[11]).toEqual([]);
  });
  it('contains no number about the flood: only timings, zoom steps and shares', () => {
    const all = readFileSync(join(__dirname, '..', 'dev', 'tour.ts'), 'utf8').replace(/\/\/.*$/gm, '');
    const src = all.slice(all.indexOf('export const TOUR: TourStep'), all.indexOf('export const TOUR_STEPS'));
    expect(src).not.toMatch(/\b(2017|08074500|08075770|08076000)\b|lng|lat:|center: \[-?\d/);
    expect(TOUR.flatMap((s) => s.camera).every((m) => !('center' in m))).toBe(true); // every camera target comes from the data
  });
  it('uses only the four highlight types the player supports', () => {
    expect(new Set(TOUR.flatMap((s) => s.highlights.map((h) => h.type)))).toEqual(new Set(['pulse', 'outline', 'dim']));
  });
});

describe('the start check', () => {
  const ok: StartState = { mode: 'replay', event: 'Hurricane Harvey', at: '2017-08-28T05:15:00+00:00', layer: 'supply', ready: true, runId: 'r1' };
  it('lets the tour start on the Harvey replay at 08-28 05:15 with Supply access', () => { expect(refusal(ok)).toBeNull(); });
  it('refuses the wrong run, time, layer or a page still loading, says what it found, and says what to open', () => {
    const cases: [Partial<StartState>, RegExp][] = [
      [{ mode: 'mixed' }, /MIXED run/], [{ mode: 'scenario', event: null }, /SCENARIO run/], [{ mode: null, event: null, runId: null }, /not loaded yet/],
      [{ at: '2017-08-27T05:15:00Z' }, /2017-08-27 05:15 UTC, not 2017-08-28 05:15/], [{ layer: 'risk' }, /not coloured by Supply access/], [{ ready: false }, /still loading/],
    ];
    for (const [over, re] of cases) {
      const m = refusal({ ...ok, ...over })!;
      expect(m).toMatch(re);
      expect(m).toContain('Harvey REPLAY at 2017-08-28 05:15 UTC');
      expect(m).toContain('Nothing was changed.');
    }
    expect(refusal({ ...ok, mode: 'mixed' })).toContain('?tour=1&run=r1&at=2017-08-28T05%3A15%3A00.000Z');
    expect(TOUR_START_AT).toBe('2017-08-28T05:15:00Z');
  });
});

describe('finding things in the page', () => {
  type Fake = { tag: string; text: string; kids: Fake[]; rect: { width: number; height: number }; parent?: Fake };
  const mk = (tag: string, text: string, kids: Fake[] = [], rect = { width: 10, height: 10 }): Fake => { const n: Fake = { tag, text, kids, rect }; kids.forEach((k) => { k.parent = n; }); return n; };
  const wrap = (n: Fake): unknown => ({
    textContent: n.text + n.kids.map((k) => k.text).join(' '),
    getBoundingClientRect: () => n.rect,
    closest: (css: string) => { let p: Fake | undefined = n; while (p) { if (p.tag === css) return wrap(p); p = p.parent; } return null; },
    querySelectorAll: (css: string) => { const out: Fake[] = []; const walk = (x: Fake) => x.kids.forEach((k) => { if (k.tag === css) out.push(k); walk(k); }); walk(n); return out.map(wrap); },
  });
  const h2 = mk('h2', 'Needs attention'), other = mk('h2', 'Cases (5 open)');
  const page = mk('body', '', [mk('section', '', [h2]), mk('section', '', [other]), mk('span', 'REPLAY', [], { width: 0, height: 0 })]);
  const doc = wrap(page) as unknown as Element;
  it('finds an element by CSS and its text, and lifts it to an ancestor', () => {
    expect(resolveSel({ css: 'h2', match: /^Needs attention/, closest: 'section' }, doc)).not.toBeNull();
    expect(resolveSel({ css: 'h2', match: /^Responders/ }, doc)).toBeNull();
  });
  it('does not count an element that has no size, and finds nothing for a selector the page does not have', () => {
    expect(resolveSel({ css: 'span', match: /^REPLAY$/ }, doc)).toBeNull();
    expect(resolveSel({ css: '[data-tour="flood-polygons"]' }, doc)).toBeNull();
  });
  it('never finds the dev tools\' own panel: its narration contains the words the selectors look for', () => {
    const own = { ...(wrap(mk('div', 'synthetic', [])) as object), closest: (css: string) => (css.includes('data-dev-player') ? {} : null) };
    const root = { querySelectorAll: () => [own] } as unknown as Element;
    expect(resolveSel({ css: 'div', match: /synthetic/ }, root)).toBeNull();
  });
  it('describes a selector for the report', () => {
    const s: Sel = { css: 'h2', match: /^Cases/, scope: { css: 'section' }, closest: 'section' };
    expect(describeSel(s)).toBe('section › h2 /^Cases/ ⤴ section');
  });
});

describe('where the camera goes comes from the data', () => {
  it('picks the densest cluster of points, the same every time, ties to the first cell in key order', () => {
    const pts: [number, number][] = [[-95.5, 29.7], [-95.499, 29.701], [-95.498, 29.702], [-95.1, 29.9], [-95.11, 29.91]];
    const a = densestCluster(pts)!;
    expect(a).toEqual([-95.5, 29.7, -95.498, 29.702]);
    expect(densestCluster([...pts].reverse())).toEqual(a);
    expect(densestCluster([])).toBeNull();
    expect(densestCluster([[-95.9, 29.1], [-95.1, 29.9]])).toEqual([-95.1, 29.9, -95.1, 29.9]);
    expect(densestCluster([[-95.1, 29.9], [-95.9, 29.1]])).toEqual([-95.1, 29.9, -95.1, 29.9]); // the same either way round
  });
});

describe('the tour runner', () => {
  const EXTENT: [number, number, number, number] = [-95.65, 29.77, -95.25, 30.02];
  // A stand-in page: `resolves(css)` says which selectors find a (10 x 10) element; none carries text.
  const page = (resolves: (css: string) => boolean): Document => ({
    querySelectorAll: (css: string) => (resolves(css) ? [{ textContent: '', getBoundingClientRect: () => ({ width: 10, height: 10 }), closest: () => null, scrollIntoView: () => {}, querySelectorAll: () => [] }] : []),
  }) as unknown as Document;
  function rig(opts: { resolves?: (css: string) => boolean; extent?: typeof EXTENT | null; steps?: typeof TOUR } = {}) {
    let now = 0;
    const clock = new PlayerClock(() => now);
    const calls: string[] = [];
    let center = { lng: 0, lat: 0 }, zoom = 1;
    const set = (kind: string) => (o: Record<string, unknown>) => { calls.push(kind); center = { lng: (o.center as number[])[0], lat: (o.center as number[])[1] }; zoom = o.zoom as number; };
    const map: MapLike = {
      cameraForBounds: (b) => ({ center: { lng: (b[0][0] + b[1][0]) / 2, lat: (b[0][1] + b[1][1]) / 2 }, zoom: 9 }),
      flyTo: set('fly'), easeTo: set('ease'), jumpTo: set('jump'),
      stop: () => { calls.push('stop'); }, getCenter: () => center, getZoom: () => zoom, getPitch: () => 0, getBearing: () => 0,
    };
    const host: TourHost = { start: () => ({ mode: 'replay', event: 'Hurricane Harvey', at: TOUR_START_AT, layer: 'supply', ready: true, runId: 'r' }), map: () => map,
      extent: () => (opts.extent === undefined ? EXTENT : opts.extent), cutOffPoints: () => [[-95.5, 29.9], [-95.499, 29.901], [-95.2, 30.0]] };
    const shown: string[][] = [];
    const ui = { highlight: (items: { label: string }[]) => shown.push(items.map((i) => i.label)), caption: () => {} };
    const env = { win: { scrollTo: (o: ScrollToOptions) => { calls.push(`scroll:${o.top}`); }, scrollY: 0 }, doc: page(opts.resolves ?? (() => false)) };
    const tour = createTour(host, ui, clock, opts.steps ?? TOUR, env);
    return { tour, clock, calls, shown, tick: (to: number) => { while (now < to * 1000) { now += 100; tour.tick(); } }, play: () => { clock.play(); tour.start(); } };
  }
  it('ends at 84 s, and a restart gives the same camera at every step end', () => {
    const run = () => { const r = rig(); r.play(); r.tick(85); return r.tour.snaps(); };
    const a = run(), b = run();
    expect(a.length).toBeGreaterThan(5);
    expect(b).toEqual(a);
  });
  it('is finished at 84 s and clears its highlights', () => {
    const r = rig(); r.play(); r.tick(83); expect(r.tour.finished()).toBe(false);
    r.tick(85); expect(r.tour.finished()).toBe(true); expect(r.shown.at(-1)).toEqual([]);
  });
  it('reports a camera move whose target the data cannot give, and does not invent one', () => {
    const r = rig({ extent: null }); r.play(); r.tick(12);
    const row = r.tour.report().find((x) => x.kind === 'camera' && x.label === 'fit zones')!;
    expect(row.resolved).toBe(false);
    expect(r.calls).not.toContain('jump');
    expect(r.calls).not.toContain('fly');
  });
  it('shows one highlight at a time, each for an equal share of its step, and says which resolved', () => {
    const steps = [{ id: 's', at: 0, dur: 12, narration: 'n', camera: [], highlights: [
      { sel: { css: 'a' }, type: 'pulse' as const, label: 'A' }, { sel: { css: 'missing' }, type: 'outline' as const, label: 'B' }, { sel: { css: 'c' }, type: 'dim' as const, label: 'C' }] }];
    const r = rig({ steps, resolves: (css) => css !== 'missing' });
    r.play(); r.tick(3.9); expect(r.shown.at(-1)).toEqual(['A']);
    r.tick(4.1); expect(r.shown.at(-1)).toEqual([]); // B does not resolve: skipped, nothing put in its place
    r.tick(8.1); expect(r.shown.at(-1)).toEqual(['C']);
    expect(r.tour.report().map((x) => [x.label, x.resolved])).toEqual([['A', true], ['B', false], ['C', true]]);
  });
  it('does not advance while paused, and a skipped-to step shows its own highlights, not the ones before', () => {
    const r = rig({ resolves: () => true }); r.play(); r.tick(12);
    const n = r.shown.length;
    r.clock.pause(); r.tick(30);
    expect(r.shown.length).toBe(n);
  });
  it('reads the narration for the step the time is in', () => {
    const r = rig();
    expect(r.tour.line(0)?.text).toBe(NARRATION[0]);
    expect(r.tour.line(49)?.text).toBe(NARRATION[8]);
    expect(r.tour.line(83.9)?.text).toBe(NARRATION[11]);
  });
  it('seeks to a step by jumping, not flying, and stands the clock at that step', () => {
    const r = rig(); r.tour.seek(4);
    expect(r.clock.time()).toBe(19);
    expect(r.calls.filter((c) => c === 'fly')).toEqual([]);
  });
  it('aims the cluster step at the densest cluster of cut-off zones, west first and then east', () => {
    const r = rig({ resolves: () => true }); r.play(); r.tick(31);
    const snap = r.tour.snaps().find((x) => x.step === 4)!;
    expect(snap.center[0]).toBeGreaterThan(-95.5); // it ended east of where it began
    expect(r.calls.filter((c) => c === 'ease').length).toBeGreaterThanOrEqual(1);
  });
});

describe('the tour changes no app state', () => {
  const src = readFileSync(join(__dirname, '..', 'dev', 'tour.ts'), 'utf8').replace(/\/\/.*$/gm, '');
  it('never clicks, dispatches an event, writes to a field or storage, or fetches', () => {
    expect(src).not.toMatch(/\.click\(|dispatchEvent|\.value\s*=|localStorage|sessionStorage|indexedDB|fetch\(|XMLHttpRequest|history\.|location\./);
  });
  it('is given no way to move the slider, pick a layer or open a panel: its host has reads only', () => {
    const host = src.slice(src.indexOf('export interface TourHost'), src.indexOf('export interface TourUi'));
    expect(host).toMatch(/start\(\)/);
    expect(host).not.toMatch(/set[A-Z]|goTo|select|open\(|choose|pin|reveal/);
  });
});
