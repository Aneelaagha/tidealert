import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PlayerClock } from '../dev/TimelinePlayer';

const api = { runs: vi.fn(), copilotStatus: vi.fn(), zones: vi.fn(), needs: vi.fn(), ask: vi.fn() };
const get = vi.fn();
vi.mock('../lib/api', () => ({ api: new Proxy({}, { get: (_t, k: string) => (...a: unknown[]) => (api as Record<string, (...x: unknown[]) => unknown>)[k](...a) }), get: (...a: unknown[]) => get(...a), post: vi.fn() }));

import { CHECKPOINTS, DEMO_DURATION_S, MAP_HOLD_AT, SCENE2_AT, SWAP_AT, SWITCH_AT, SWITCH_CAPTION, TOTAL_STEPS, createFullDemo, preflight, type DemoHost } from '../dev/demo';
import { SCENE2, SCENE2_DURATION_S, type Scene2 } from '../dev/scene2';
import { TOUR, TOUR_DURATION_S, type Tour } from '../dev/tour';

const SRC = join(__dirname, '..');
const source = readFileSync(join(SRC, 'dev', 'demo.ts'), 'utf8');

describe('the Full Demo timeline', () => {
  it('is the tour (84 s), a 3 s run switch, then Scene 2 (116 s): 203 s', () => {
    expect(TOUR_DURATION_S).toBe(84); expect(SCENE2_DURATION_S).toBe(116);
    expect([SWITCH_AT, SWAP_AT, MAP_HOLD_AT, SCENE2_AT, DEMO_DURATION_S]).toEqual([84, 85, 86, 87, 203]);
    expect(TOTAL_STEPS).toBe(TOUR.length + 1 + SCENE2.length);
  });
  it('has six named resume points, in order, at the right moments', () => {
    expect(CHECKPOINTS.map((c) => c.label)).toEqual(['Tour start', 'Tour → Scene 2', 'Scene 2: dispatch', 'Scene 2: needs', 'Scene 2: copilot', 'End']);
    const at = (id: string) => SCENE2_AT + SCENE2.find((s) => s.id === id)!.at;
    expect(CHECKPOINTS.map((c) => c.at)).toEqual([0, SWITCH_AT, at('move-to-hunting-bayou'), at('operator-name'), at('copilot-briefing'), DEMO_DURATION_S]);
    expect(CHECKPOINTS.slice(2, 5).map((c) => c.at)).toEqual([118, 150, 192]);
  });
  it('adds one editorial line, the switch caption, and says what is happening', () => {
    expect(SWITCH_CAPTION).toBe('Switching to the mixed run — synthetic responders, real flood.');
    expect(source.match(/Switching to/g)).toHaveLength(1);
  });
  it('composes the two timelines and changes neither: it imports their data and holds none of their narration', () => {
    expect(source).toMatch(/from '\.\/tour'/); expect(source).toMatch(/from '\.\/scene2'/);
    for (const s of [...TOUR, ...SCENE2]) expect(source).not.toContain(s.narration);
  });
});

