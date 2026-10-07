import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  type CameraMove, type MapView, type Places, MIN_HOLD_MS, ZOOM_CEILING, createCamera, frameCenter, geometryCentroid, planMove,
} from '../dev/camera';
import { BEATS, type Host, PACING_ISOLATION, SCRIPT, SCRIPT_LISTENING, SCRIPT_OFFLINE, type Snapshot, createConductor, listeningFacts, tickIndexAt } from '../dev/conductor';
import { PlayerClock } from '../dev/TimelinePlayer';
import type { Case, Contribution } from '../lib/api';

const EXTENT: [number, number, number, number] = [-96, 29, -95, 31];
const places = (known: Record<string, [number, number]> = {}): Places => ({ extent: () => EXTENT, zoneCenter: (id) => known[id] ?? null });

describe('where a frame points comes from the data', () => {
  it('metro is the extent\'s centre, metro-north the centre of its northern half', () => {
    expect(frameCenter('metro', [], places())).toEqual([-95.5, 30]);
    expect(frameCenter('metro-north', [], places())).toEqual([-95.5, 30.5]);
  });
  it('a zone is its own centroid, and several zones are the midpoint of them all', () => {
    const p = places({ a: [-95.4, 29.8], b: [-95.2, 30.2] });
    expect(frameCenter('zone', ['a'], p)).toEqual([-95.4, 29.8]);
    expect(frameCenter('zones', ['a', 'b'], p)).toEqual([expect.closeTo(-95.3, 9), expect.closeTo(30, 9)]);
  });
  it('is null, never a guess, when the data does not say', () => {
    expect(frameCenter('zone', [], places())).toBeNull();
    expect(frameCenter('zone', ['nope'], places())).toBeNull();
    expect(frameCenter('zones', ['a', 'nope'], places({ a: [1, 1] }))).toBeNull();
    expect(frameCenter('metro', [], { extent: () => null, zoneCenter: () => null })).toBeNull();
  });
});

describe('a zone\'s centroid', () => {
  it('is the centre of a square, and of the larger part of a multipolygon', () => {
    const sq = { type: 'Polygon', coordinates: [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]] };
    expect(geometryCentroid(sq)).toEqual([1, 1]);
    const multi = { type: 'MultiPolygon', coordinates: [[[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]], [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]]] };
    expect(geometryCentroid(multi)).toEqual([2, 2]);
  });
  it('is null for a shape it cannot read', () => {
    expect(geometryCentroid(null)).toBeNull();
    expect(geometryCentroid({ type: 'Point', coordinates: [1, 1] })).toBeNull();
  });
});

describe('planning a move', () => {
  it('fills the defaults: top-down, north up, 1200 ms, ease-out', () => {
    expect(planMove({ frame: 'metro', zoom: 10 }, [0, 0], 10)).toMatchObject({ pitch: 0, bearing: 0, duration: 1200, easing: 'ease-out', zoom: 10 });
  });
  it('never goes past zoom 16', () => { expect(planMove({ frame: 'zone', zoom: 19 }, [0, 0], 10).zoom).toBe(ZOOM_CEILING); expect(ZOOM_CEILING).toBe(16); });
  it('flies for more than one zoom level and eases for one or less, unless the step names its verb', () => {
    expect(planMove({ frame: 'zone', zoom: 13 }, [0, 0], 10).mode).toBe('fly');
    expect(planMove({ frame: 'zone', zoom: 11 }, [0, 0], 10).mode).toBe('ease');
    expect(planMove({ frame: 'zone', zoom: 10.5 }, [0, 0], 10).mode).toBe('ease');
    expect(planMove({ frame: 'zone', zoom: 13, mode: 'ease' }, [0, 0], 10).mode).toBe('ease');
  });
});

