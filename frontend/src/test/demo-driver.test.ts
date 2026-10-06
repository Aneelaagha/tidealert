import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  END_AT_S, FREEZE_AT_S, type Host, MIN, type Snapshot, REPLAY_MIN_PER_SEC, SCRIPT, START_AT_S, clockAt, createDriver, pickCountdown, sceneStart, tickIndexAt,
} from '../dev/demo-driver';
import type { LastCall, LastCallZone } from '../lib/api';
import { countdownTone, minutesLeft } from '../lib/lastCall';

const T = (hh: number, mm: number) => Date.UTC(2017, 7, 27, hh, mm);
const ticks = Array.from({ length: 40 }, (_, i) => T(2, 0) + i * 15 * MIN); // 02:00, 02:15, ...
const lz = (id: string, cutoff: number, status: LastCallZone['status'] = 'counting'): LastCallZone => ({ zone_id: id, zone_name: `block ${id}`, status,
  cutoff_at: new Date(cutoff).toISOString(), last_call_at: new Date(cutoff).toISOString(), minutes_to_last_call: null, minutes_to_cutoff: null, hindsight: true, was_reconnected: false });
const lastCall = (zones: LastCallZone[]): LastCall => ({ run_id: 'r', mode: 'replay', at: '', label: '', available: true, reason: null,
  lead: { reply_minutes: 0, decision_minutes: 0, travel_minutes: 0, total_minutes: 0, note: '' }, counts: { counting: zones.length, passed: 0, cut_off: 0, reconnected: 0 }, zones });
const snap = (over: Partial<Snapshot> = {}): Snapshot => ({ tickAt: T(3, 15), clockMs: T(3, 15), ready: true, cases: 0, firstCaseAt: null, possibly: 100, cutOff: 0,
  freshness: ['fresh', 'fresh'], lastCall: null, ranked: [], alarms: { '08074500': T(4, 30) }, pinned: [], ...over });

describe('the replay clock', () => {
  it('moves 12 replay-minutes per real second from the start offset, and is held at the freeze', () => {
    const t0 = T(3, 15);
    expect(clockAt(0, t0)).toBe(t0);
    expect(clockAt(START_AT_S, t0)).toBe(t0);
    expect(clockAt(START_AT_S + 1, t0)).toBe(t0 + REPLAY_MIN_PER_SEC * MIN);
    expect(clockAt(FREEZE_AT_S, t0)).toBe(t0 + (FREEZE_AT_S - START_AT_S) * REPLAY_MIN_PER_SEC * MIN);
    expect(clockAt(FREEZE_AT_S + 50, t0)).toBe(clockAt(FREEZE_AT_S, t0)); // it does not run on
  });
  it('finds the replay step the clock is in (data exists per step), and none before the first', () => {
    expect(tickIndexAt(T(2, 0) - 1, ticks)).toBe(-1);
    expect(tickIndexAt(T(2, 0), ticks)).toBe(0);
    expect(tickIndexAt(T(2, 14), ticks)).toBe(0);
    expect(tickIndexAt(T(2, 15), ticks)).toBe(1);
  });
  it('starts the scene 45 minutes before the first Case, on a replay step, from the data it is given', () => {
    expect(sceneStart(T(4, 0), ticks)).toBe(T(3, 15));
    expect(sceneStart(T(4, 7), ticks)).toBe(T(3, 15)); // snapped down to a step
    expect(sceneStart(T(1, 0), ticks)).toBeNull(); // before the replay begins: no scene
  });
  it('reads a countdown as the recorded time minus the clock, never negative, and amber at an hour', () => {
    expect(minutesLeft(T(5, 0), T(3, 0))).toBe(120);
    expect(minutesLeft(T(5, 0), T(5, 30))).toBe(0);
    expect([countdownTone(61), countdownTone(60), countdownTone(1), countdownTone(0)]).toEqual(['text-slate-100', 'text-warning-orange', 'text-warning-orange', 'text-danger-red']);
  });
});

