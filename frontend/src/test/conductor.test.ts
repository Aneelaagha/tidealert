import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  BEATS, type Host, MIN, PACING_ISOLATION, PACING_LISTENING, SCRIPT, SCRIPT_LISTENING, SCRIPT_OFFLINE, type Snapshot, clockAt, createConductor, listeningFacts, pickCountdown,
  stepAtOrBefore, tickIndexAt,
} from '../dev/conductor';
import { PlayerClock } from '../dev/TimelinePlayer';
import type { Case, Contribution, LastCall, LastCallZone, ZonesResponse } from '../lib/api';
import { countdownTone, minutesLeft } from '../lib/lastCall';

const T = (hh: number, mm: number) => Date.UTC(2017, 7, 27, hh, mm);
const ticks = Array.from({ length: 60 }, (_, i) => T(2, 0) + i * 15 * MIN); // 02:00, 02:15, ...
const lz = (id: string, cutoff: number, status: LastCallZone['status'] = 'counting'): LastCallZone => ({ zone_id: id, zone_name: `block ${id}`, status,
  cutoff_at: new Date(cutoff).toISOString(), last_call_at: new Date(cutoff).toISOString(), minutes_to_last_call: null, minutes_to_cutoff: null, hindsight: true, was_reconnected: false });
const lastCall = (zones: LastCallZone[]): LastCall => ({ run_id: 'r', mode: 'replay', at: '', label: '', available: true, reason: null,
  lead: { reply_minutes: 0, decision_minutes: 0, travel_minutes: 0, total_minutes: 0, note: '' }, counts: { counting: zones.length, passed: 0, cut_off: 0, reconnected: 0 }, zones });
const snap = (over: Partial<Snapshot> = {}): Snapshot => ({ mode: 'replay', tickAt: T(3, 15), clockMs: T(3, 15), ready: true, cases: 0, firstCaseAt: null, possibly: 100, cutOff: 0,
  headlineCutOff: 10, headlineFlagged: 40, freshness: ['fresh', 'fresh'], lastCall: null, aerial: null, ranked: [], listening: null, offline: null, pinned: [], ...over });

// The strings below are what the listening engine stored for the scenario (copied from /cases at 2026-09-10 14:45 UTC), not invented ones.
const k = (engine: string, direction: string, rule_fragment: string): Contribution => ({ engine, direction, engine_confidence: 0.8, effective_confidence: 0.8, independent_sources: 1,
  first_observed_at: '2026-09-10T14:15:00Z', last_confirmed_at: '2026-09-10T14:15:00Z', rule_fragment });
const c = (id: string, zone: string, household: string | null, engines: string[], sentence: string, contributions: Contribution[]): Case => ({ id, zone_id: zone, household_id: household,
  status: 'open', confidence_word: 'single_source', opened_at: '2026-09-10T14:15:00Z', inference_sentence: sentence, support: 0.8, contradiction: 0, fresh_sources: 1, engines, contributions, tasks: [] });
const LATE = c('c1', 'A', 'h1', ['silence'], 'Household has not answered a check-in sent at 2026-09-10 14:00 UTC after 15 min', [
  k('listening', 'procedural', '[2026-09-10T14:15:00+00:00] cascade escalated_voice: no SMS reply after 15 min'),
  k('silence', 'supports', "[2026-09-10T14:15:00+00:00] late: probe e3670a03 unanswered after 15 min")]);
const HELP = (id: string, zone: string, hh: string, depth?: string) => c(id, zone, hh, ['listening'], 'Household replied that it needs help; a water-depth question has been sent.', [
  k('listening', 'supports', '[2026-09-10T14:15:00+00:00] help request: replied HELP by sms; depth follow-up sent; confidence 0.80 = source base (sms)'),
  ...(depth ? [k('listening', 'supports', `[2026-09-10T14:30:00+00:00] reported ${depth}-deep water (single report: visible, does not change the zone); confidence 0.80`)] : [])]);
const BLOCK = c('z1', 'A', null, ['listening'], 'Several households in this street block independently report flood water at least knee-deep.', [
  k('listening', 'supports', '[2026-09-10T14:45:00+00:00] corroborated depth reports: 2 households reported flood depth within 27 min (knee, waist); zone risk_level unknown -> extreme')]);
