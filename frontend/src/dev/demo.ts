// DEV ONLY (?demo=1). The Full Demo: the guided tour and Scene 2 as one live sequence, with named resume points and a pre-flight check.
// It composes the two timelines and changes neither: Part 1 is the tour (0:00-1:24, Harvey replay, read-only), Part 2 is the run switch (3 s:
// a 1 s hold on the tour's last frame, the badge swap with its one editorial caption, a 1 s hold on the map), Part 3 is Scene 2 (116 s, mixed run).
// Honesty rules are the two tools' own; this file adds only the switch, the checkpoints and the checks, and it writes no rows itself.
import { api, get } from '../lib/api';
import type { PlayerClock } from './TimelinePlayer';
import { DONOR_NAME, OPERATOR_NAME, SCENE2_DURATION_S, type PrepareTarget, type Scene2 } from './scene2';
import { TOUR, TOUR_DURATION_S, type Tour } from './tour';

export const SWITCH_AT = TOUR_DURATION_S; // 84: the tour's last frame holds for 1 s
export const SWAP_AT = SWITCH_AT + 1; // 85: the badge swaps and its caption shows
export const MAP_HOLD_AT = SWAP_AT + 1; // 86: 1 s hold on the map
export const SCENE2_AT = MAP_HOLD_AT + 1; // 87: Scene 2 begins
export const DEMO_DURATION_S = SCENE2_AT + SCENE2_DURATION_S; // 203
export const SWITCH_CAPTION = 'Switching to the mixed run — synthetic responders, real flood.';
export const SWITCH_LINE = SWITCH_CAPTION; // the only editorial line in the demo
export const HOLD_MAX_MS = 6000; // the swap waits for the mixed run's data this long, then the demo goes on and says so

export type CheckpointId = 'tour-start' | 'tour-scene2' | 'dispatch' | 'needs' | 'copilot' | 'end';
export interface Checkpoint { id: CheckpointId; label: string; at: number; prepare: 'harvey' | PrepareTarget | 'mixed' }
/** The six resume points: where each puts the timeline, and the state the page is put in first. Labels, not numbers. */
export const CHECKPOINTS: Checkpoint[] = [
  { id: 'tour-start', label: 'Tour start', at: 0, prepare: 'harvey' },
  { id: 'tour-scene2', label: 'Tour → Scene 2', at: SWITCH_AT, prepare: 'harvey' },
  { id: 'dispatch', label: 'Scene 2: dispatch', at: SCENE2_AT + 31, prepare: 'dispatch' },
  { id: 'needs', label: 'Scene 2: needs', at: SCENE2_AT + 63, prepare: 'needs' },
  { id: 'copilot', label: 'Scene 2: copilot', at: SCENE2_AT + 105, prepare: 'copilot' },
  { id: 'end', label: 'End', at: DEMO_DURATION_S, prepare: 'end' },
];

/** The sequence's steps for the read-along: the tour's, the switch, then Scene 2's. */
export const TOTAL_STEPS = TOUR.length + 1 + 19;

export type DemoStatus = 'idle' | 'preparing' | 'ready' | 'running' | 'paused' | 'finished';

export interface DemoHost {
  openHarvey(): Promise<boolean>; // Harvey replay at 2017-08-28 05:15 UTC, coloured by supply access
  openMixed(): Promise<boolean>; // the mixed run at its recorded peak
  caption(text: string | null): void; // under the mode badge
  scrollTop(): void; // instantly, to the top of the page
  stopMap(): void; // halt any camera move in flight
  log(line: string): void;
}
export interface FullDemoDeps { tour: Tour; scene: Scene2; clock: PlayerClock; host: DemoHost }

export interface LogRow { at: number; what: string; ok: boolean; note: string }