describe('the script', () => {
  it('is in time order, ends on a freeze then silence, and has no repeat or loop', () => {
    const at = SCRIPT.map((e) => e.at);
    expect(at).toEqual([...at].sort((a, b) => a - b));
    expect(SCRIPT.at(-2)).toMatchObject({ name: 'freeze-end', at: FREEZE_AT_S });
    expect(SCRIPT.at(-1)).toMatchObject({ name: 'silence', at: END_AT_S });
    expect(new Set(SCRIPT.map((e) => `${e.at}:${e.name}`)).size).toBe(SCRIPT.length);
  });
  it('reports only values taken from the snapshot: change the data and the reported value changes', () => {
    const first = SCRIPT.find((e) => e.name === 'first-case')!;
    const a = first.check(snap({ cases: 3, firstCaseAt: T(4, 0), tickAt: T(4, 0) }), {});
    const b = first.check(snap({ cases: 9, firstCaseAt: T(4, 15), tickAt: T(4, 15) }), {});
    expect(a.value).toContain('3 Cases');
    expect(b.value).toContain('9 Cases');
    expect(a.value).not.toBe(b.value);
  });
  it('does not fire the first Case on a quiet map', () => {
    expect(SCRIPT.find((e) => e.name === 'first-case')!.check(snap({ cases: 0 }), {}).ok).toBe(false);
  });
  it('does not call the start frame quiet unless no Case is open and every source is fresh', () => {
    const start = SCRIPT.find((e) => e.name === 'freeze-start')!;
    expect(start.check(snap(), {}).ok).toBe(true);
    expect(start.check(snap({ cases: 118 }), {}).ok).toBe(false);
    expect(start.check(snap({ freshness: ['fresh', 'stale'] }), {}).ok).toBe(false);
    expect(start.check(snap({ freshness: null }), {}).ok).toBe(false);
  });
  it('shows a gauge crossing only when the stored alarm lies inside the scene, the clock has passed it, and the count rose', () => {
    const ev = SCRIPT.find((e) => e.name === 'gauge-crossing-08074500')!;
    const memo = { startMs: T(3, 15), possibly0: 949 };
    expect(ev.check(snap({ clockMs: T(4, 15), possibly: 3469 }), { ...memo }).ok).toBe(false); // before the alarm
    expect(ev.check(snap({ clockMs: T(4, 30), possibly: 949 }), { ...memo }).ok).toBe(false); // the count has not risen
    const ok = ev.check(snap({ clockMs: T(4, 30), tickAt: T(4, 30), possibly: 3469 }), { ...memo });
    expect(ok.ok).toBe(true);
    expect(ok.value).toContain('04:29'.slice(0, 2)); // the stored alarm hour
    expect(ok.value).toContain('949');
    expect(ok.value).toContain('3,469');
    expect(ev.check(snap({ clockMs: T(4, 30), possibly: 3469, alarms: { '08074500': T(1, 0) } }), { ...memo }).ok).toBe(false); // alarm before the scene began
    expect(ev.check(snap({ clockMs: T(4, 30), possibly: 3469, alarms: null }), { ...memo }).ok).toBe(false);
  });
  it('shows the Cases growing only against the count the scene actually opened with', () => {
    const ev = SCRIPT.find((e) => e.name === 'cases-growth')!;
    expect(ev.check(snap({ cases: 11 }), { firstCases: 3 }).value).toBe('Cases 3 → 11 at the 03:15 UTC step');
    expect(ev.check(snap({ cases: 3 }), { firstCases: 3 }).ok).toBe(false);
    expect(ev.check(snap({ cases: 11 }), {}).ok).toBe(false);
  });
});

describe('picking a real countdown', () => {
  const s = snap({ clockMs: T(5, 0), lastCall: lastCall([lz('a', T(5, 45)), lz('b', T(7, 0)), lz('c', T(8, 45)), lz('d', T(8, 45))]) });
  it('takes the soonest recorded cut-off that is far enough ahead, and never one already shown', () => {
    expect(pickCountdown(s, 30)?.zone_id).toBe('a');
    expect(pickCountdown({ ...s, clockMs: T(5, 20) }, 30)?.zone_id).toBe('b'); // a zone that is too close is not picked
    expect(pickCountdown({ ...s, pinned: ['a'] }, 60)?.zone_id).toBe('b');
    expect(pickCountdown({ ...s, pinned: ['a', 'b'] }, 60)?.zone_id).toBe('c');
    expect(pickCountdown({ ...s, clockMs: T(8, 30) }, 60)).toBeNull(); // nothing left an hour ahead: no countdown, not a made-up one
  });
  it('ignores zones that are not counting down', () => {
    expect(pickCountdown(snap({ clockMs: T(5, 0), lastCall: lastCall([lz('x', T(9, 0), 'cut_off')]) }), 30)).toBeNull();
    expect(pickCountdown(snap({ lastCall: null }), 30)).toBeNull();
  });
});