const zonesAt = (level: string) => ({ features: [{ properties: { zone_id: 'A', name: 'Synthetic listening block A', risk_level: level } }] }) as unknown as ZonesResponse;

describe('the run clock', () => {
  it('moves at each beat\'s own speed from its start offset, and is held at its freeze', () => {
    const t0 = T(3, 15);
    for (const p of [PACING_ISOLATION, PACING_LISTENING]) {
      expect(clockAt(0, t0, p)).toBe(t0);
      expect(clockAt(p.startAtS, t0, p)).toBe(t0);
      expect(clockAt(p.startAtS + 2, t0, p)).toBe(t0 + 2 * p.minPerSec * MIN);
      expect(clockAt(p.freezeAtS, t0, p)).toBe(t0 + (p.freezeAtS - p.startAtS) * p.minPerSec * MIN);
      expect(clockAt(p.freezeAtS + 50, t0, p)).toBe(clockAt(p.freezeAtS, t0, p)); // it does not run on
    }
    expect([PACING_ISOLATION.minPerSec, PACING_ISOLATION.freezeAtS]).toEqual([12, 40]); // as briefed
  });
  it('puts the listening scenario\'s three active steps at about 13, 23 and 33 seconds', () => {
    const t0 = Date.UTC(2026, 8, 10, 14, 0);
    const secondsTo = (min: number) => PACING_LISTENING.startAtS + min / PACING_LISTENING.minPerSec;
    expect([15, 30, 45].map(secondsTo)).toEqual([13, 23, 33]);
    expect(clockAt(33, t0, PACING_LISTENING)).toBe(Date.UTC(2026, 8, 10, 14, 45));
  });
  it('finds the run step the clock is in (data exists per step), and none before the first', () => {
    expect(tickIndexAt(T(2, 0) - 1, ticks)).toBe(-1);
    expect(tickIndexAt(T(2, 0), ticks)).toBe(0);
    expect(tickIndexAt(T(2, 14), ticks)).toBe(0);
    expect(tickIndexAt(T(2, 15), ticks)).toBe(1);
  });
  it('opens on the last step at or before the wanted time, and refuses a time before the run begins', () => {
    expect(stepAtOrBefore(T(3, 15), ticks)).toBe(T(3, 15));
    expect(stepAtOrBefore(T(3, 22), ticks)).toBe(T(3, 15));
    expect(stepAtOrBefore(T(1, 0), ticks)).toBeNull();
  });
  it('reads a countdown as the recorded time minus the clock, never negative, and amber at an hour', () => {
    expect(minutesLeft(T(5, 0), T(3, 0))).toBe(120);
    expect(minutesLeft(T(5, 0), T(5, 30))).toBe(0);
    expect([countdownTone(61), countdownTone(60), countdownTone(1), countdownTone(0)]).toEqual(['text-slate-100', 'text-warning-orange', 'text-warning-orange', 'text-danger-red']);
  });
});

