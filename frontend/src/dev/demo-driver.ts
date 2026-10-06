// DEV ONLY. The demo driver for the Harvey opening scene: it moves the replay playhead by itself and, at fixed real-time
// offsets, fires named events so panels animate in sync. The PACING (offsets, speed, the freeze) is hardcoded here. The DATA
// is not: every value an event reports comes from what the page has fetched for the replay time the playhead is at, and an
// event whose condition is not met by that data is SKIPPED and logged, never faked.
//
// It is reachable only in a Vite dev build with ?dev=1 (see DevPanel and App): in a production build the import is dead
// code and this file is not in the bundle (tests/build check it). It never loops: it freezes at FREEZE_AT_S and stops.
import type { Attention } from '../lib/attention';
import { minutesLeft } from '../lib/lastCall';
import type { LastCall, LastCallZone } from '../lib/api';

export const REPLAY_MIN_PER_SEC = 12; // replay minutes per real second
export const START_AT_S = 2; // the playhead starts moving
export const FREEZE_AT_S = 22; // the playhead stops: the still frame
export const END_AT_S = 24; // nothing moves after this; the driver stops itself
export const TICK_MIN = 15; // the replay's own step: data exists at these times only
export const LEAD_IN_MIN = 45; // pacing: the first Case lands about 4 s after the playhead starts
export const GRACE_S = 2.5; // how long after its offset an event waits for the data of its replay time to arrive
export const MIN = 60_000;

/** The replay time at `t` real seconds after Start, given the start of the scene. Linear, then held at the freeze. */
export function clockAt(t: number, startMs: number): number {
  const moving = Math.min(Math.max(t - START_AT_S, 0), FREEZE_AT_S - START_AT_S);
  return startMs + moving * REPLAY_MIN_PER_SEC * MIN;
}

/** The index of the replay step the clock is in (data exists per step), or -1 before the first. */
export function tickIndexAt(clockMs: number, tickTimes: number[]): number {
  let lo = -1;
  for (let i = 0; i < tickTimes.length && tickTimes[i] <= clockMs; i++) lo = i;
  return lo;
}

/** The scene's start: the last replay step at or before (first Case time - LEAD_IN_MIN). Derived from the data, not typed in. */
export function sceneStart(firstCaseMs: number, tickTimes: number[]): number | null {
  const i = tickIndexAt(firstCaseMs - LEAD_IN_MIN * MIN, tickTimes);
  return i < 0 ? null : tickTimes[i];
}


/** What the page has loaded for the replay step the playhead is at. `ready` is true only when everything is for that step. */
export interface Snapshot {
  tickAt: number | null; // the step the playhead is at (ms)
  clockMs: number;
  ready: boolean;
  cases: number | null;
  firstCaseAt: number | null;
  possibly: number | null; // zones "may be cut off" in the supply-access answer
  cutOff: number | null;
  freshness: string[] | null; // each source's status
  lastCall: LastCall | null;
  ranked: Attention[];
  alarms: Record<string, number> | null; // gauge -> NWS minor-flood alarm time (ms), from the stored thresholds
  pinned: string[];
}

/** What earlier events of the same run saw, so a later event compares with the real value and not with a number typed here. */
export interface Memo { startMs?: number; cases0?: number | null; possibly0?: number | null; firstCases?: number | null }

export interface Check { ok: boolean; value: string; act?: (host: Host) => void }
export interface ScriptEvent { at: number; name: string; what: string; check: (s: Snapshot, m: Memo) => Check }

/** What the driver may do to the page: move the playhead, and ask panels to show something that is already in the data. */
export interface Host {
  snapshot(): Snapshot;
  goToTick(i: number): void;
  setClock(ms: number, wholeSecond: number): void; // the continuous replay clock (header) and the real second it is read at (countdowns tick once a second)
  pinZone(zoneId: string): void; // show this zone's countdown in the Last call panel
  pulseZone(zoneId: string): void;
  caption(text: string | null): void;
  frozen(): void;
}

const hhmm = (ms: number) => new Date(ms).toISOString().slice(11, 16);
const day = (ms: number) => new Date(ms).toISOString().slice(5, 16).replace('T', ' ');

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

/** A gauge crossing is shown only if the stored alarm time falls inside the scene (after it began) and the replay clock has passed it,
 *  and the zones "may be cut off" count has risen above what it was when the scene began. All three are real values. */
