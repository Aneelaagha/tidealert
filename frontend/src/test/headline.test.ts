import { describe, expect, it } from 'vitest';
import type { Case, Run, Task, ZonesResponse } from '../lib/api';
import { headlineFacts, runPhrase } from '../components/Headline';

const run = (over: Partial<Run>): Run => ({ id: 'r', name: 'n', description: null, mode: 'replay', event: 'Hurricane Harvey', peak_at: null, window_start: null, window_end: null,
  case_count: 0, regions: [], extent: null, caveats: [], task_actions_blocked: null, sources: [], ...over });
const zones = (counts: number[]): ZonesResponse => ({ type: 'FeatureCollection', run_id: 'r', mode: 'replay', at: '2017-08-27T18:30:00+00:00', gap_reasons: [],
  features: counts.map((n, i) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { zone_id: `z${i}`, case_count: n } as never })) });
const caseWith = (zone: string, access: string, active = true): Case =>
  ({ zone_id: zone, tasks: [{ active, safety: { zone_access: access } }] } as unknown as Case);
const task = (responder: string | null, active = true): Task => ({ active, assigned_responder_id: responder } as unknown as Task);

describe('the headline numbers', () => {
  it('counts flagged zones (with Cases), cut-off zones among them, and distinct responders on active tasks', () => {
    const f = headlineFacts(zones([1, 1, 1, 0]), [caseWith('z0', 'isolated'), caseWith('z1', 'reconnected'), caseWith('z2', 'isolated')],
                            [task('a'), task('a'), task('b'), task(null), task('c', false)]);
    expect(f).toMatchObject({ flagged: 3, cutOff: 2, assigned: 2 });
  });

  it('counts a zone once even with several Cases, and ignores closed tasks', () => {
    const f = headlineFacts(zones([2]), [caseWith('z0', 'isolated'), caseWith('z0', 'isolated'), caseWith('z0', 'isolated', false)], []);
    expect(f?.cutOff).toBe(1);
  });

  it('counts zones the engine did not assess apart, so "0 cut off" never stands for "not cut off"', () => {
    const f = headlineFacts(zones([1, 1]), [caseWith('z0', 'not_evaluated'), caseWith('z1', 'isolated')], []);
    expect(f).toMatchObject({ flagged: 2, cutOff: 1, notAssessed: 1 });
    expect(headlineFacts(zones([1]), [caseWith('z0', 'not_evaluated')], [])).toMatchObject({ flagged: 1, cutOff: 0, notAssessed: 1 });
  });

  it('waits for all three answers rather than showing a partial headline', () => {
    expect(headlineFacts(null, [], [])).toBeNull();
    expect(headlineFacts(zones([1]), null, [])).toBeNull();
    expect(headlineFacts(zones([1]), [], null)).toBeNull();
  });
});

describe('how a run describes itself', () => {
  it('names the real event of a replay, and says nothing invented when there is none', () => {
    expect(runPhrase(run({}))).toBe('replay of Hurricane Harvey');
    expect(runPhrase(run({ event: null }))).toBe('replay of recorded data');
  });
  it('says plainly that the mixed run has synthetic responders and a scenario is not a real event', () => {
    expect(runPhrase(run({ mode: 'mixed' }))).toBe('mixed scenario: real Hurricane Harvey flood, synthetic responders');
    expect(runPhrase(run({ mode: 'scenario', event: null }))).toBe('synthetic scenario, not a real event');
  });
});