describe('the driver', () => {
  let nowMs = 0;
  beforeEach(() => { vi.useFakeTimers(); nowMs = 0; });
  afterEach(() => { vi.useRealTimers(); });

  function run(snapshotAt: (clock: number) => Snapshot, script = SCRIPT) {
    const calls = { go: [] as number[], pinned: [] as string[], pulses: [] as string[], frozen: 0, captions: [] as (string | null)[], clocks: [] as number[] };
    const host: Host = {
      snapshot: () => snapshotAt(calls.clocks.at(-1) ?? T(3, 15)),
      goToTick: (i) => calls.go.push(i), setClock: (ms) => calls.clocks.push(ms), pinZone: (id) => calls.pinned.push(id), pulseZone: (id) => calls.pulses.push(id),
      caption: (c) => calls.captions.push(c), frozen: () => { calls.frozen++; },
    };
    const d = createDriver(host, ticks, T(3, 15), script, () => nowMs);
    d.start();
    const advance = (to: number) => { while (nowMs < to * 1000) { nowMs += 100; vi.advanceTimersByTime(100); } };
    return { d, calls, advance };
  }
  const quiet = (clock: number) => snap({ clockMs: clock, tickAt: ticks[tickIndexAt(clock, ticks)], cases: 0, freshness: ['fresh'] });

  it('advances the playhead step by step, freezes at the freeze offset, stops at the end, and never runs again', () => {
    const { d, calls, advance } = run(quiet);
    advance(FREEZE_AT_S + 1);
    const last = calls.clocks.at(-1)!;
    expect(last).toBe(clockAt(FREEZE_AT_S, T(3, 15)));
    expect(calls.frozen).toBe(1);
    expect(calls.go).toEqual([...calls.go].sort((a, b) => a - b)); // the playhead only moves forward
    expect(new Set(calls.go).size).toBe(calls.go.length); // each step is requested once: the existing slider path
    advance(END_AT_S + 5);
    expect(d.running()).toBe(false);
    const n = calls.clocks.length;
    advance(END_AT_S + 60);
    expect(calls.clocks.length).toBe(n); // no loop: nothing happens after it stops
    expect(calls.frozen).toBe(1);
  });
  it('captions the fast-forward while it plays and says it is paused after', () => {
    const { calls, advance } = run(quiet);
    advance(5);
    expect(calls.captions).toContain('Replay playing at 12 min/s');
    advance(FREEZE_AT_S + 1);
    expect(calls.captions.at(-1)).toBe('Replay paused');
  });
  it('skips, and logs, an event the real data does not satisfy: it never fires one on a quiet map', () => {
    const { d, advance } = run(quiet);
    advance(END_AT_S + 1);
    const first = d.log().find((e) => e.name === 'first-case')!;
    expect(first.ok).toBe(false);
    expect(first.firedAt).toBeNull();
    expect(first.value).toMatch(/^SKIPPED/);
  });
  it('waits for the data of a replay step before judging an event, and skips if it never arrives', () => {
    const { d, advance } = run((c) => ({ ...quiet(c), ready: false, cases: 5, firstCaseAt: T(4, 0) }));
    advance(END_AT_S + 1);
    expect(d.log().find((e) => e.name === 'first-case')).toMatchObject({ ok: false, value: 'SKIPPED: the data for this replay step has not arrived' });
  });
  it('fires an event once, with the value the data gave, and acts on it', () => {
    const { d, calls, advance } = run((c) => snap({ clockMs: c, tickAt: ticks[tickIndexAt(c, ticks)], cases: 0, freshness: ['fresh'], ranked: [{ zoneId: 'zz', name: 'block zz', caseId: null, group: 0, access: 'isolated', since: null, assigned: false, priority: 'high', word: null, open: 0 }] }));
    advance(FREEZE_AT_S + 1);
    const ring = d.log().find((e) => e.name === 'pulse-ring')!;
    expect(ring.ok).toBe(true);
    expect(ring.value).toContain('block zz');
    expect(calls.pulses).toEqual(['zz']); // once
  });
});

describe('keeping it out of the product', () => {
  const SRC = join(__dirname, '..');
  const files = (dir: string): string[] => readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? (n === 'test' ? [] : files(p)) : /\.(ts|tsx)$/.test(n) ? [p] : [];
  });
  it('is imported nowhere except behind the dev gate in App', () => {
    const importers = files(SRC).filter((f) => !relative(SRC, f).startsWith('dev') && /from ['"]\.{1,2}\/(dev|\.\.\/dev)/.test(readFileSync(f, 'utf8')) || (/import\(['"]\.\/dev\//.test(readFileSync(f, 'utf8')) && !relative(SRC, f).startsWith('dev')));
    expect(importers.map((f) => relative(SRC, f))).toEqual(['App.tsx']);
    const app = readFileSync(join(SRC, 'App.tsx'), 'utf8');
    expect(app).toMatch(/import\.meta\.env\.DEV \? lazy\(\(\) => import\('\.\/dev\/DevPanel'\)\) : null/);
    expect(app).toMatch(/DEV_ON = import\.meta\.env\.DEV && typeof window !== 'undefined' && new URLSearchParams\(window\.location\.search\)\.get\('dev'\) === '1'/);
    expect(app).toMatch(/\{DEV_ON && DevPanel && devHost &&/);
  });
  it('the production-reachable pieces use no driver code', () => {
    for (const f of ['lib/pulse.ts', 'lib/lastCall.ts', 'components/LastCallPanel.tsx', 'components/Header.tsx', 'components/ZoneMap.tsx']) {
      expect(readFileSync(join(SRC, f), 'utf8'), f).not.toMatch(/demo-driver|createDriver|DevPanel/);
    }
  });
  it('types in no data: the script has no case count, gauge value, zone id, colour or countdown literal', () => {
    const code = readFileSync(join(SRC, 'dev', 'demo-driver.ts'), 'utf8').replace(/\/\/.*$/gm, '');
    const script = code.slice(code.indexOf('export const SCRIPT'), code.indexOf('export interface LogEntry'));
    expect(script).not.toMatch(/\b(elevated|extreme)\b|#[0-9a-fA-F]{6}|zone_id: '|cases: \d|possibly: \d/);
    expect(script.match(/\bevent\(([\w_]+|\d+),/g)?.length).toBe(SCRIPT.length); // every entry is an offset, a name and a check, nothing else
    expect(script).not.toMatch(/Math\.random|fetch\(/);
  });
});