describe('the scripts', () => {
  it('are in time order, end on a freeze then silence, and have no repeat or loop', () => {
    for (const [script, p] of [[SCRIPT, PACING_ISOLATION], [SCRIPT_LISTENING, PACING_LISTENING]] as const) {
      const at = script.map((e) => e.at);
      expect(at).toEqual([...at].sort((a, b) => a - b));
      expect(script.at(-2)).toMatchObject({ name: 'freeze-end', at: p.freezeAtS });
      expect(script.at(-1)).toMatchObject({ name: 'silence', at: p.endAtS });
      expect(new Set(script.map((e) => `${e.at}:${e.name}`)).size).toBe(script.length);
    }
  });
  it('keep the briefed offsets', () => {
    expect(SCRIPT.map((e) => [e.at, e.name]).slice(0, 6)).toEqual([[0, 'open-harvey'], [3, 'playhead-start'], [8, 'cutoff-climbs'], [15, 'last-call-1'], [25, 'aerial-populates'], [35, 'last-call-2']]);
    expect(SCRIPT_LISTENING.map((e) => e.at).slice(0, 9)).toEqual([0, 3, 8, 15, 20, 25, 30, 35, PACING_LISTENING.freezeAtS]);
  });
  it('show the REPLAY badge on Harvey and the SCENARIO badge on the scenario, and refuse the wrong run', () => {
    expect(SCRIPT[0].check(snap({ mode: 'replay' }), {}).ok).toBe(true);
    expect(SCRIPT[0].check(snap({ mode: 'mixed' }), {}).ok).toBe(false);
    expect(SCRIPT_LISTENING[0].check(snap({ mode: 'scenario' }), {}).ok).toBe(true);
    expect(SCRIPT_LISTENING[0].check(snap({ mode: 'replay' }), {}).ok).toBe(false);
  });
  it('report only values taken from the snapshot: change the data and the reported value changes', () => {
    const ev = SCRIPT.find((e) => e.name === 'cutoff-climbs')!;
    const a = ev.check(snap({ headlineCutOff: 30 }), { headline0: 10 });
    const b = ev.check(snap({ headlineCutOff: 55 }), { headline0: 10 });
    expect([a.ok, b.ok]).toEqual([true, true]);
    expect(a.value).toContain('10 → 30');
    expect(b.value).toContain('10 → 55');
  });
  it('do not claim the cut-off count climbs when it falls or holds (Harvey after the 27 Aug peak: 147 → 112)', () => {
    const ev = SCRIPT.find((e) => e.name === 'cutoff-climbs')!;
    expect(ev.check(snap({ headlineCutOff: 112 }), { headline0: 147 }).ok).toBe(false);
    expect(ev.check(snap({ headlineCutOff: 147 }), { headline0: 147 }).ok).toBe(false);
    expect(ev.check(snap({ headlineCutOff: null }), { headline0: 147 }).ok).toBe(false);
  });
  it('do not show a countdown when no zone is counting down far enough ahead', () => {
    const ev = SCRIPT.find((e) => e.name === 'last-call-1')!;
    expect(ev.check(snap({ lastCall: lastCall([]) }), {}).ok).toBe(false);
    expect(ev.check(snap({ lastCall: lastCall([lz('a', T(3, 20))]) }), {}).ok).toBe(false); // 5 min ahead: too close to be a countdown
    expect(ev.check(snap({ lastCall: lastCall([lz('a', T(5, 15), 'cut_off')]) }), {}).ok).toBe(false);
    expect(ev.check(snap({ lastCall: lastCall([lz('a', T(5, 15))]) }), {}).ok).toBe(true);
  });
  it('populate Aerial priority only from a real ranking, and say which rows', () => {
    const ev = SCRIPT.find((e) => e.name === 'aerial-populates')!;
    expect(ev.check(snap({ aerial: [] }), {}).ok).toBe(false);
    expect(ev.check(snap({ aerial: null }), {}).ok).toBe(false);
    const r = ev.check(snap({ aerial: [{ rank: 1, zoneId: 'zq', name: 'block q', minutes: 125 }, { rank: 2, zoneId: 'zr', name: 'block r', minutes: 90 }] }), {});
    expect(r.ok).toBe(true);
    expect(r.value).toContain('1. block q (125 min)');
  });
});