describe('running moves on the map', () => {
  function rig() {
    let t = 0; const timers: { at: number; fn: () => void; dead: boolean }[] = [];
    const calls: string[] = [];
    const map: MapView = { getZoom: () => 10, getCenter: () => ({ lng: 0, lat: 0 }), getPitch: () => 0, getBearing: () => 0,
      flyTo: () => calls.push(`fly@${t}`), easeTo: () => calls.push(`ease@${t}`), jumpTo: () => calls.push(`jump@${t}`), stop: () => calls.push('stop') };
    const cam = createCamera(() => map, () => {}, () => t, (fn, ms) => { const h = { at: t + ms, fn, dead: false }; timers.push(h); return h; }, (h) => { (h as { dead: boolean }).dead = true; });
    const advance = (to: number) => { while (t < to) { t += 50; for (const h of timers) if (!h.dead && h.at <= t) { h.dead = true; h.fn(); } } };
    return { cam, calls, advance, at: () => t };
  }
  const mv = (over: Partial<CameraMove> = {}): CameraMove => ({ center: [1, 1], zoom: 12, pitch: 0, bearing: 0, duration: 1000, easing: 'ease-out', mode: 'fly', ...over });
  it('holds still for 800 ms between two moves: the second starts only after the first ended and the hold', () => {
    const r = rig();
    r.cam.go('a', mv());
    r.advance(100); r.cam.go('b', mv({ mode: 'ease' }));
    r.advance(5000);
    expect(r.calls).toEqual(['fly@0', `ease@${1000 + MIN_HOLD_MS}`]);
  });
  it('lets a move waiting for the hold be replaced by a newer one, and says so', () => {
    const r = rig();
    r.cam.go('a', mv()); r.advance(100); r.cam.go('b', mv()); r.advance(200); r.cam.go('c', mv({ mode: 'ease' })); r.advance(6000);
    expect(r.calls.filter((c) => c.startsWith('ease'))).toHaveLength(1);
    expect(r.cam.moves().some((m) => m.label === 'b' && /replaced by c/.test(m.note ?? ''))).toBe(true);
  });
  it('jumps at once (the opening frame), whatever came before', () => {
    const r = rig();
    r.cam.go('a', mv()); r.cam.go('open', mv({ mode: 'jump', duration: 0 }));
    expect(r.calls).toEqual(['fly@0', 'jump@0']);
  });
  it('holds and says why when the target is unknown, and stops on pause', () => {
    const r = rig();
    r.cam.hold('last-call-1', 'no target');
    expect(r.cam.moves()).toEqual([{ label: 'last-call-1', move: null, note: 'held: no target' }]);
    r.cam.go('a', mv()); r.advance(10); r.cam.go('b', mv()); r.cam.stop(); r.advance(5000);
    expect(r.calls).toEqual(['fly@0', 'stop']);
  });
});

