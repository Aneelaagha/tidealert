// DEV ONLY (?dev=1 in a Vite dev build). The demo conductor: it moves a run's playhead by itself and, at fixed timeline offsets, fires named events so
// panels animate in sync. The PACING (offsets, speed, the freeze) is hardcoded here. The DATA is not: every value an event reports
// comes from what the page has fetched for the run time the playhead is at, and an event whose condition is not met by that data is
// SKIPPED and logged, never faked. Nothing is written anywhere: the runs are precomputed and the conductor only reveals them through
// the same slider path a person uses.
//
// Three beats:
//   isolation  the Harvey replay: cut-off count, Last call countdowns, Aerial priority.
//   listening  the synthetic listening scenario: probe cascade, HELP replies, depth reports, corroboration, a Case.
//   offline    the dev-forced connection loss: banner, cached labels, recovery. Its steps run on whichever run is on screen.
// Time comes from the shared PlayerClock (play, pause, seek, speed), so the same player drives the guided tour.
//
// It is reachable only in a Vite dev build with ?dev=1 (see DevPanel and App): in a production build the import is dead code and this
// file is not in the bundle (tests/build check it). It never loops: it freezes at the beat's freeze offset and stops.
import type { Attention } from '../lib/attention';
import { minutesLeft } from '../lib/lastCall';
import type { Case, LastCall, LastCallZone, ZonesResponse } from '../lib/api';
import type { Line, PlayerClock, PlayerStep, Tool } from './TimelinePlayer';

export const TICK_MIN = 15; // the runs' own step: data exists at these times only
export const GRACE_S = 2.5; // how long after its offset an event waits for the data of its run time to arrive
const PURE = new Set(['playhead-start', 'freeze-end', 'silence', 'offline-on', 'offline-hold', 'recover']); // pacing or switch only: no run data to wait for
export const HOLD_MAX_S = 4; // the longest the playhead waits at one step for that step's data before moving on (and the event then skips, saying so)
export const ISOLATION_WAIT_S = 6; // the Harvey beat steps every 1.25 s and its zones are slow to load, so its events wait longer
export const MIN = 60_000;

/** How a beat moves the playhead. `minPerSec` is run minutes per real second. */
export interface Pacing { minPerSec: number; startAtS: number; freezeAtS: number; endAtS: number }
/** The Harvey replay: 12 run-minutes per real second, 37 s of motion, frozen at 40 s. */
export const PACING_ISOLATION: Pacing = { minPerSec: 12, startAtS: 3, freezeAtS: 40, endAtS: 42 };
/** The listening scenario: its recorded activity is the first 45 minutes of a 3 hour window (the stored sweeps show nothing new after
 *  the 14:45 step), so 1.5 run-minutes per real second puts its three steps (14:15, 14:30, 14:45) at about 13, 23 and 33 s. */
export const PACING_LISTENING: Pacing = { minPerSec: 1.5, startAtS: 3, freezeAtS: 45, endAtS: 47 };

/** The offline beat has no playhead: 15 s of switch and checks, then a refresh check. */
export const PACING_OFFLINE: Pacing = { minPerSec: 0, startAtS: 0, freezeAtS: 17, endAtS: 24 };

/** Where the Harvey beat opens, as briefed. A dev URL may override it with ?harveyStart=<ISO time>. */
export const HARVEY_START = '2017-08-28T05:15:00Z';

/** The run time at `t` real seconds after Start, given the beat's start. Linear, then held at the freeze. */
export function clockAt(t: number, startMs: number, pacing: Pacing = PACING_ISOLATION): number {
  const moving = Math.min(Math.max(t - pacing.startAtS, 0), pacing.freezeAtS - pacing.startAtS);
  return startMs + moving * pacing.minPerSec * MIN;
}

/** The index of the run step the clock is in (data exists per step), or -1 before the first. */
export function tickIndexAt(clockMs: number, tickTimes: number[]): number {
  let lo = -1;
  for (let i = 0; i < tickTimes.length && tickTimes[i] <= clockMs; i++) lo = i;
  return lo;
}