describe('what the listening scenario\'s Cases say', () => {
  const cases = [LATE, HELP('h2', 'A', 'h2', 'knee'), HELP('h3', 'A', 'h3', 'waist'), HELP('h4', 'B', 'h4', 'ankle'), BLOCK];
  it('counts late households, cascade steps, HELP replies, depth reports, block Cases and raised zones from the engines\' own text', () => {
    const f = listeningFacts(cases, zonesAt('extreme'));
    expect(f.lateHouseholds).toBe(1);
    expect(f.cascadeSteps).toEqual(['escalated_voice']);
    expect(f.helpHouseholds).toBe(3);
    expect(f.depths.map((d) => d.depth).sort()).toEqual(['ankle', 'knee', 'waist']);
    expect(f.zoneCases).toHaveLength(1);
    expect(f.raisedZones).toEqual([{ zoneId: 'A', name: 'Synthetic listening block A', level: 'extreme' }]);
  });
  it('counts nothing on a quiet scenario, and nothing is raised while the zone reads unknown', () => {
    const f = listeningFacts([], zonesAt('unknown'));
    expect(f).toEqual({ lateHouseholds: 0, lateZoneIds: [], cascadeSteps: [], helpHouseholds: 0, depths: [], zoneCases: [], raisedZones: [] });
  });
  it('fires each event only once its evidence is in the step, and not before', () => {
    const quiet = snap({ mode: 'scenario', listening: listeningFacts([], zonesAt('unknown')) });
    const loud = snap({ mode: 'scenario', listening: listeningFacts(cases, zonesAt('extreme')) });
    for (const name of ['cascade-fires', 'first-reply-help', 'depth-knee', 'second-reply', 'corroboration-2', 'case-opens']) {
      const ev = SCRIPT_LISTENING.find((e) => e.name === name)!;
      expect([name, ev.check(quiet, {}).ok]).toEqual([name, false]);
      expect([name, ev.check(loud, {}).ok]).toEqual([name, true]);
    }
  });
  it('does not call one depth report a corroboration, and does not raise the zone on a single report', () => {
    const one = snap({ mode: 'scenario', listening: listeningFacts([HELP('h2', 'A', 'h2', 'knee')], zonesAt('unknown')) });
    expect(SCRIPT_LISTENING.find((e) => e.name === 'depth-knee')!.check(one, {}).ok).toBe(true);
    expect(SCRIPT_LISTENING.find((e) => e.name === 'second-reply')!.check(one, {}).ok).toBe(false);
    expect(SCRIPT_LISTENING.find((e) => e.name === 'corroboration-2')!.check(one, {}).ok).toBe(false);
  });
  it('reports the engine\'s own words for the corroboration and the Case', () => {
    const loud = snap({ mode: 'scenario', listening: listeningFacts(cases, zonesAt('extreme')) });
    expect(SCRIPT_LISTENING.find((e) => e.name === 'corroboration-2')!.check(loud, {}).value).toContain('zone risk_level unknown -> extreme');
    expect(SCRIPT_LISTENING.find((e) => e.name === 'case-opens')!.check(loud, {}).value).toContain('Several households in this street block');
  });
});

describe('picking a real countdown', () => {
  const s = (zones: LastCallZone[], pinned: string[] = []) => snap({ lastCall: lastCall(zones), pinned });
  it('takes the soonest recorded cut-off that is far enough ahead, and never one already shown', () => {
    const zones = [lz('late', T(9, 0)), lz('soon', T(5, 0)), lz('near', T(3, 20))];
    expect(pickCountdown(s(zones), 20)?.zone_id).toBe('soon');
    expect(pickCountdown(s(zones, ['soon']), 20)?.zone_id).toBe('late');
  });
  it('ignores zones that are not counting down', () => {
    expect(pickCountdown(s([lz('x', T(9, 0), 'cut_off'), lz('y', T(9, 0), 'reconnected')]), 20)).toBeNull();
  });
});