// ---------------------------------------------------------------- the runner, on fakes
function world(over: { report?: { step: number; resolved: boolean }[]; openMixed?: () => Promise<boolean>; openHarvey?: () => Promise<boolean>; refusal?: string | null; prepare?: () => Promise<string> } = {}) {
  let now = 0;
  const clock = new PlayerClock(() => now);
  const calls: string[] = [];
  const tour = { steps: [], line: (t: number) => ({ text: `tour ${Math.floor(t)}` }), refusal: () => over.refusal ?? null, start: () => calls.push('tour.start'), tick: () => calls.push('tour.tick'),
    stop: () => calls.push('tour.stop'), seek: (i: number) => calls.push(`tour.seek ${i}`), finished: () => false, report: () => over.report ?? [] } as unknown as Tour;
  const scene = { steps: SCENE2.map((s) => ({ at: s.at, label: s.id })), line: (t: number) => ({ text: `scene ${Math.floor(t)}`, skipped: false }), start: () => calls.push('scene.start'), tick: () => calls.push('scene.tick'),
    stop: () => calls.push('scene.stop'), startFrom: (f: number) => calls.push(`scene.startFrom ${f}`), prepare: over.prepare ?? (async (t: string) => { calls.push(`scene.prepare ${t}`); return t; }) } as unknown as Scene2;
  const host: DemoHost = {
    openHarvey: over.openHarvey ?? (async () => { calls.push('openHarvey'); return true; }),
    openMixed: over.openMixed ?? (async () => { calls.push('openMixed'); return true; }),
    caption: (t) => calls.push(`caption ${t === null ? 'off' : 'on'}`), scrollTop: () => calls.push('scrollTop'), stopMap: () => calls.push('stopMap'), log: () => {},
  };
  const demo = createFullDemo({ tour, scene, clock, host });
  const advance = (to: number) => { clock.seek(to); clock.play(); demo.tick(); };
  return { demo, clock, calls, advance, setNow: (n: number) => { now = n; } };
}
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('playing the sequence', () => {
  it('opens the Harvey replay first, and plays only once it is ready', async () => {
    const w = world();
    expect(await w.demo.prepare()).toBeNull();
    expect(w.demo.status()).toBe('ready');
    w.demo.play();
    expect(w.demo.status()).toBe('running'); expect(w.calls).toContain('tour.start');
  });
  it('refuses to be ready when the tour would refuse to start, and says why', async () => {
    const w = world({ refusal: 'The guided tour starts only on the Harvey REPLAY' });
    expect(await w.demo.prepare()).toMatch(/Harvey REPLAY/);
    expect(w.demo.status()).toBe('idle');
    w.demo.play(); expect(w.demo.status()).toBe('idle');
  });
  it('runs the tour to 84 s, holds 1 s, swaps the run with its caption, holds 1 s on the map, then starts Scene 2 at 87 s', async () => {
    const w = world();
    await w.demo.prepare(); w.demo.play(); w.calls.length = 0;
    w.advance(40); expect(w.calls).toEqual(['tour.tick']);
    w.calls.length = 0; w.advance(84.5); expect(w.calls).not.toContain('openMixed');
    w.calls.length = 0; w.advance(85.1);
    expect(w.calls.filter((c) => c === 'openMixed' || c.startsWith('caption'))).toEqual(['openMixed', 'caption on']); // the caption is set after the swap starts
    await flush();
    w.calls.length = 0; w.advance(86.2);
    expect(w.calls).toEqual(expect.arrayContaining(['caption off', 'scrollTop'])); expect(w.calls).not.toContain('scene.start');
    w.calls.length = 0; w.advance(87.1);
    expect(w.calls).toEqual(expect.arrayContaining(['scene.start', 'scene.tick']));
    w.advance(DEMO_DURATION_S); expect(w.demo.status()).toBe('finished');
  });
  it('stands the clock still (bounded) while the mixed run loads, and never starts Scene 2 on a half-loaded page', async () => {
    let release: (v: boolean) => void = () => {};
    const w = world({ openMixed: () => new Promise<boolean>((r) => { release = r; }) });
    await w.demo.prepare(); w.demo.play(); w.advance(85.1); w.calls.length = 0;
    const hold = vi.spyOn(w.clock, 'hold');
    w.advance(86.5); w.advance(88);
    expect(hold).toHaveBeenCalled(); expect(w.calls).not.toContain('scene.start');
    release(true); await flush(); w.calls.length = 0;
    w.advance(88); expect(w.calls).toContain('scene.start');
  });
  it('does not start Scene 2 when the run switch failed, and logs it', async () => {
    const w = world({ openMixed: async () => false });
    await w.demo.prepare(); w.demo.play(); w.advance(85.1); await flush(); w.calls.length = 0;
    w.advance(88);
    expect(w.calls).not.toContain('scene.start'); expect(w.demo.status()).toBe('finished');
    expect(w.demo.log().some((r) => !r.ok && /mixed run could not be opened/.test(r.note))).toBe(true);
  });
  it('maps time to the read-along line and the step number across the three parts', async () => {
    const w = world();
    expect(w.demo.line(10)?.text).toBe('tour 10');
    expect(w.demo.line(85)?.text).toBe(SWITCH_CAPTION);
    expect(w.demo.line(87 + 31)?.text).toBe('scene 31');
    expect(w.demo.stepAt(0)).toBe(1); expect(w.demo.stepAt(84.5)).toBe(TOUR.length + 1);
    expect(w.demo.stepAt(SCENE2_AT)).toBe(TOUR.length + 2); expect(w.demo.stepAt(DEMO_DURATION_S)).toBe(TOTAL_STEPS);
  });
  it("appends (skipped) to a tour step whose highlight or camera target was not in the page, as Scene 2's read-along does", () => {
    const w = world({ report: [{ step: 3, resolved: true }, { step: 5, resolved: false }] });
    expect(w.demo.line(TOUR[3].at + 1)?.skipped).toBe(false);
    expect(w.demo.line(TOUR[5].at + 1)?.skipped).toBe(true);
    expect(w.demo.line(TOUR[4].at + 1)?.skipped).toBe(false);
  });
  it('Pause stops the clock and the camera', async () => {
    const w = world(); await w.demo.prepare(); w.demo.play(); w.demo.pause();
    expect(w.demo.status()).toBe('paused'); expect(w.clock.isPlaying).toBe(false); expect(w.calls).toContain('stopMap');
    w.demo.play(); expect(w.demo.status()).toBe('running');
  });
});