/** The last run step at or before `wantMs`, or null when the run has none that early. */
export function stepAtOrBefore(wantMs: number, tickTimes: number[]): number | null {
  const i = tickIndexAt(wantMs, tickTimes);
  return i < 0 ? null : tickTimes[i];
}

// ---------------------------------------------------------------- what the listening scenario's Cases say, as the engines wrote it
export interface ListeningFacts {
  lateHouseholds: number; // household Cases with silence evidence: did not answer a check-in within their own usual time
  cascadeSteps: string[]; // each recorded cascade step ("escalated_voice", "escalated_neighbor", ...)
  helpHouseholds: number; // household Cases whose listening evidence says the household replied HELP
  depths: { depth: string; zoneId: string; caseId: string }[]; // each depth report (ankle / knee / waist)
  zoneCases: { caseId: string; zoneId: string; openedAt: string; sentence: string; evidence: string }[]; // Cases for a whole block
  raisedZones: { zoneId: string; name: string; level: string }[]; // zones whose risk level is no longer unknown
}

const DEPTH = /reported (\w+)-deep water/;
const STEP = /cascade (\w+):/;

/** Read the listening scenario's facts from the Cases and zones the page holds. Pure: only what the engines stored is counted. */
export function listeningFacts(cases: Case[], zones: ZonesResponse | null): ListeningFacts {
  const f: ListeningFacts = { lateHouseholds: 0, cascadeSteps: [], helpHouseholds: 0, depths: [], zoneCases: [], raisedZones: [] };
  for (const c of cases) {
    if (c.household_id === null) {
      if (c.engines.includes('listening')) {
        const ev = c.contributions.find((k) => k.engine === 'listening' && k.direction === 'supports');
        f.zoneCases.push({ caseId: c.id, zoneId: c.zone_id, openedAt: c.opened_at, sentence: c.inference_sentence, evidence: ev?.rule_fragment ?? '' });
      }
      continue;
    }
    if (c.contributions.some((k) => k.engine === 'silence' && k.direction === 'supports')) f.lateHouseholds++;
    if (c.contributions.some((k) => k.engine === 'listening' && /replied HELP/.test(k.rule_fragment))) f.helpHouseholds++;
    for (const k of c.contributions) {
      const step = k.engine === 'listening' && k.direction === 'procedural' ? STEP.exec(k.rule_fragment) : null;
      if (step) f.cascadeSteps.push(step[1]);
      const d = k.engine === 'listening' ? DEPTH.exec(k.rule_fragment) : null;
      if (d) f.depths.push({ depth: d[1], zoneId: c.zone_id, caseId: c.id });
    }
  }
  for (const z of zones?.features ?? []) if (z.properties.risk_level !== 'unknown') f.raisedZones.push({ zoneId: z.properties.zone_id, name: z.properties.name, level: z.properties.risk_level });
  return f;
}

/** What the page has loaded for the run step the playhead is at. `ready` is true only when everything is for that step. */
export interface Snapshot {
  mode: string | null; // the run's mode badge: replay / scenario / ...
  tickAt: number | null; // the step the playhead is at (ms)
  clockMs: number;
  ready: boolean;
  cases: number | null;
  firstCaseAt: number | null;
  possibly: number | null; // zones "may be cut off" in the supply-access answer
  cutOff: number | null;
  headlineCutOff: number | null; // the number in the top banner: flagged zones that are cut off
  headlineFlagged: number | null;
  freshness: string[] | null; // each source's status
  lastCall: LastCall | null;
  aerial: { rank: number; name: string; minutes: number }[] | null; // the Aerial priority ranking for this step
  ranked: Attention[];
  listening: ListeningFacts | null;
  offline: OfflineView | null; // the connection and what the page shows of it (read from the page, not from the beat)
  pinned: string[];
}