describe('the conductor on the shared clock', () => {
  let nowMs = 0;

  type Look = { label: string; spec: unknown; zones: string[]; why?: string };
  type Calls = { looks: Look[]; go: number[]; pinned: string[]; pulses: string[]; revealed: string[]; offline: boolean[]; frozen: number; captions: (string | null)[]; clocks: number[] };
  function run(snapshotAt: (clock: number) => Snapshot, beat: 'isolation' | 'listening' | 'offline' = 'isolation', lag?: { ms: number }) {
    nowMs = 0;
    const calls: Calls = { looks: [], go: [], pinned: [], pulses: [], revealed: [], offline: [], frozen: 0, captions: [], clocks: [] };
    const host: Host = {
      snapshot: () => snapshotAt(calls.clocks.at(-1) ?? T(3, 15)),
      goToTick: (i) => calls.go.push(i), setClock: (ms) => calls.clocks.push(ms), pinZone: (id) => calls.pinned.push(id), pulseZone: (id) => calls.pulses.push(id),
      reveal: (p) => calls.revealed.push(p), caption: (cap) => calls.captions.push(cap), frozen: () => { calls.frozen++; }, offline: (on) => calls.offline.push(on), look: (label, spec, zones, why) => calls.looks.push({ label, spec, zones, why }),
    };
    void lag;
    const clock = new PlayerClock(() => nowMs);
    const c = createConductor(host, ticks, T(3, 15), beat, clock);
    clock.play();
    c.start();
    const advance = (to: number) => { while (nowMs < to * 1000) { nowMs += 100; c.tick(); } };
    return { c, clock, calls, advance };
  }
  const quiet = (clock: number) => snap({ clockMs: clock, tickAt: ticks[tickIndexAt(clock, ticks)], cases: 0, headlineCutOff: 0, freshness: ['fresh'] });
  const FREEZE = PACING_ISOLATION.freezeAtS;

  it('advances the playhead step by step, freezes at the freeze offset, stops at the end, and never runs again', () => {
    const { c, calls, advance } = run(quiet);
    advance(FREEZE + 1);
    expect(calls.clocks.at(-1)).toBe(clockAt(FREEZE, T(3, 15), PACING_ISOLATION));
    expect(calls.frozen).toBe(1);
    expect(calls.go).toEqual([...calls.go].sort((a, b) => a - b)); // the playhead only moves forward
    expect(new Set(calls.go).size).toBe(calls.go.length); // each step is requested once: the existing slider path
    advance(PACING_ISOLATION.endAtS + 5);
    expect(c.running()).toBe(false);
    const n = calls.clocks.length;
    advance(PACING_ISOLATION.endAtS + 60);
    expect(calls.clocks.length).toBe(n); // no loop: nothing happens after it stops
    expect(calls.frozen).toBe(1);
  });
  it('captions the fast-forward while it plays and says it is paused after, for each beat', () => {
    for (const beat of ['isolation', 'listening'] as const) {
      const { calls, advance } = run(quiet, beat);
      advance(5);
      expect(calls.captions).toContain(BEATS[beat].caption(BEATS[beat].pacing));
      advance(BEATS[beat].pacing.freezeAtS + 1);
      expect(calls.captions.at(-1)).toBe('Paused');
    }
    expect(BEATS.isolation.caption(PACING_ISOLATION)).toBe('Replay playing at 12 min/s');
  });
  it('stands still while paused, picks up where it left off, and runs at the chosen speed', () => {
    const { clock, calls, advance } = run(quiet);
    advance(10);
    const at10 = calls.clocks.at(-1)!;
    clock.pause();
    advance(30); // 20 s pass while paused
    expect(calls.clocks.at(-1)).toBe(at10);
    clock.play();
    advance(32);
    expect(calls.clocks.at(-1)).toBe(clockAt(12, T(3, 15), PACING_ISOLATION)); // 10 s + 2 s of timeline, not 22
    clock.setSpeed(1.5);
    advance(34);
    expect(calls.clocks.at(-1)).toBe(clockAt(12 + 3, T(3, 15), PACING_ISOLATION)); // 2 wall s at 1.5x = 3 timeline s
  });
  it('skips to a step: events before it are logged as not run, never as fired, and the playhead jumps to its time', () => {
    const { c, clock, calls, advance } = run((cl) => ({ ...quiet(cl), aerial: [{ rank: 1, zoneId: 'zq', name: 'block q', minutes: 125 }] }));
    c.seek(c.steps.findIndex((s) => s.label === 'aerial-populates'));
    expect(clock.time()).toBe(25);
    advance(26);
    const log = c.log();
    expect(log.find((e) => e.name === 'cutoff-climbs')).toMatchObject({ ok: false, value: 'NOT RUN: skipped past to aerial-populates' });
    expect(log.find((e) => e.name === 'last-call-1')).toMatchObject({ ok: false });
    expect(log.find((e) => e.name === 'aerial-populates')).toMatchObject({ ok: true });
    expect(calls.clocks.at(-1)!).toBeGreaterThanOrEqual(clockAt(25, T(3, 15), PACING_ISOLATION));
  });
  it('skips, and logs, an event the real data does not satisfy: it never fires one on a quiet map', () => {
    const { c, calls, advance } = run(quiet);
    advance(PACING_ISOLATION.endAtS + 1);
    for (const name of ['cutoff-climbs', 'last-call-1', 'aerial-populates', 'last-call-2']) {
      const e = c.log().find((x) => x.name === name)!;
      expect([name, e.ok, e.firedAt]).toEqual([name, false, null]);
      expect(e.value).toMatch(/^SKIPPED/);
    }
    expect(calls.pinned).toEqual([]);
    expect(calls.revealed).toEqual([]);
  });
  it('waits for the data of a run step before judging an event, and skips if it never arrives', () => {
    const { c, advance } = run((cl) => ({ ...quiet(cl), ready: false, headlineCutOff: 99 }));
    advance(400); // every step is held for its data up to the limit, so the beat takes longer; it still ends and still skips
    expect(c.running()).toBe(false);
    expect(c.log().find((e) => e.name === 'cutoff-climbs')).toMatchObject({ ok: false, value: 'SKIPPED: the data for this run step has not arrived' });
  });
  it('fires an event once, with the value the data gave, acts on it, and reveals Aerial priority only then', () => {
    const rows = [{ rank: 1, zoneId: 'zq', name: 'block q', minutes: 125 }];
    const { c, calls, advance } = run((cl) => ({ ...quiet(cl), aerial: rows }));
    advance(FREEZE + 1);
    const a = c.log().find((e) => e.name === 'aerial-populates')!;
    expect(a.ok).toBe(true);
    expect(a.firedAt).toBeGreaterThanOrEqual(25);
    expect(a.value).toContain('block q');
    expect(calls.revealed).toEqual(['aerial']); // once
  });
  it('holds Aerial priority back until its cue, on the Harvey beat only', () => {
    expect(BEATS.isolation.hidden).toEqual(['aerial']);
    expect(BEATS.listening.hidden).toEqual([]);
  });
  it('holds the beat\'s own time while a due event\'s step is still loading, so a slow load makes it slower and never different', () => {
    const runWithLag = (lag: number) => {
      let sentAt = 0; let sentTo = -1;
      const clocks: number[] = [];
      nowMs = 0;
      const host: Host = {
        snapshot: () => { const i = tickIndexAt(clocks.at(-1) ?? T(3, 15), ticks); const ready = i === sentTo && nowMs - sentAt >= lag;
          return snap({ clockMs: clocks.at(-1) ?? T(3, 15), tickAt: ticks[i], ready, headlineCutOff: 10 + i, aerial: [{ rank: 1, zoneId: `z${i}`, name: `q${i}`, minutes: i }], cases: i }); },
        goToTick: (i) => { sentTo = i; sentAt = nowMs; }, setClock: (ms) => clocks.push(ms), pinZone: () => {}, pulseZone: () => {}, reveal: () => {}, caption: () => {}, frozen: () => {}, offline: () => {}, look: () => {},
      };
      const clock = new PlayerClock(() => nowMs);
      const c = createConductor(host, ticks, T(3, 15), 'isolation', clock);
      clock.play(); c.start();
      while (c.running() && nowMs < 400_000) { nowMs += 100; c.tick(); }
      return { log: c.log().map((e) => ({ name: e.name, ok: e.ok, replay: e.replay, value: e.value })), wall: nowMs };
    };
    const fast = runWithLag(100);
    const slow = runWithLag(1800);
    expect(slow.log).toEqual(fast.log);
    expect(slow.wall).toBeGreaterThan(fast.wall); // the slow load took longer on the wall clock
    expect(fast.log.find((e) => e.name === 'aerial-populates')).toMatchObject({ ok: true }); // and the scene still played
  });
  it('lets a listening event wait past its offset for the step that holds its evidence, and fires it then, not at the offset', () => {
    const start = Date.UTC(2026, 8, 10, 14, 0);
    const stepsL = Array.from({ length: 13 }, (_, i) => start + i * 15 * MIN);
    nowMs = 0;
    const clocks: number[] = [];
    const snapL = (cl: number) => snap({ mode: 'scenario', clockMs: cl, tickAt: stepsL[tickIndexAt(cl, stepsL)],
      listening: listeningFacts(cl >= clockAt(18, start, PACING_LISTENING) ? [HELP('h2', 'A', 'h2')] : [], zonesAt('unknown')) });
    const host: Host = { snapshot: () => snapL(clocks.at(-1) ?? start), goToTick: () => {}, setClock: (ms) => clocks.push(ms), pinZone: () => {}, pulseZone: () => {},
                         reveal: () => {}, caption: () => {}, frozen: () => {}, offline: () => {}, look: () => {} };
    const clock = new PlayerClock(() => nowMs);
    const c = createConductor(host, stepsL, start, 'listening', clock);
    clock.play(); c.start();
    while (nowMs < 25_000) { nowMs += 100; c.tick(); }
    const e = c.log().find((x) => x.name === 'first-reply-help')!;
    expect(e.ok).toBe(true);
    expect(e.firedAt).toBeGreaterThanOrEqual(18);
    expect(e.value).toContain('1 household replied HELP');
  });
});