describe('the conductor\'s camera', () => {
  const T0 = Date.UTC(2017, 7, 27, 3, 15);
  const ticks = Array.from({ length: 60 }, (_, i) => T0 + i * 15 * 60_000);
  const snap = (over: Partial<Snapshot> = {}): Snapshot => ({ mode: 'replay', tickAt: T0, clockMs: T0, ready: true, cases: 0, firstCaseAt: null, possibly: 1, cutOff: 0, headlineCutOff: 0, headlineFlagged: 0,
    freshness: ['fresh'], lastCall: null, aerial: null, ranked: [], listening: null, offline: null, pinned: [], ...over });
  const spec = (name: string, list = SCRIPT) => list.find((e) => e.name === name)!.camera;

  it('has the briefed moves for Beat 1: zoom, duration and verb', () => {
    expect(spec('playhead-start')).toMatchObject({ frame: 'metro', zoom: 10, bearing: 15, duration: 2000, mode: 'ease' });
    expect(spec('cutoff-climbs')).toMatchObject({ frame: 'metro-north', zoom: 11, duration: 1400, mode: 'fly' });
    expect(spec('last-call-1')).toMatchObject({ frame: 'zone', zoom: 13, duration: 1600, mode: 'fly' });
    expect(spec('aerial-populates')).toMatchObject({ frame: 'zone', zoom: 14, duration: 1400, mode: 'fly' });
    expect(spec('last-call-2')).toMatchObject({ frame: 'zone', zoom: 13, duration: 1200, mode: 'fly' });
    expect(spec('freeze-end')).toMatchObject({ frame: 'metro', zoom: 10, duration: 1800, mode: 'ease' });
    expect(BEATS.isolation.opening).toMatchObject({ frame: 'metro', zoom: 10, mode: 'jump' });
  });
  it('has the briefed moves for Beat 2, none on the reply, none on the Case', () => {
    expect(spec('open-scenario', SCRIPT_LISTENING)).toBeUndefined();
    expect(BEATS.listening.opening).toMatchObject({ frame: 'metro', zoom: 11 });
    expect(spec('playhead-start', SCRIPT_LISTENING)).toMatchObject({ frame: 'metro', zoom: 11, mode: 'ease' });
    expect(spec('cascade-fires', SCRIPT_LISTENING)).toMatchObject({ frame: 'zone', zoom: 14, duration: 1400, mode: 'fly' });
    expect(spec('first-reply-help', SCRIPT_LISTENING)).toBeUndefined();
    expect(spec('depth-knee', SCRIPT_LISTENING)).toMatchObject({ frame: 'zone', zoom: 14.5, mode: 'ease' });
    expect(spec('second-reply', SCRIPT_LISTENING)).toMatchObject({ frame: 'zone', zoom: 15, duration: 1400, mode: 'fly' });
    expect(spec('corroboration-2', SCRIPT_LISTENING)).toMatchObject({ frame: 'zones', zoom: 13.5, duration: 1200, mode: 'ease' });
    expect(spec('case-opens', SCRIPT_LISTENING)).toBeUndefined();
    expect(spec('freeze-end', SCRIPT_LISTENING)).toMatchObject({ frame: 'metro', zoom: 11, duration: 1600, mode: 'ease' });
  });
  it('has no camera in Beat 3', () => {
    expect(SCRIPT_OFFLINE.every((e) => !e.camera)).toBe(true);
    expect(BEATS.offline.opening).toBeUndefined();
  });
  it('never asks for a zoom past 16, a tilt, or a typed coordinate', () => {
    const all = [...SCRIPT, ...SCRIPT_LISTENING].flatMap((e) => (e.camera ? [e.camera] : [])).concat([BEATS.isolation.opening!, BEATS.listening.opening!]);
    for (const c of all) { expect(c.zoom).toBeLessThanOrEqual(16); expect(c.pitch ?? 0).toBe(0); expect('center' in c).toBe(false); }
    const src = readFileSync(join(__dirname, '..', 'dev', 'conductor.ts'), 'utf8');
    expect(src).not.toMatch(/center:\s*\[|lng|\blat\b/);
  });
  it('names the zone each step talks about, from the data it read', () => {
    const lc = SCRIPT.find((e) => e.name === 'last-call-1')!;
    const z = { zone_id: 'zlc', zone_name: 'b', status: 'counting', cutoff_at: new Date(T0 + 3 * 3_600_000).toISOString(), last_call_at: '', minutes_to_last_call: null, minutes_to_cutoff: null, hindsight: true, was_reconnected: false };
    const lastCall = { run_id: 'r', mode: 'replay', at: '', label: '', available: true, reason: null, lead: { reply_minutes: 0, decision_minutes: 0, travel_minutes: 0, total_minutes: 0, note: '' }, counts: { counting: 1, passed: 0, cut_off: 0, reconnected: 0 }, zones: [z] };
    expect(lc.check(snap({ lastCall: lastCall as never }), {}).zones).toEqual(['zlc']);
    expect(SCRIPT.find((e) => e.name === 'aerial-populates')!.check(snap({ aerial: [{ rank: 1, zoneId: 'zaer', name: 'n', minutes: 5 }] }), {}).zones).toEqual(['zaer']);
  });
  it('takes the scenario\'s zones from the Cases: the late block, the knee block, the block of the second reporter, every block with a depth report', () => {
    const k = (rule_fragment: string, engine = 'listening', direction = 'supports'): Contribution => ({ engine, direction, engine_confidence: 1, effective_confidence: 1, independent_sources: 1, first_observed_at: '', last_confirmed_at: '', rule_fragment });
    const c = (id: string, zone: string, cs: Contribution[]): Case => ({ id, zone_id: zone, household_id: id, status: 'open', confidence_word: 'single_source', opened_at: '', inference_sentence: '', support: 1, contradiction: 0, fresh_sources: 1, engines: [], contributions: cs, tasks: [] });
    const cases = [c('1', 'A', [k('late', 'silence'), k('cascade escalated_voice: x', 'listening', 'procedural')]), c('2', 'A', [k('late', 'silence')]), c('3', 'B', [k('late', 'silence')]),
      c('4', 'A', [k('reported knee-deep water')]), c('5', 'A', [k('reported waist-deep water')]), c('6', 'B', [k('reported ankle-deep water')])];
    const f = listeningFacts(cases, null);
    expect(f.lateZoneIds).toEqual(['A', 'B']); // two late households in A, one in B
    const s = snap({ mode: 'scenario', listening: { ...f, zoneCases: [{ caseId: 'z', zoneId: 'A', openedAt: '', sentence: '', evidence: 'e' }], raisedZones: [{ zoneId: 'A', name: 'A', level: 'extreme' }] } });
    const z = (n: string) => SCRIPT_LISTENING.find((e) => e.name === n)!.check(s, {}).zones;
    expect(z('cascade-fires')).toEqual(['A']);
    expect(z('depth-knee')).toEqual(['A']);
    expect(z('second-reply')).toEqual(['A']);
    expect(z('corroboration-2')).toEqual(['A', 'B']);
  });

  function run(snapshotAt: (clock: number) => Snapshot, beat: 'isolation' | 'listening' = 'isolation') {
    let nowMs = 0;
    let clk = T0;
    const looks: { label: string; spec: unknown; zones: string[]; why?: string }[] = [];
    const host: Host = { snapshot: () => ({ ...snapshotAt(clk), clockMs: clk, tickAt: ticks[tickIndexAt(clk, ticks)] }), goToTick: () => {}, setClock: (ms) => { clk = ms; }, pinZone: () => {}, pulseZone: () => {}, reveal: () => {}, caption: () => {}, frozen: () => {}, offline: () => {},
      look: (label, s, zones, why) => looks.push({ label, spec: s, zones, why }) };
    const clock = new PlayerClock(() => nowMs);
    const c = createConductor(host, ticks, T0, beat, clock);
    clock.play(); c.start();
    while (c.running() && nowMs < 120_000) { nowMs += 100; c.tick(); }
    return { looks, c };
  }
  it('opens a beat on its frame, and again at Play, so Restart returns to it', () => {
    const { looks } = run((cl) => ({ ...snap({ clockMs: cl }), ready: true }));
    expect(looks.filter((l) => l.label === 'opening')).toHaveLength(2);
    expect(looks[0]).toMatchObject({ label: 'opening', spec: { frame: 'metro', zoom: 10 } });
  });
  it('moves the camera only for a step that fired, and holds, saying why, for one that was skipped', () => {
    const { looks, c } = run(() => snap({ headlineCutOff: 0 })); // nothing climbs, nothing counts down, no ranking
    const names = looks.map((l) => l.label);
    for (const skipped of ['cutoff-climbs', 'last-call-1', 'aerial-populates', 'last-call-2']) {
      const l = looks.find((x) => x.label === skipped)!;
      expect([skipped, l.spec]).toEqual([skipped, null]);
      expect(l.why).toMatch(/skipped/);
      expect(c.log().find((e) => e.name === skipped)!.ok).toBe(false);
    }
    expect(names).toContain('playhead-start');
    expect(looks.find((l) => l.label === 'freeze-end')!.spec).toMatchObject({ frame: 'metro', zoom: 10, mode: 'ease' });
  });
  it('is the same every run: no randomness in what the camera is asked to do', () => {
    const a = run(() => snap({ aerial: [{ rank: 1, zoneId: 'z1', name: 'n', minutes: 1 }] })).looks, b = run(() => snap({ aerial: [{ rank: 1, zoneId: 'z1', name: 'n', minutes: 1 }] })).looks;
    expect(b).toEqual(a);
    expect(PACING_ISOLATION.freezeAtS).toBe(40);
  });
});

describe('keeping the camera out of the tour and out of the product', () => {
  it('the tour does not import the camera layer, and nothing outside the conductor does', () => {
    expect(readFileSync(join(__dirname, '..', 'dev', 'tour.ts'), 'utf8')).not.toMatch(/from '\.\/camera'/);
    const overlay = readFileSync(join(__dirname, '..', 'dev', 'DevOverlay.tsx'), 'utf8');
    expect(overlay).toMatch(/await import\('\.\/camera'\)/);
    expect(overlay).not.toMatch(/^import (?!type )[^\n]*from '\.\/camera'/m);
    const app = readFileSync(join(__dirname, '..', 'App.tsx'), 'utf8');
    expect(app).not.toMatch(/from '\.\/dev\/camera'/);
  });
  it('the map only holds its view for the conductor', () => {
    const app = readFileSync(join(__dirname, '..', 'App.tsx'), 'utf8');
    expect(app).toMatch(/holdView=\{demo\.active\}/);
    expect(readFileSync(join(__dirname, '..', 'components', 'ZoneMap.tsx'), 'utf8')).not.toMatch(/from '\.\.?\/(\.\.\/)?dev\//);
  });
});