export interface OfflineView { state: string; offlineSince: number | null; lastLoadedAt: number | null; recoveredAt: number | null; banner: boolean; cached: number; unknown: number }

/** What earlier events of the same run saw, so a later event compares with the real value and not with a number typed here. */
export interface Memo { startMs?: number; headline0?: number | null; cases0?: number | null }

export interface Check { ok: boolean; value: string; act?: (host: Host) => void }
export interface ScriptEvent { at: number; name: string; what: string; check: (s: Snapshot, m: Memo) => Check; waitS?: number; pure?: boolean }

/** What the driver may do to the page: move the playhead, and ask panels to show something that is already in the data. */
export interface Host {
  snapshot(): Snapshot;
  goToTick(i: number): void;
  setClock(ms: number, wholeSecond: number): void; // the continuous clock (header) and the real second it is read at (countdowns tick once a second)
  pinZone(zoneId: string): void; // show this zone's countdown in the Last call panel
  pulseZone(zoneId: string): void;
  reveal(panel: string): void; // show a panel the beat kept back until its cue (its data is already loaded)
  caption(text: string | null): void;
  frozen(): void;
  offline(on: boolean): void; // force the connection offline (dev switch) or bring it back
}

const hhmm = (ms: number) => new Date(ms).toISOString().slice(11, 16);
const day = (ms: number) => new Date(ms).toISOString().slice(5, 16).replace('T', ' ');
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const tally = (xs: string[]) => [...new Set(xs)].sort().map((x) => `${x} ×${xs.filter((y) => y === x).length}`).join(', ');

function countingZones(s: Snapshot): LastCallZone[] {
  return (s.lastCall?.zones ?? []).filter((z) => z.status === 'counting' && z.cutoff_at);
}

/** The counting zone with the earliest recorded cut-off that is at least `minAheadMin` minutes away, not already pinned. */
export function pickCountdown(s: Snapshot, minAheadMin: number): LastCallZone | null {
  const ahead = countingZones(s)
    .filter((z) => Date.parse(z.cutoff_at!) - s.clockMs >= minAheadMin * MIN && !s.pinned.includes(z.zone_id))
    .sort((a, b) => Date.parse(a.cutoff_at!) - Date.parse(b.cutoff_at!) || a.zone_id.localeCompare(b.zone_id));
  return ahead[0] ?? null;
}

const event = (offset: number, name: string, what: string, check: ScriptEvent['check'], waitS?: number): ScriptEvent => ({ at: offset, name, what, check, waitS, pure: PURE.has(name) });
const stepOf = (s: Snapshot) => hhmm(s.tickAt ?? s.clockMs);
const countdown = (s: Snapshot, z: LastCallZone) => `${z.zone_name}: cut off ${hhmm(Date.parse(z.cutoff_at!))} UTC, ${minutesLeft(Date.parse(z.cutoff_at!), s.clockMs)} min away at ${hhmm(s.clockMs)} UTC`;