const gaugeCrossing = (gauge: string): ((s: Snapshot, m: Memo) => Check) => (s, m) => {
  const alarm = s.alarms?.[gauge];
  if (alarm === undefined) return { ok: false, value: `no stored alarm time for USGS ${gauge}` };
  if (m.startMs !== undefined && alarm < m.startMs) return { ok: false, value: `USGS ${gauge} crossed its alarm at ${day(alarm)} UTC, before this scene begins` };
  if (s.clockMs < alarm) return { ok: false, value: `the replay is at ${hhmm(s.clockMs)} UTC, before USGS ${gauge}'s alarm at ${hhmm(alarm)} UTC` };
  const grew = s.possibly !== null && m.possibly0 != null && s.possibly > m.possibly0;
  return { ok: grew, value: `USGS ${gauge} reached its NWS minor-flood alarm at ${hhmm(alarm)} UTC; zones that may be cut off: ${m.possibly0?.toLocaleString()} → ${s.possibly?.toLocaleString()} at the ${hhmm(s.tickAt ?? s.clockMs)} UTC step` };
};

const event = (at: number, name: string, what: string, check: ScriptEvent['check']): ScriptEvent => ({ at, name, what, check });

export const SCRIPT: ScriptEvent[] = [
  event(0, 'freeze-start', 'Frozen at the scene start: no Case open, every source fresh (banner green)', (s, m) => { m.startMs = s.clockMs; m.cases0 = s.cases; m.possibly0 = s.possibly;
      return { ok: s.cases === 0 && !!s.freshness && s.freshness.length > 0 && s.freshness.every((f) => f === 'fresh'),
               value: `replay ${day(s.clockMs)} UTC: ${s.cases} Cases open; sources ${s.freshness?.join(', ')}; ${s.possibly?.toLocaleString()} zones already may be cut off` }; }),
  event(START_AT_S, 'playhead-start', 'The playhead starts moving at 12 replay-minutes per real second', (s) => ({ ok: true, value: `from ${day(s.clockMs)} UTC` })),
  event(6, 'first-case', 'The first Case opens (the Case card slides in)', (s, m) => { m.firstCases = s.cases; return { ok: (s.cases ?? 0) > 0 && s.firstCaseAt !== null, value: `${s.cases} Cases open at the ${hhmm(s.tickAt ?? s.clockMs)} UTC step (first opened ${s.firstCaseAt ? hhmm(s.firstCaseAt) : '?'} UTC)` }; }),
  event(8, 'gauge-crossing-08074500', 'USGS 08074500 reaches its NWS minor-flood alarm and zones flip to "may be cut off"', gaugeCrossing('08074500')),
  event(11, 'cases-growth', 'The Cases counter grows with the data (each value is the real count at its step)', (s, m) => ({ ok: m.firstCases != null && (s.cases ?? 0) > m.firstCases, value: `Cases ${m.firstCases} → ${s.cases} at the ${hhmm(s.tickAt ?? s.clockMs)} UTC step` })),
  event(11, 'last-call-focus-1', 'Last call focuses a zone genuinely counting down (lead time 0: last call is its cut-off time)', (s) => { const z = pickCountdown(s, 20); return z ? { ok: true, value: `${z.zone_name}: cut off ${hhmm(Date.parse(z.cutoff_at!))} UTC, ${minutesLeft(Date.parse(z.cutoff_at!), s.clockMs)} min away at ${hhmm(s.clockMs)} UTC`, act: (h) => h.pinZone(z.zone_id) } : { ok: false, value: 'no zone counting down more than 20 min ahead' }; }),
  event(12, 'gauge-crossing-08075770', 'USGS 08075770 reaches its alarm (replaces 08076000, whose alarm was the day before)', gaugeCrossing('08075770')),
  event(15, 'last-call-focus-2', 'A second real countdown appears beneath', (s) => { const z = pickCountdown(s, 60); return z ? { ok: true, value: `${z.zone_name}: cut off ${hhmm(Date.parse(z.cutoff_at!))} UTC, ${minutesLeft(Date.parse(z.cutoff_at!), s.clockMs)} min away at ${hhmm(s.clockMs)} UTC`, act: (h) => h.pinZone(z.zone_id) } : { ok: false, value: 'no second zone counting down more than 60 min ahead' }; }),
  event(16, 'countdown-amber', 'The second countdown crosses 1 h 00 m and turns amber', (s) => { const z = (s.lastCall?.zones ?? []).find((x) => x.zone_id === s.pinned[1]); if (!z?.cutoff_at) return { ok: false, value: 'the second countdown is not on screen' };
      const m = minutesLeft(Date.parse(z.cutoff_at), s.clockMs); return { ok: m <= 60 && m > 0, value: `${z.zone_name}: ${m} min left at ${hhmm(s.clockMs)} UTC` }; }),
  event(17, 'pulse-ring', 'One pulse ring from a zone with an open task (the top zone in Needs attention)', (s) => { const z = s.ranked.find((r) => r.group <= 3); return z ? { ok: true, value: `${z.name} (${z.priority ?? 'no'} priority task, ${z.access ?? 'access not assessed'})`, act: (h) => h.pulseZone(z.zoneId) } : { ok: false, value: 'no zone with an open task' }; }),
  event(21, 'last-call-focus-3', 'A third real countdown appears', (s) => { const z = pickCountdown(s, 60); return z ? { ok: true, value: `${z.zone_name}: cut off ${hhmm(Date.parse(z.cutoff_at!))} UTC, ${minutesLeft(Date.parse(z.cutoff_at!), s.clockMs)} min away at ${hhmm(s.clockMs)} UTC`, act: (h) => h.pinZone(z.zone_id) } : { ok: false, value: 'no third zone counting down more than 60 min ahead' }; }),
  event(FREEZE_AT_S, 'freeze-end', 'The playhead and the header clock stop on a mid-crisis frame', (s) => ({ ok: true, value: `frozen at replay ${day(s.clockMs)} UTC with ${s.cases} Cases open`, act: (h) => h.frozen() })),
  event(END_AT_S, 'silence', 'No UI motion from here on', () => ({ ok: true, value: 'stopped' })),
];

