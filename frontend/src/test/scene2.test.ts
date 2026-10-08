import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PlayerClock } from '../dev/TimelinePlayer';

const post = vi.fn();
const needs = vi.fn();
vi.mock('../lib/api', () => ({ post: (...a: unknown[]) => post(...a), api: { needs: (...a: unknown[]) => needs(...a) } }));

import { DONOR_NAME, HB_FROM, HB_TO, OPERATOR_NAME, SCENE2, SCENE2_DURATION_S, SCENE2_STEPS, type Scene2Facts, type Scene2Host, type Step, Skip, clippedBy, createScene2, resetDemo } from '../dev/scene2';

const SRC = join(__dirname, '..');
const source = readFileSync(join(SRC, 'dev', 'scene2.ts'), 'utf8');

// The narration is read aloud. These are the briefed lines, verbatim; changing one needs approval.
const NARRATION = [
  "Let's follow one coordinator through one decision.",
  "Needs attention puts first the zones that are cut off with nobody assigned, then cut off with someone assigned, then zones that may be cut off. It's a display order, not a risk score.",
  "Let's open the first one.",
  'Estimated population. Whether a dry route exists. When the road was lost. How sure we are. The Case shows which engine found it and a confidence word. Where data is stale, it says verify.',
  'Nothing is shown as safe just because we lack data.',
  'Now dispatch. This is Hunting Bayou.',
  'At 2:30, three tasks were assigned, because the zone had reconnected at 2:15.',
  "By 3:45 it's cut off again, and the task shows a warning: isolated after assignment. A responder is told before driving in, not after.",
  "Whenever a zone reconnects, its tasks are flagged verify before dispatch. A reopened road isn't the same as a safe road.",
  'These assignments are scripted and synthetic. The flood they respond to is real.',
  'People in a cut-off zone need more than a dispatch decision. They need supplies.',
  'The operator opens the zone and posts a need.',
  'Water, forty units. Recorded as entered by an operator, not measured.',
  'The portal lists open needs, cut-off zones first.',
  'A neighbor picks a need, enters a quantity, and pledges. It records a pledge, not a delivery.',
  'No money, no card, no donor name, no leaderboard.',
  'This is where goodwill becomes something a coordinator can plan around.',
  "The coordinator can ask the Copilot for a briefing. It answers only from this run's data, so it can't invent a status.",
  "TideAlert doesn't promise rescue. It helps people decide, and it says what it doesn't know.",
];
const AT = [0, 6, 14, 17, 27, 31, 37, 43, 53, 59, 63, 69, 74, 82, 87, 95, 101, 105, 111];

describe('the Scene 2 timeline', () => {
  it('reads the briefed narration verbatim, in order', () => { expect(SCENE2.map((s) => s.narration)).toEqual(NARRATION); });
  it('starts each step at the briefed second, each ending where the next begins, and ends at 116', () => {
    expect(SCENE2.map((s) => s.at)).toEqual(AT);
    SCENE2.forEach((s, i) => expect(s.at + s.dur).toBe(i + 1 < SCENE2.length ? SCENE2[i + 1].at : SCENE2_DURATION_S));
    expect(SCENE2_DURATION_S).toBe(116);
    expect(SCENE2_STEPS).toHaveLength(19);
  });
  it('states the verify rule (step 9) without a camera move, an action or a highlight: the flag is not on those tasks', () => {
    const s = SCENE2[8];
    expect(s.id).toBe('verify-rule');
    expect(s.acts).toEqual([]);
    expect(s.highlights).toEqual([]);
  });
  it('slides 02:30 to 03:45, the times of the real re-isolation on the mixed run', () => { expect([HB_FROM, HB_TO]).toEqual(['2017-08-28T02:30:00Z', '2017-08-28T03:45:00Z']); });
});