// ---------------------------------------------------------------- beat 1: isolation, on the Harvey replay
export const SCRIPT: ScriptEvent[] = [
  event(0, 'open-harvey', 'The Harvey replay opens, REPLAY badge, map fitted', (s, m) => { m.startMs = s.clockMs; m.headline0 = s.headlineCutOff; m.cases0 = s.cases;
      return { ok: s.mode === 'replay', value: `${s.mode?.toUpperCase()} badge; replay ${day(s.clockMs)} UTC; top banner: ${s.headlineCutOff} of ${s.headlineFlagged} flagged zones cut off; ${s.cutOff?.toLocaleString()} zones cut off in the engine's supply-access answer` }; }),
  event(3, 'playhead-start', 'The playhead starts moving at 12 replay-minutes per real second', (s) => ({ ok: true, value: `from ${day(s.clockMs)} UTC` })),
  event(8, 'cutoff-climbs', 'The cut-off count in the top banner climbs (each value is the real count at its step)', (s, m) => {
      const grew = s.headlineCutOff !== null && m.headline0 != null && s.headlineCutOff > m.headline0;
      return { ok: grew, value: `top banner cut off: ${m.headline0} → ${s.headlineCutOff} of ${s.headlineFlagged} flagged zones at the ${stepOf(s)} UTC step` }; }, ISOLATION_WAIT_S),
  event(15, 'last-call-1', 'Last call shows a zone genuinely counting down (lead time 0: last call is its cut-off time)', (s) => { const z = pickCountdown(s, 20);
      return z ? { ok: true, value: countdown(s, z), act: (h) => h.pinZone(z.zone_id) } : { ok: false, value: `no zone is counting down more than 20 min ahead at the ${stepOf(s)} UTC step (${s.lastCall?.counts.counting ?? 0} counting)` }; }, ISOLATION_WAIT_S),
  event(25, 'aerial-populates', 'Aerial priority populates with its top 5 (the real ranking)', (s) => s.aerial && s.aerial.length > 0
      ? { ok: true, value: `top ${s.aerial.length} at the ${stepOf(s)} UTC step: ${s.aerial.map((r) => `${r.rank}. ${r.name} (${r.minutes} min)`).join('; ')}`, act: (h) => h.reveal('aerial') }
      : { ok: false, value: 'the ranking holds no zone at this step' }, ISOLATION_WAIT_S),
  event(35, 'last-call-2', 'A second real countdown appears beneath', (s) => { const z = pickCountdown(s, 20);
      return z ? { ok: true, value: countdown(s, z), act: (h) => h.pinZone(z.zone_id) } : { ok: false, value: `no second zone is counting down more than 20 min ahead at the ${stepOf(s)} UTC step (${s.lastCall?.counts.counting ?? 0} counting)` }; }, ISOLATION_WAIT_S),
  event(PACING_ISOLATION.freezeAtS, 'freeze-end', 'The playhead and the header clock stop on a mid-crisis frame', (s) => ({ ok: true, value: `frozen at replay ${day(s.clockMs)} UTC`, act: (h) => h.frozen() })),
  event(PACING_ISOLATION.endAtS, 'silence', 'No UI motion from here on', () => ({ ok: true, value: 'stopped' })),
];