describe('the resume points', () => {
  it('Tour start: stops both tools, opens Harvey at its start, the clock to 0, and starts the tour', async () => {
    const w = world(); await w.demo.prepare(); w.demo.play(); w.advance(150); w.calls.length = 0;
    expect(await w.demo.jump('tour-start')).toBeNull();
    expect(w.calls).toEqual(expect.arrayContaining(['scene.stop', 'tour.stop', 'caption off', 'openHarvey', 'tour.start']));
    expect(w.clock.time()).toBe(0); expect(w.demo.status()).toBe('running'); // it was playing: it goes on playing
  });
  it('keeps the mode: a jump while paused leaves it paused, at the resume point, until Play', async () => {
    const w = world(); await w.demo.prepare(); w.demo.play(); w.advance(50); w.demo.pause();
    expect(await w.demo.jump('needs')).toBeNull();
    expect(w.demo.status()).toBe('paused'); expect(w.clock.isPlaying).toBe(false); expect(w.clock.time()).toBe(CHECKPOINTS[3].at);
    w.demo.play(); expect(w.demo.status()).toBe('running');
  });
  it('Tour → Scene 2: Harvey open, the clock at 84 s, no tool started, then the run switch plays', async () => {
    const w = world(); await w.demo.prepare();
    expect(await w.demo.jump('tour-scene2')).toBeNull();
    expect(w.clock.time()).toBe(SWITCH_AT); expect(w.demo.status()).toBe('paused'); // it was not playing: it waits for Play
    expect(w.calls).toContain('openHarvey'); expect(w.calls).not.toContain('tour.start');
    w.demo.play(); w.advance(85.1); expect(w.calls).toContain('openMixed');
  });
  for (const [id, target, from] of [['dispatch', 'dispatch', 31], ['needs', 'needs', 63], ['copilot', 'copilot', 105]] as const) {
    it(`Scene 2: ${id}: the mixed run, the page put in that state, Scene 2 started ${from} s in without running the steps before it`, async () => {
      const w = world(); await w.demo.prepare(); w.demo.play(); w.advance(20); w.calls.length = 0;
      expect(await w.demo.jump(id)).toBeNull();
      expect(w.calls).toEqual(expect.arrayContaining(['openMixed', `scene.prepare ${target}`, `scene.startFrom ${from}`, 'scrollTop']));
      expect(w.clock.time()).toBe(SCENE2_AT + from); expect(w.demo.status()).toBe('running');
      w.calls.length = 0; w.advance(SCENE2_AT + from + 1); expect(w.calls).not.toContain('openMixed'); expect(w.calls).toContain('scene.tick'); // no second run switch, no replay of the steps before
    });
  }
  it('End: the final state, finished, nothing playing', async () => {
    const w = world(); await w.demo.prepare();
    expect(await w.demo.jump('end')).toBeNull();
    expect(w.calls).toContain('scene.prepare end'); expect(w.clock.time()).toBe(DEMO_DURATION_S); expect(w.demo.status()).toBe('finished');
  });
  it('a resume point that cannot be reached says so and leaves the clock where it was, so the operator can try another', async () => {
    const w = world({ openMixed: async () => false }); await w.demo.prepare(); w.demo.play(); w.advance(20);
    expect(await w.demo.jump('needs')).toMatch(/Could not open the mixed run/);
    expect(w.demo.status()).toBe('idle'); expect(w.clock.time()).toBe(20);
    const v = world({ prepare: async () => { throw new Error('no zone is cut off at this time'); } }); await v.demo.prepare();
    expect(await v.demo.jump('copilot')).toMatch(/could not be put in the "Scene 2: copilot" state: no zone is cut off/);
  });
});