describe('what Scene 2 is allowed to write', () => {
  it('uses the two placeholder names and no real name', () => {
    expect([OPERATOR_NAME, DONOR_NAME]).toEqual(['Demo Operator', 'Test Donor']);
    expect(source).toMatch(/typeInto\(c\.q\(operatorInput\), OPERATOR_NAME/);
    expect(source).toMatch(/DONOR_NAME, 1000/);
  });
  it('asks the Copilot through the Briefing button only: no free-text field is touched', () => {
    expect(source).toMatch(/match: \/\^briefing\$\/i/);
    expect(source).not.toMatch(/aria-label="Question"/);
    expect(source).not.toMatch(/copilot\/ask/);
  });
  it('names no zone: the Hunting Bayou zones are found from the data, by the gauge their Case came from', () => {
    expect(source).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/);
    for (const id of ['27e11195', '082db8c3', '3cf498ae']) expect(source).not.toContain(id);
    expect(source).toMatch(/HB_GAUGE = \/08075770\//);
  });
  it('holds no flood figures: its numbers are times, slider stops, zoom levels and quantities typed in', () => {
    expect(source).not.toMatch(/\bpopulation\s*[:=]\s*\d/i);
    expect(source).not.toMatch(/Math\.random|Date\.now|new Date\(\)/);
  });
  it('never touches money or a card', () => { expect(source).not.toMatch(/\$\d|credit|card number|payment method/i); });
});

describe('keeping it out of the product', () => {
  it('is loaded only by a dynamic import in the overlay, and imported statically nowhere else outside dev/', () => {
    const overlay = readFileSync(join(SRC, 'dev', 'DevOverlay.tsx'), 'utf8');
    expect(overlay).not.toMatch(/^import (?!type )[^\n]*from '\.\/scene2'/m);
    expect(overlay).toMatch(/await import\('\.\/scene2'\)/);
    const app = readFileSync(join(SRC, 'App.tsx'), 'utf8');
    expect(app.split('\n').filter((l) => /from '\.\/dev\//.test(l)).every((l) => /^import type /.test(l))).toBe(true);
    expect(source).not.toMatch(/from '\.\/(conductor)'/);
  });
  it('the Reset route is mounted by the API only when it was started with TIDEALERT_DEV_RESET=1', () => {
    const main = readFileSync(join(SRC, '..', '..', 'backend', 'app', 'main.py'), 'utf8');
    expect(main).toMatch(/if os\.environ\.get\("TIDEALERT_DEV_RESET"\) == "1"/);
    expect(readFileSync(join(SRC, '..', '..', 'backend', 'app', 'routes', 'needs.py'), 'utf8')).not.toContain('dev-reset');
  });
});

// ---------------------------------------------------------------- the runner, on a fake page
function facts(over: Partial<Scene2Facts> = {}): Scene2Facts {
  return { ready: true, runId: 'run', mode: 'mixed', atMs: 0, ticks: [], windowEnd: null, zones: [], ranked: [], selectedZoneId: null, needsWritable: true, ...over };
}
function world(steps: Step[], f: Scene2Facts = facts()) {
  let now = 0;
  const clock = new PlayerClock(() => now);
  const host: Scene2Host = { open: async () => ({ startMs: 0 }), mixedRunId: () => 'run', goToTick: () => {}, facts: () => f, extent: () => null, zoneGeometry: () => null, active: () => {} };
  const shown: string[][] = [];
  const logs: string[] = [];
  const env = { doc: { querySelector: () => null } as unknown as Document, win: {} as never, sleep: async (ms: number) => { now += ms; }, log: (l: string) => { logs.push(l); } };
  const scene = createScene2(host, { highlight: (items) => shown.push(items.map((i) => i.label)) }, clock, steps, env);
  const at = async (t: number) => { clock.seek(t); clock.play(); scene.tick(); await Promise.resolve(); await Promise.resolve(); };
  return { scene, clock, shown, logs, at, now: () => now };
}
const step = (over: Partial<Step>): Step => ({ at: 0, dur: 5, id: 's', narration: 'n', acts: [], highlights: [], ...over });

describe('the runner', () => {
  beforeEach(() => { vi.spyOn(console, 'warn').mockImplementation(() => {}); vi.spyOn(console, 'info').mockImplementation(() => {}); });

  it('runs a step once when its time comes and logs the value the act used', async () => {
    const run = vi.fn(async () => 'water 40');
    const w = world([step({ acts: [{ at: 0, name: 'enter', run }] })]);
    w.scene.start();
    await w.at(0); await w.at(1);
    await vi.waitFor(() => expect(w.scene.log()).toHaveLength(1));
    expect(run).toHaveBeenCalledTimes(1);
    expect(w.scene.log()[0]).toEqual({ step: 's', kind: 'act', name: 'enter', ok: true, value: 'water 40' });
  });
  it('SKIPS a step whose act cannot be satisfied, says why, marks the line (skipped) and goes on to the next step: nothing is substituted', async () => {
    const after = vi.fn(async () => 'done');
    const w = world([step({ id: 'a', at: 0, dur: 5, acts: [{ at: 0, name: 'click', run: async () => { throw new Skip('the button is not on the page'); } }] }),
                     step({ id: 'b', at: 5, dur: 5, acts: [{ at: 0, name: 'next', run: after }] })]);
    w.scene.start();
    await w.at(0);
    await vi.waitFor(() => expect(w.scene.log()).toHaveLength(1));
    expect(w.scene.log()[0]).toEqual({ step: 'a', kind: 'act', name: 'click', ok: false, value: 'the button is not on the page' });
    expect(w.scene.line(2)).toEqual({ text: 'n', skipped: true });
    await w.at(5);
    await vi.waitFor(() => expect(after).toHaveBeenCalled());
    expect(w.scene.line(6)?.skipped).toBe(false);
  });
  it("skips a step's highlights when its check fails (step 7: not three tasks), and shows no box", async () => {
    const w = world([step({ need: () => '11 zones have an assigned task at 02:30, not three', highlights: [{ label: 'panel', find: () => [{} as Element] }] })]);
    w.scene.start();
    await w.at(1);
    await vi.waitFor(() => expect(w.scene.log().length).toBeGreaterThan(0));
    expect(w.scene.log()[0]).toMatchObject({ kind: 'highlight', ok: false, value: expect.stringContaining('not three') });
    expect(w.shown.flat()).not.toContain('panel');
  });
  it('reports a highlight whose element was never on the page, once, after its step ends, and highlights nothing in its place', async () => {
    const w = world([step({ dur: 4, highlights: [{ label: 'marker', find: () => [] }] })]);
    w.scene.start();
    await w.at(1); await w.at(5); await w.at(6);
    const rows = w.scene.log().filter((r) => r.kind === 'highlight');
    expect(rows).toEqual([{ step: 's', kind: 'highlight', name: 'marker', ok: false, value: 'the element was not on the page when its turn came' }]);
    expect(w.shown.flat()).not.toContain('marker');
  });
  it("starts a step's highlights after hlFrom, one at a time, each for an equal share", async () => {
    const el = { getBoundingClientRect: () => ({ top: 10, bottom: 30 }), parentElement: null, scrollIntoView: () => {} } as unknown as Element;
    const win = { innerHeight: 800, getComputedStyle: () => ({ overflowY: 'visible' }), scrollTo: () => {} } as never;
    let now = 0; const clock = new PlayerClock(() => now); const shown: string[][] = [];
    const host: Scene2Host = { open: async () => ({ startMs: 0 }), mixedRunId: () => 'r', goToTick: () => {}, facts: () => facts(), extent: () => null, zoneGeometry: () => null, active: () => {} };
    const s = step({ dur: 10, hlFrom: 4, highlights: ['a', 'b', 'c'].map((label) => ({ label, find: () => [el] })) });
    const scene = createScene2(host, { highlight: (i) => shown.push(i.map((x) => x.label)) }, clock, [s], { doc: {} as Document, win, sleep: async () => {}, log: () => {} });
    scene.start();
    for (const t of [1, 3.9]) { clock.seek(t); clock.play(); scene.tick(); }
    expect(shown).toEqual([]); // nothing before hlFrom
    for (const t of [4.5, 6.5, 8.5]) { clock.seek(t); clock.play(); scene.tick(); }
    expect(shown.filter((x) => x.length).flat()).toEqual(['a', 'b', 'c']);
  });
  it('stop() cancels what is waiting, so an act from the last play cannot fire in the next', async () => {
    const run = vi.fn(async () => 'late');
    const w = world([step({ acts: [{ at: 3, name: 'late', run }] })]);
    w.scene.start();
    await w.at(0);
    w.scene.stop();
    w.clock.seek(10);
    await new Promise((r) => setTimeout(r, 20));
    expect(run).not.toHaveBeenCalled();
  });
  it('is finished at 116 s, and a seek does nothing: a scene that writes rows is played from the top', () => {
    const w = world([step({})]);
    w.clock.seek(116); expect(w.scene.finished()).toBe(true);
    w.clock.seek(10); w.scene.seek(5); expect(w.clock.time()).toBe(10);
  });
});

describe('the pre-check and Reset', () => {
  beforeEach(() => { post.mockReset(); needs.mockReset(); });
  const host = (id: string | null): Scene2Host => ({ open: async () => null, mixedRunId: () => id, goToTick: () => {}, facts: () => facts({ windowEnd: '2017-09-03T05:00:00Z' }), extent: () => null, zoneGeometry: () => null, active: () => {} });
  const env = { doc: { querySelector: () => null } as unknown as Document, win: {} as never, sleep: async () => {}, log: () => {} };

  it('refuses to start while an earlier play left its rows on the board, and says to press Reset', async () => {
    needs.mockResolvedValue({ zones: { z: { events: [{ actor: 'Demo Operator' }, { actor: 'A Human' }], pledges: [{ donor: 'Test Donor' }, { donor: 'A Neighbor' }] } } });
    const s = createScene2(host('run'), { highlight: () => {} }, new PlayerClock(() => 0), [], env);
    expect(await s.precheck()).toMatch(/2 demo rows .* Press Reset first/);
    expect(needs).toHaveBeenCalledWith('run', '2017-09-03T05:00:00Z');
  });
  it('lets a clean board (or only human rows) start', async () => {
    needs.mockResolvedValue({ zones: { z: { events: [{ actor: 'A Human' }], pledges: [{ donor: 'A Neighbor' }] } } });
    const s = createScene2(host('run'), { highlight: () => {} }, new PlayerClock(() => 0), [], env);
    expect(await s.precheck()).toBeNull();
  });
  it('says so when there is no mixed run', async () => {
    const s = createScene2(host(null), { highlight: () => {} }, new PlayerClock(() => 0), [], env);
    expect(await s.precheck()).toMatch(/no mixed Harvey run/);
    expect(await resetDemo(host(null), env.doc)).toMatch(/no mixed Harvey run/);
  });
  it('Reset asks the server to delete by the two markers on the mixed run, and reports the counts', async () => {
    post.mockResolvedValue({ pledges_deleted: 1, need_entries_deleted: 1 });
    const line = await resetDemo(host('run'), env.doc);
    expect(post).toHaveBeenCalledWith('/needs/dev-reset', { run_id: 'run' });
    expect(line).toBe('Reset: removed 1 need entries and 1 pledges written as "Demo Operator" / "Test Donor". Anything else was left alone.');
  });
  it('Reset says how to switch it on when the server was not started for it', async () => {
    post.mockRejectedValue(new Error('HTTP 404: Not found'));
    expect(await resetDemo(host('run'), env.doc)).toBe('Reset is off: start the API with TIDEALERT_DEV_RESET=1.');
  });
});

describe('knowing when a highlight box would point at blank space', () => {
  const rect = (top: number, bottom: number) => ({ getBoundingClientRect: () => ({ top, bottom }) });
  const win = (styles: Record<string, string>) => ({ innerHeight: 800, getComputedStyle: (e: { id?: string }) => ({ overflowY: styles[e.id ?? ''] ?? 'visible' }) }) as never;
  it('is not clipped when inside the window and inside the scrolling panel it sits in', () => {
    const panel = { id: 'p', parentElement: null, ...rect(100, 500) };
    expect(clippedBy({ parentElement: panel, ...rect(150, 200) } as unknown as Element, win({ p: 'auto' }))).toBe(false);
  });
  it('is clipped when it is below the window, or below the bottom of its scrolling panel', () => {
    const panel = { id: 'p', parentElement: null, ...rect(100, 500) };
    expect(clippedBy({ parentElement: null, ...rect(700, 900) } as unknown as Element, win({}))).toBe(true);
    expect(clippedBy({ parentElement: panel, ...rect(480, 560) } as unknown as Element, win({ p: 'auto' }))).toBe(true);
  });
});