// ---------------------------------------------------------------- beat 2: silence + listening, on the synthetic scenario
// The scenario's sweeps are 15 minutes apart and its recorded activity falls on three of them, so several brief events share a step.
// Each event fires once its offset has passed AND the playhead's step holds its evidence (waitS is how long it waits for that step);
// the offset is the earliest it may fire, never a time it is forced at.
export const SCRIPT_LISTENING: ScriptEvent[] = [
  event(0, 'open-scenario', 'The listening scenario opens, SCENARIO badge, map fitted to its area', (s, m) => { m.startMs = s.clockMs; m.cases0 = s.cases;
      return { ok: s.mode === 'scenario', value: `${s.mode?.toUpperCase()} badge; scenario ${day(s.clockMs)} UTC; ${s.cases} Cases open` }; }),
  event(3, 'playhead-start', 'The playhead starts moving at 1.5 scenario-minutes per real second', (s) => ({ ok: true, value: `from ${day(s.clockMs)} UTC` })),
  event(8, 'cascade-fires', 'The probe cascade is visible: households late for their own baseline, escalated by voice call', (s) => {
      const l = s.listening; const n = l?.lateHouseholds ?? 0;
      return { ok: n > 0 && (l?.cascadeSteps.length ?? 0) > 0, value: `${plural(n, 'household')} did not answer the check-in within their own usual time; cascade steps recorded: ${tally(l?.cascadeSteps ?? [])} (at the ${stepOf(s)} UTC step)` }; }, 8),
  event(15, 'first-reply-help', 'The first replies arrive: HELP', (s) => { const n = s.listening?.helpHouseholds ?? 0;
      return { ok: n > 0, value: `${plural(n, 'household')} replied HELP by SMS and got the water-depth question (at the ${stepOf(s)} UTC step)` }; }, 8),
  event(20, 'depth-knee', 'A depth follow-up arrives: knee', (s) => { const d = s.listening?.depths ?? [];
      return { ok: d.some((x) => x.depth === 'knee'), value: `depth reports so far: ${tally(d.map((x) => x.depth))} (at the ${stepOf(s)} UTC step)` }; }, 10),
  event(25, 'second-reply', 'A second household in the same block reports a depth', (s) => { const d = s.listening?.depths ?? [];
      const byZone = d.reduce<Record<string, string[]>>((a, x) => ({ ...a, [x.zoneId]: [...(a[x.zoneId] ?? []), x.depth] }), {});
      const zone = Object.entries(byZone).find(([, v]) => v.length >= 2);
      return { ok: !!zone, value: zone ? `${zone[1].length} households in one block have reported depth: ${tally(zone[1])} (at the ${stepOf(s)} UTC step)` : `no block has two depth reports yet at the ${stepOf(s)} UTC step` }; }, 12),
  event(30, 'corroboration-2', 'Corroboration reaches 2 and the zone risk level rises', (s) => { const l = s.listening; const zc = l?.zoneCases[0]; const r = l?.raisedZones[0];
      return { ok: !!zc && !!r, value: zc && r ? `${r.name}: risk level now ${r.level}. Engine's words: ${zc.evidence}` : `no block is corroborated yet at the ${stepOf(s)} UTC step` }; }, 12),
  event(35, 'case-opens', "The block's corroborated Case opens (the Case card slides in)", (s) => { const zc = s.listening?.zoneCases[0];
      return zc ? { ok: true, value: `${zc.sentence} (opened ${hhmm(Date.parse(zc.openedAt))} UTC)`, act: (h) => h.pulseZone(zc.zoneId) } : { ok: false, value: `no block Case is open at the ${stepOf(s)} UTC step` }; }, 12),
  event(PACING_LISTENING.freezeAtS, 'freeze-end', 'The playhead and the header clock stop', (s) => ({ ok: true, value: `frozen at scenario ${day(s.clockMs)} UTC`, act: (h) => h.frozen() })),
  event(PACING_LISTENING.endAtS, 'silence', 'No UI motion from here on', () => ({ ok: true, value: 'stopped' })),
];

// ---------------------------------------------------------------- beat 3: offline, on whichever run is on screen
export const SCRIPT_OFFLINE: ScriptEvent[] = [
  event(0, 'offline-on', 'The connection is forced offline (dev switch); the 5-second probe is suppressed', (s) => ({ ok: true, value: `forced offline on the ${s.mode?.toUpperCase() ?? 'loaded'} run at the ${stepOf(s)} UTC step`, act: (h) => h.offline(true) })),
  event(2, 'offline-banner', 'The banner appears and the source chips read cached, from what the page shows', (s) => { const o = s.offline;
      return { ok: !!o && o.state === 'offline' && o.banner && (o.cached > 0 || o.unknown > 0), value: o ? `connection ${o.state}; banner ${o.banner ? 'shown' : 'not shown'}; ${o.cached} cached label(s), ${o.unknown} unknown` : 'no connection reading' }; }, 4),
  event(8, 'offline-hold', 'Hold the frame', (s) => ({ ok: true, value: `still ${s.offline?.state ?? 'unknown'}` })),
  event(15, 'recover', 'The switch is turned off and the first real answer returns the page online', () => ({ ok: true, value: 'switch off', act: (h) => h.offline(false) })),
  event(17, 'confirm-refresh', 'The page is online again and has read its view from the server', (s) => { const o = s.offline;
      return { ok: !!o && o.state === 'online' && o.banner === false && o.recoveredAt !== null && o.lastLoadedAt !== null && o.lastLoadedAt >= o.recoveredAt, value: o ? `connection ${o.state}; banner ${o.banner ? 'shown' : 'gone'}; view re-read from the server after recovery` : 'no connection reading' }; }, 6),
  event(PACING_OFFLINE.endAtS, 'silence', 'Nothing moves from here on', () => ({ ok: true, value: 'stopped' })),
];