export interface LogEntry { name: string; what: string; scriptedAt: number; firedAt: number | null; replay: string; ok: boolean; value: string }

export interface Driver { start(): void; stop(): void; log(): LogEntry[]; running(): boolean }

/** The driver loop. Fixed pacing; every event's condition is checked against the page's data. It never loops. */
export function createDriver(host: Host, tickTimes: number[], startMs: number, script: ScriptEvent[] = SCRIPT, now: () => number = () => performance.now()): Driver {
  const entries = new Map<string, LogEntry>();
  const done = new Set<string>();
  const memo: Memo = {};
  let timer: ReturnType<typeof setInterval> | undefined;
  let t0 = 0;
  let lastTick = -2;
  let running = false;

  const stop = () => { if (timer !== undefined) clearInterval(timer); timer = undefined; running = false; };

  function step() {
    const t = (now() - t0) / 1000;
    const clock = clockAt(t, startMs);
    host.setClock(clock, Math.floor(t));
    const i = tickIndexAt(clock, tickTimes);
    if (i !== lastTick && i >= 0) { lastTick = i; host.goToTick(i); }
    host.caption(t < START_AT_S ? null : t < FREEZE_AT_S ? `Replay playing at ${REPLAY_MIN_PER_SEC} min/s` : 'Replay paused');
    for (const ev of script) {
      const key = `${ev.at}:${ev.name}`;
      if (done.has(key) || t < ev.at) continue;
      const snap = host.snapshot();
      const dataReady = snap.ready || ev.at === END_AT_S || ev.name === 'playhead-start' || ev.name === 'freeze-end'; // the last three are pure pacing
      const res = dataReady ? ev.check(snap, memo) : { ok: false, value: 'the data for this replay step has not arrived' };
      if (res.ok) {
        res.act?.(host);
        entries.set(key, { name: ev.name, what: ev.what, scriptedAt: ev.at, firedAt: Math.round(t * 100) / 100, replay: day(clock), ok: true, value: res.value });
        done.add(key);
      } else if (t > ev.at + GRACE_S) {
        // Not satisfied by the real data in time: skipped and logged, never faked.
        entries.set(key, { name: ev.name, what: ev.what, scriptedAt: ev.at, firedAt: null, replay: day(clock), ok: false, value: `SKIPPED: ${res.value}` });
        done.add(key);
      }
    }
    if (t >= END_AT_S) stop();
  }

  return {
    start() { if (running) return; running = true; t0 = now(); lastTick = -2; timer = setInterval(step, 100); step(); },
    stop,
    log: () => script.map((ev) => entries.get(`${ev.at}:${ev.name}`)).filter((e): e is LogEntry => !!e),
    running: () => running,
  };
}