describe('the offline beat', () => {
  let nowMs = 0;
  const off = (o: Partial<NonNullable<Snapshot['offline']>>) => snap({ offline: { state: 'offline', offlineSince: 1, lastLoadedAt: 1, recoveredAt: null, banner: true, cached: 3, unknown: 0, ...o } });
  const ev = (n: string) => SCRIPT_OFFLINE.find((e) => e.name === n)!;
  it('is the briefed 15 seconds: switch at 0, banner at 2, hold at 8, recover at 15', () => {
    expect(SCRIPT_OFFLINE.map((e) => [e.at, e.name]).slice(0, 4)).toEqual([[0, 'offline-on'], [2, 'offline-banner'], [8, 'offline-hold'], [15, 'recover']]);
  });
  it('turns the switch on and off through the host, and reads the banner from the page, not from the script', () => {
    const acted: boolean[] = [];
    const host = { offline: (on: boolean) => acted.push(on) } as unknown as Host;
    ev('offline-on').check(snap(), {}).act?.(host);
    ev('recover').check(snap(), {}).act?.(host);
    expect(acted).toEqual([true, false]);
    expect(ev('offline-banner').check(off({}), {}).ok).toBe(true);
    expect(ev('offline-banner').check(off({ banner: false }), {}).ok).toBe(false); // no banner on the page: not claimed
    expect(ev('offline-banner').check(off({ cached: 0, unknown: 0 }), {}).ok).toBe(false);
    expect(ev('offline-banner').check(snap(), {}).ok).toBe(false);
  });
  it('confirms the refresh only when the page is online again and has re-read its view after recovering', () => {
    const on = (o: Partial<NonNullable<Snapshot['offline']>>) => off({ state: 'online', banner: false, recoveredAt: 100, lastLoadedAt: 250, ...o });
    expect(ev('confirm-refresh').check(on({}), {}).ok).toBe(true);
    expect(ev('confirm-refresh').check(on({ lastLoadedAt: 50 }), {}).ok).toBe(false); // the view was not re-read yet
    expect(ev('confirm-refresh').check(on({ state: 'offline' }), {}).ok).toBe(false);
    expect(ev('confirm-refresh').check(on({ banner: true }), {}).ok).toBe(false);
  });
  it('runs its checks without a playhead and ends by itself', () => {
    const clocks = { n: 0 };
    nowMs = 0;
    const host = { snapshot: () => off({}), goToTick: () => { clocks.n++; }, setClock: () => { clocks.n++; }, caption: () => { clocks.n++; }, offline: () => {}, look: () => { clocks.n++; } } as unknown as Host;
    const clock = new PlayerClock(() => nowMs);
    const c = createConductor(host, [], T(3, 15), 'offline', clock);
    clock.play(); c.start();
    while (c.running() && nowMs < 60_000) { nowMs += 100; c.tick(); }
    expect(clocks.n).toBe(0); // it never touches the slider
    expect(c.log().find((e) => e.name === 'offline-banner')).toMatchObject({ ok: true });
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
    expect(app).toMatch(/import\.meta\.env\.DEV \? lazy\(\(\) => import\('\.\/dev\/DevOverlay'\)\) : null/);
    expect(app).toMatch(/DEV_ON = import\.meta\.env\.DEV && typeof window !== 'undefined' && new URLSearchParams\(window\.location\.search\)\.get\('dev'\) === '1'/);
    expect(app).toMatch(/TOUR_ON = import\.meta\.env\.DEV && typeof window !== 'undefined' && new URLSearchParams\(window\.location\.search\)\.get\('tour'\) === '1'/);
    expect(app).toMatch(/\{DevOverlay && DEV_ON && !TOUR_ON && devHost && /); // both gates at once: the tour mounts alone
    expect(app).toMatch(/\{DevOverlay && TOUR_ON && tourData && /);
  });
  it('the page takes no value from either tool, and the overlay loads each tool only by a dynamic import, so a gate loads only its own code', () => {
    const app = readFileSync(join(SRC, 'App.tsx'), 'utf8');
    const devImports = app.split('\n').filter((l) => /from '\.\/dev\//.test(l));
    expect(devImports.every((l) => /^import type /.test(l))).toBe(true); // types are erased: nothing from dev/ is fetched until its gate lazy-loads the overlay
    const overlay = readFileSync(join(SRC, 'dev', 'DevOverlay.tsx'), 'utf8');
    expect(overlay).not.toMatch(/^import (?!type )[^\n]*from '\.\/(tour|conductor)'/m);
    expect(overlay).toMatch(/await import\('\.\/conductor'\)/);
    expect(overlay).toMatch(/import\('\.\/tour'\)/);
    expect(readFileSync(join(SRC, 'dev', 'tour.ts'), 'utf8')).not.toMatch(/from '\.\/conductor'/);
    expect(readFileSync(join(SRC, 'dev', 'conductor.ts'), 'utf8')).not.toMatch(/from '\.\/tour'/);
  });
  it('the production-reachable pieces use no driver code', () => {
    for (const f of ['lib/pulse.ts', 'lib/lastCall.ts', 'components/LastCallPanel.tsx', 'components/Header.tsx', 'components/ZoneMap.tsx']) {
      expect(readFileSync(join(SRC, f), 'utf8'), f).not.toMatch(/dev\/conductor|dev\/tour|createConductor|createTour|DevOverlay|TimelinePlayer/);
    }
  });
  it('the offline switch lives only in connection.ts, and every use of it is behind import.meta.env.DEV', () => {
    const src = readFileSync(join(SRC, 'lib', 'connection.ts'), 'utf8');
    expect(src).toMatch(/export const isForcedOffline = \(\): boolean => import\.meta\.env\.DEV && forcedOffline;/);
    expect(src).toMatch(/export function devForceOffline\(on: boolean, now: \(\) => number = Date\.now\): void \{\n  if \(!import\.meta\.env\.DEV\) return;/);
    expect(src.match(/forcedOffline/g)?.length).toBe(3); // the declaration, the DEV-gated reader, and the one write inside devForceOffline
    const users = files(SRC).filter((f) => /devForceOffline|isForcedOffline/.test(readFileSync(f, 'utf8'))).map((f) => relative(SRC, f)).sort();
    expect(users).toEqual(['App.tsx', 'lib/connection.ts']);
  });
  it('types in no data: the scripts have no case count, gauge value, zone id, colour or countdown literal', () => {
    const code = readFileSync(join(SRC, 'dev', 'conductor.ts'), 'utf8').replace(/\/\/.*$/gm, '');
    const script = code.slice(code.indexOf('export const SCRIPT'), code.indexOf('export type BeatName'));
    expect(script).not.toMatch(/#[0-9a-fA-F]{6}|zone_id: '|cases: \d|possibly: \d|cutOff: \d/);
    expect(script).not.toMatch(/['"`](elevated|extreme)['"`]/);
    expect(script.match(/\bevent\(([\w.]+),/g)?.length).toBe(SCRIPT.length + SCRIPT_LISTENING.length + SCRIPT_OFFLINE.length); // every entry is an offset, a name and a check, nothing else
    expect(script).not.toMatch(/Math\.random|fetch\(/);
  });
});