/** The read-along: the step's narration, else the beat's caption, else the step's name. */
export function readAlong(step: { what?: string; caption?: string; name: string }): string {
  return step.what?.trim() || step.caption?.trim() || step.name;
}

export type BeatName = 'isolation' | 'listening' | 'offline';
export const BEATS: Record<BeatName, { script: ScriptEvent[]; pacing: Pacing; caption: (p: Pacing) => string; hidden: string[]; playhead: boolean }> = {
  isolation: { script: SCRIPT, pacing: PACING_ISOLATION, caption: (p) => `Replay playing at ${p.minPerSec} min/s`, hidden: ['aerial'], playhead: true },
  listening: { script: SCRIPT_LISTENING, pacing: PACING_LISTENING, caption: (p) => `Scenario playing at ${p.minPerSec} min/s`, hidden: [], playhead: true },
  offline: { script: SCRIPT_OFFLINE, pacing: PACING_OFFLINE, caption: () => '', hidden: [], playhead: false },
};

/** What the page gives the conductor on top of the Host: open a beat's run frozen at its start, and read the connection. */
export interface DevHostBase extends Omit<Host, 'snapshot'> {
  snapshot(): RawSnapshot;
  harveyStart(): string | null; // ?harveyStart= from the page's own URL, read at load
  open(beat: 'isolation' | 'listening', wantAt: string | null, hidden: string[]): Promise<{ startMs: number; tickTimes: number[] } | null>;
  active(on: boolean): void;
  connection(): { state: string; offlineSince: number | null };
}

/** What the page holds for the step; the conductor derives the scenario's facts from it (so the page imports none of this file). */
export interface RawSnapshot extends Omit<Snapshot, 'listening'> { stepCases: Case[] | null; stepZones: ZonesResponse | null }
export const withListening = (raw: RawSnapshot): Snapshot => ({ ...raw, listening: raw.stepCases && raw.stepZones ? listeningFacts(raw.stepCases, raw.stepZones) : null });

export interface LogEntry { name: string; what: string; scriptedAt: number; firedAt: number | null; replay: string; ok: boolean; value: string }

export interface Conductor extends Tool { log(): LogEntry[]; running(): boolean }