describe('the pre-flight check', () => {
  const HARVEY = { id: '9c3d69a2-6118', mode: 'replay', event: 'Hurricane Harvey', peak_at: '2017-08-27T20:00:00Z', window_end: '2017-09-03T05:00:00Z' };
  const MIXED = { id: '95a779db-3ec2', mode: 'mixed', event: 'Hurricane Harvey', peak_at: '2017-08-27T20:00:00Z', window_end: '2017-09-03T05:00:00Z' };
  const board = (rows = 0) => ({ writable: true, blocked_reason: null, zones: rows ? { z: { events: [{ actor: 'Demo Operator' }], pledges: rows > 1 ? [{ donor: 'Test Donor' }] : [] } } : {} });
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset()); get.mockReset();
    api.runs.mockResolvedValue({ runs: [HARVEY, MIXED] });
    api.copilotStatus.mockResolvedValue({ mode: 'template' });
    api.zones.mockResolvedValue({ at: '2017-08-28T05:15:00+00:00' });
    api.needs.mockResolvedValue(board());
    api.ask.mockResolvedValue({ mode: 'template' });
    get.mockImplementation(async (path: string) => (path === '/needs/dev-build' ? { sha: 'abc1234567', dirty: false } : { sha: 'abc1234567' }));
  });
  const by = (items: Awaited<ReturnType<typeof preflight>>) => Object.fromEntries(items.map((i) => [i.id, i]));

  it('reports six items, all PASS on a ready machine', async () => {
    const r = await preflight();
    expect(r.map((i) => i.id)).toEqual(['backend', 'build', 'harvey', 'mixed', 'rows', 'template']);
    expect(r.every((i) => i.ok)).toBe(true);
  });
  it('fails the build check when the server was started from another commit, and says to restart it', async () => {
    get.mockImplementation(async (path: string) => (path === '/needs/dev-build' ? { sha: 'old0000000', dirty: false } : { sha: 'abc1234567' }));
    const i = by(await preflight()).build;
    expect(i.ok).toBe(false); expect(i.detail).toBe('server old0000, checkout abc1234'); expect(i.fix).toBe('restart the API from this checkout');
  });
  it('fails the build check when the server does not report its build (not started for the demo)', async () => {
    get.mockImplementation(async (path: string) => { if (path === '/needs/dev-build') throw new Error('404'); return { sha: 'abc1234567' }; });
    expect(by(await preflight()).build.fix).toMatch(/TIDEALERT_DEV_RESET=1/);
  });
  it('offers a one-click Reset when demo rows are on the mixed run, and passes once they are gone', async () => {
    api.needs.mockResolvedValue(board(2));
    const i = by(await preflight()).rows;
    expect(i.ok).toBe(false); expect(i.detail).toBe('2 left from an earlier run'); expect(i.reset).toBe(true); expect(i.fix).toBe('press Reset');
  });
  it('fails when the mixed run refuses entries, when the Harvey time is not on the run, and when the briefing would use a model', async () => {
    api.needs.mockResolvedValue({ writable: false, blocked_reason: 'a replay', zones: {} });
    expect(by(await preflight()).mixed.ok).toBe(false);
    api.zones.mockResolvedValue({ at: '2017-08-28T06:00:00+00:00' });
    expect(by(await preflight()).harvey.ok).toBe(false);
    api.ask.mockResolvedValue({ mode: 'model' });
    expect(by(await preflight()).template.ok).toBe(false);
  });
  it('fails with the reason, not an exception, when the backend does not answer', async () => {
    api.copilotStatus.mockRejectedValue(new Error('offline'));
    const i = by(await preflight()).backend;
    expect(i.ok).toBe(false); expect(i.detail).toBe('offline');
  });
  it('asks the Copilot through an intent with an empty question: no free text', async () => {
    await preflight();
    expect(api.ask).toHaveBeenCalledWith(expect.objectContaining({ question: '', intent: 'open_cases' }));
  });
});

describe('keeping it out of the product', () => {
  it('?demo=1 is its own gate, loaded only by a lazy dev-only import; without it nothing of the Full Demo is fetched', () => {
    const app = readFileSync(join(SRC, 'App.tsx'), 'utf8');
    expect(app).toMatch(/DEMO_ON = import\.meta\.env\.DEV && typeof window !== 'undefined' && new URLSearchParams\(window\.location\.search\)\.get\('demo'\) === '1'/);
    expect(app).toMatch(/DemoOverlay = import\.meta\.env\.DEV \? lazy\(\(\) => import\('\.\/dev\/DemoOverlay'\)\) : null/);
    expect(app).toMatch(/\{DemoOverlay && DEMO_ON && !TOUR_ON && devHost && tourData && /);
    expect(app).toMatch(/\{DevOverlay && DEV_ON && !TOUR_ON && !DEMO_ON && devHost/); // the ?dev=1 overlay does not mount beside it
    expect(app.split('\n').filter((l) => /from '\.\/dev\//.test(l)).every((l) => /^import type /.test(l))).toBe(true);
    const overlay = readFileSync(join(SRC, 'dev', 'DemoOverlay.tsx'), 'utf8');
    expect(overlay).not.toMatch(/^import (?!type )[^\n]*from '\.\/(demo|tour|scene2|conductor)'/m);
    for (const m of ['demo', 'tour', 'scene2']) expect(overlay).toMatch(new RegExp(`import\\('\\./${m}'\\)`));
  });
  it('the build-commit check exists only on the dev server and only when the API was started with the dev switch', () => {
    expect(readFileSync(join(SRC, '..', 'vite.config.ts'), 'utf8')).toMatch(/apply: 'serve'/);
    expect(readFileSync(join(SRC, '..', '..', 'backend', 'app', 'main.py'), 'utf8')).toMatch(/if os\.environ\.get\("TIDEALERT_DEV_RESET"\) == "1"/);
    expect(readFileSync(join(SRC, '..', '..', 'backend', 'app', 'routes', 'dev_reset.py'), 'utf8')).toContain('/needs/dev-build');
  });
});