export interface FullDemo {
  status(): DemoStatus;
  line(t: number): { text: string; skipped: boolean } | null;
  stepAt(t: number): number; // 1-based step of the whole sequence at time t, 0 before the first
  tick(): void;
  /** Open the first frame (Harvey at the tour's start, REPLAY badge) and wait to be played. */
  prepare(): Promise<string | null>;
  play(): void;
  pause(): void;
  jump(id: CheckpointId): Promise<string | null>;
  log(): LogRow[];
  stop(): void;
}

export function createFullDemo({ tour, scene, clock, host }: FullDemoDeps): FullDemo {
  let status: DemoStatus = 'idle';
  const rows: LogRow[] = [];
  let swapStarted = false, swapDone = false, captionOff = false, sceneStarted = false, tourFinal = false;
  let swapFailed: string | null = null;
  let heldMs = 0;
  let busy = false;
  const note = (what: string, ok: boolean, why = '') => { rows.push({ at: Math.round(clock.time() * 10) / 10, what, ok, note: why }); host.log(`[demo] ${ok ? '' : 'SKIPPED '}${what}${why ? `: ${why}` : ''}`); };

  function resetFlags(over: { swap?: boolean; scene?: boolean } = {}) {
    swapStarted = swapDone = captionOff = !!over.swap; sceneStarted = !!over.scene; tourFinal = !!over.swap;
    swapFailed = null; heldMs = 0;
  }

  async function swap() {
    const ok = await host.openMixed();
    swapDone = true;
    if (!ok) { swapFailed = 'the mixed run could not be opened'; note('run switch', false, swapFailed); } else note('run switch', true, 'mixed run open, badge MIXED');
  }

  return {
    status: () => status,
    log: () => [...rows],
    stepAt(t) {
      if (t < SWITCH_AT) { let n = 0; TOUR.forEach((s, i) => { if (s.at <= t) n = i + 1; }); return n; }
      if (t < SCENE2_AT) return TOUR.length + 1;
      const rel = t - SCENE2_AT;
      let n = TOUR.length + 1;
      scene.steps.forEach((s, i) => { if (s.at <= rel) n = TOUR.length + 1 + i + 1; });
      return n;
    },
    line(t) {
      if (t < SWITCH_AT) {
        const l = tour.line(t);
        if (!l) return null;
        let n = -1;
        TOUR.forEach((s, i) => { if (s.at <= t) n = i; });
        // The tour reports each highlight and camera target it could not find in the page; the read-along says so, as Scene 2's does.
        return { text: l.text, skipped: tour.report().some((r) => r.step === n && !r.resolved) };
      }
      if (t < SCENE2_AT) return { text: SWITCH_LINE, skipped: false };
      const l = scene.line(Math.min(t - SCENE2_AT, SCENE2_DURATION_S));
      return l ? { text: l.text, skipped: !!l.skipped } : null;
    },
    async prepare() {
      if (busy) return null;
      busy = true; status = 'preparing';
      try {
        scene.stop(); tour.stop(); host.caption(null); clock.pause(); clock.seek(0); resetFlags();
        const ok = await host.openHarvey();
        host.scrollTop();
        if (!ok) { status = 'idle'; return 'Could not open the Harvey replay at 2017-08-28 05:15 UTC.'; }
        const why = tour.refusal();
        if (why) { status = 'idle'; return why; }
        status = 'ready';
        return null;
      } finally { busy = false; }
    },
    play() {
      if (status === 'paused') { clock.play(); status = 'running'; return; }
      if (status !== 'ready') return;
      clock.pause(); clock.seek(0); clock.play();
      tour.start();
      status = 'running';
    },
    pause() { if (status !== 'running') return; clock.pause(); host.stopMap(); status = 'paused'; },
    tick() {
      if (status !== 'running') return;
      const t = clock.time();
      if (t < SWITCH_AT) { tour.tick(); return; }
      if (!tourFinal) { tour.tick(); tourFinal = true; } // lets the tour clear its last highlight and caption; its last frame stays
      if (t >= SWAP_AT && !swapStarted) {
        swapStarted = true;
        void swap(); // opening the run clears any caption as its first, synchronous act, so the caption is set after it starts
        host.caption(SWITCH_CAPTION);
      }
      // The mixed run's data takes a moment to load. The timeline stands still (bounded) rather than let Scene 2 start on a half-loaded page.
      if (swapStarted && !swapDone && t >= MAP_HOLD_AT) {
        if (heldMs < HOLD_MAX_MS) { clock.hold(100); heldMs += 100; } else { swapDone = true; swapFailed = 'the mixed run was not ready in time'; note('run switch', false, swapFailed); }
        return;
      }
      if (t >= MAP_HOLD_AT && swapDone && !captionOff) { captionOff = true; host.caption(null); host.scrollTop(); }
      if (t >= SCENE2_AT) {
        if (!sceneStarted) {
          sceneStarted = true;
          if (swapFailed) { note('Scene 2', false, `not started: ${swapFailed}`); status = 'finished'; clock.pause(); return; }
          scene.start();
        }
        scene.tick();
        if (t >= DEMO_DURATION_S) { clock.pause(); status = 'finished'; }
      }
    },
    async jump(id) {
      const cp = CHECKPOINTS.find((c) => c.id === id)!;
      if (busy) return 'busy: the last jump has not finished';
      busy = true;
      const was = status;
      try {
        scene.stop(); tour.stop(); host.caption(null); clock.pause(); host.stopMap();
        status = 'preparing';
        let problem: string | null = null;
        if (cp.prepare === 'harvey') {
          if (!(await host.openHarvey())) problem = 'Could not open the Harvey replay at 2017-08-28 05:15 UTC.';
          else { const why = tour.refusal(); if (why) problem = why; }
          host.scrollTop();
        } else {
          if (!(await host.openMixed())) problem = 'Could not open the mixed run.';
          else {
            try { note(`resume: ${cp.label}`, true, await scene.prepare(cp.prepare as PrepareTarget)); }
            catch (e) { problem = `The page could not be put in the "${cp.label}" state: ${e instanceof Error ? e.message : String(e)}`; note(`resume: ${cp.label}`, false, problem); }
          }
          host.scrollTop();
        }
        if (problem) { status = 'idle'; return problem; }
        clock.seek(cp.at);
        if (cp.id === 'tour-start') { resetFlags(); tour.seek(0); tour.start(); }
        else if (cp.id === 'tour-scene2') { resetFlags(); tourFinal = false; }
        else if (cp.id === 'end') { resetFlags({ swap: true, scene: true }); status = 'finished'; return null; }
        else { resetFlags({ swap: true, scene: true }); scene.startFrom(cp.at - SCENE2_AT); }
        status = 'paused';
        if (was === 'running' || was === 'paused') { clock.play(); status = 'running'; }
        return null;
      } finally { busy = false; }
    },
    stop() { scene.stop(); tour.stop(); host.caption(null); clock.pause(); status = 'idle'; },
  };
}