/** The conductor's loop on the shared clock. Fixed pacing; every event's condition is checked against the page's data. It never loops. */
export function createConductor(host: Host, tickTimes: number[], startMs: number, beat: BeatName, clock: PlayerClock, script?: ScriptEvent[]): Conductor {
  const { pacing, playhead } = BEATS[beat];
  const events = script ?? BEATS[beat].script;
  const entries = new Map<string, LogEntry>();
  const done = new Set<string>();
  const memo: Memo = {};
  const judged = new Map<string, string>(); // each event's last verdict on real data, so a skip says why, not just that the data was late
  const keyOf = (ev: ScriptEvent) => `${ev.at}:${ev.name}`;
  let lastTick = -2;
  let lastPoll = clock.now();
  let heldFor = 0;
  let started = false;
  let over = false;

  const label = (e: ScriptEvent) => ({ name: e.name, what: e.what, scriptedAt: e.at });
  const stop = () => { started = false; over = true; };

  function tick() {
    const nw = clock.now();
    const dt = nw - lastPoll; lastPoll = nw;
    if (!started || over || !clock.isPlaying) return;
    // The run's data loads with variable lag, but the beat's time must not: an event at offset X has to see the step the clock is in at X,
    // every run. So when an event is due and its step has not fully loaded, the beat's own time stands still (bounded by HOLD_MAX_S per step)
    // until it has. Between events nothing waits, so only a slow load at a cue makes the scene longer, and never different.
    let t = clock.time();
    if (playhead && t >= pacing.startAtS && t < pacing.freezeAtS && lastTick >= 0) {
      const due = events.some((ev) => !done.has(keyOf(ev)) && !ev.pure && t >= ev.at);
      const here = host.snapshot();
      const loaded = here.ready && here.tickAt === tickTimes[lastTick];
      if (due && !loaded && heldFor < HOLD_MAX_S * 1000) { clock.hold(dt); heldFor += dt; t = clock.time(); } else if (loaded) heldFor = 0;
    }
    const clockMs = playhead ? clockAt(t, startMs, pacing) : startMs;
    const cue = playhead ? clockAt(Math.floor(t), startMs, pacing) : startMs; // what an event reads: the clock at the whole second, so values do not move with a few ms of timing
    if (playhead) {
      host.setClock(clockMs, Math.floor(t));
      const i = tickIndexAt(clockMs, tickTimes);
      if (i !== lastTick && i >= 0) { lastTick = i; heldFor = 0; host.goToTick(i); }
      host.caption(t < pacing.startAtS ? null : t < pacing.freezeAtS ? BEATS[beat].caption(pacing) : 'Paused');
    }
    for (const ev of events) {
      const key = keyOf(ev);
      if (done.has(key) || t < ev.at) continue;
      const snap = { ...host.snapshot(), clockMs: cue };
      const judging = snap.ready || !!ev.pure || !playhead;
      const res = judging ? ev.check(snap, memo) : { ok: false, value: judged.get(key) ?? 'the data for this run step has not arrived' };
      if (judging) judged.set(key, res.value);
      if (res.ok) {
        res.act?.(host);
        entries.set(key, { ...label(ev), firedAt: Math.round(t * 100) / 100, replay: day(cue), ok: true, value: res.value });
        done.add(key);
      } else if (t > ev.at + (ev.waitS ?? GRACE_S) || (playhead && t >= pacing.freezeAtS)) {
        // Not satisfied by the real data in time: skipped and logged, never faked.
        entries.set(key, { ...label(ev), firedAt: null, replay: day(cue), ok: false, value: `SKIPPED: ${res.value}` });
        done.add(key);
      }
    }
    if (t >= pacing.endAtS) stop();
  }

  return {
    title: beat === 'isolation' ? 'Isolation beat (Harvey replay)' : beat === 'listening' ? 'Silence + Listening beat (scenario)' : 'Offline beat',
    steps: events.filter((e) => e.name !== 'silence').map((e) => ({ at: e.at, label: e.name } as PlayerStep)),
    duration: pacing.endAtS,
    start() { started = true; over = false; lastPoll = clock.now(); heldFor = 0; lastTick = -2; tick(); },
    tick,
    // Skip: events before the chosen one are not run (logged as such, never presented as having fired); the playhead jumps to its time.
    seek(i) {
      const target = events.filter((e) => e.name !== 'silence')[i];
      if (!target) return;
      for (const ev of events) if (ev.at < target.at && !done.has(keyOf(ev))) { entries.set(keyOf(ev), { ...label(ev), firedAt: null, replay: '', ok: false, value: `NOT RUN: skipped past to ${target.name}` }); done.add(keyOf(ev)); }
      clock.seek(target.at); heldFor = 0; lastPoll = clock.now();
      if (!started) { started = true; over = false; lastTick = -2; }
    },
    stop,
    line(t): Line | null {
      let cur: ScriptEvent | null = null;
      for (const ev of events) if (ev.at <= t && ev.name !== 'silence') cur = ev;
      if (!cur) return null;
      const e = entries.get(keyOf(cur));
      return { text: readAlong({ what: cur.what, caption: BEATS[beat].caption(pacing), name: cur.name }), sub: e ? e.value : undefined, skipped: !!e && !e.ok };
    },
    finished: () => over,
    log: () => events.map((ev) => entries.get(keyOf(ev))).filter((e): e is LogEntry => !!e),
    running: () => started && !over,
  };
}