// ---------------------------------------------------------------- the pre-flight check
export interface CheckItem { id: string; label: string; ok: boolean; detail: string; fix: string | null; reset?: boolean }
const TIMEOUT_MS = 5000;
const lim = <T>(p: Promise<T>): Promise<T> => Promise.race([p, new Promise<never>((_, rej) => setTimeout(() => rej(new Error(`no answer in ${TIMEOUT_MS / 1000} s`)), TIMEOUT_MS))]);
const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** The six readiness checks, run together within 5 s. Each reports PASS or FAIL with one line to fix it. */
export async function preflight(): Promise<CheckItem[]> {
  const item = async (id: string, label: string, fn: () => Promise<{ detail: string; fix?: string; reset?: boolean } | { ok: true; detail: string }>): Promise<CheckItem> => {
    try {
      const r = await lim(fn());
      return 'ok' in r ? { id, label, ok: true, detail: r.detail, fix: null } : { id, label, ok: false, detail: r.detail, fix: r.fix ?? null, reset: r.reset };
    } catch (e) { return { id, label, ok: false, detail: msg(e), fix: 'check that the API is running, then press Check again' }; }
  };
  const runs = lim(api.runs());
  const mixedOf = async () => (await runs).runs.find((r) => r.mode === 'mixed' && r.event != null);
  const [backend, build, harvey, mixed, rows, template] = await Promise.all([
    item('backend', 'Backend reachable', async () => {
      const s = await api.copilotStatus();
      return { ok: true as const, detail: `answered, copilot ${s.mode} mode` };
    }),
    item('build', 'Server build current', async () => {
      const [srv, want] = await Promise.all([get<{ sha: string | null; dirty: boolean }>('/needs/dev-build').catch(() => null), get<{ sha: string | null }>(`${import.meta.env.BASE_URL}__demo/sha`).catch(() => null)]);
      if (!srv) return { detail: 'the server does not report its build', fix: 'start the API with TIDEALERT_DEV_RESET=1 (it also switches Reset on)' };
      if (!want?.sha || !srv.sha) return { detail: 'a commit could not be read', fix: 'run both from the git checkout' };
      if (srv.sha !== want.sha) return { detail: `server ${srv.sha.slice(0, 7)}, checkout ${want.sha.slice(0, 7)}`, fix: 'restart the API from this checkout' };
      return { ok: true as const, detail: `${srv.sha.slice(0, 7)}${srv.dirty ? ' (backend files changed since commit)' : ''}` };
    }),
    item('harvey', 'Harvey peak loadable', async () => {
      const r = (await runs).runs.find((x) => x.mode === 'replay' && x.peak_at && x.event?.includes('Harvey'));
      if (!r) return { detail: 'no Harvey replay run', fix: 'load the Harvey replay (scripts/run_case_matcher.py 08074500 08076000 08075770)' };
      const z = await api.zones(r.id, '2017-08-28T05:15:00.000Z');
      return Date.parse(z.at) === Date.parse('2017-08-28T05:15:00Z') ? { ok: true as const, detail: `${r.id.slice(0, 8)}… at 2017-08-28 05:15 UTC` } : { detail: 'that time is not on the run', fix: 'rebuild the Harvey replay' };
    }),
    item('mixed', 'Mixed run loadable and writable', async () => {
      const m = await mixedOf();
      if (!m) return { detail: 'no mixed run', fix: 'rebuild it with scripts/mixed_harvey_scenario.py' };
      const b = await api.needs(m.id, m.window_end);
      return b.writable ? { ok: true as const, detail: `${m.id.slice(0, 8)}…, needs and pledges accept writes` } : { detail: `entries refused: ${b.blocked_reason}`, fix: 'use the mixed run, not a replay' };
    }),
    item('rows', 'Demo rows absent', async () => {
      const m = await mixedOf();
      if (!m) return { detail: 'no mixed run', fix: 'rebuild it with scripts/mixed_harvey_scenario.py' };
      const b = await api.needs(m.id, m.window_end);
      const n = Object.values(b.zones).reduce((a, z) => a + z.events.filter((e) => e.actor === OPERATOR_NAME).length + z.pledges.filter((p) => p.donor === DONOR_NAME).length, 0);
      return n === 0 ? { ok: true as const, detail: 'none on the board' } : { detail: `${n} left from an earlier run`, fix: 'press Reset', reset: true };
    }),
    item('template', 'Copilot briefing is template-only', async () => {
      const m = await mixedOf();
      if (!m) return { detail: 'no mixed run', fix: 'rebuild it with scripts/mixed_harvey_scenario.py' };
      const a = await api.ask({ run_id: m.id, question: '', intent: 'open_cases', at: m.window_end, zone_id: null, case_id: null });
      return a.mode === 'template' ? { ok: true as const, detail: 'an intent returns a fixed template, no model call' } : { detail: `answered in ${a.mode} mode`, fix: 'unset ANTHROPIC_API_KEY for the API' };
    }),
  ]);
  return [backend, build, harvey, mixed, rows, template];
}
