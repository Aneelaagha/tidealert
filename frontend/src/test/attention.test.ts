import { describe, expect, it } from 'vitest';
import type { Case, Needs, ZonesResponse } from '../lib/api';
import { rankAttention } from '../lib/attention';

const zones = (names: string[]): ZonesResponse => ({ type: 'FeatureCollection', run_id: 'r', mode: 'replay', at: 't', gap_reasons: [],
  features: names.map((n) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { zone_id: n, name: `Zone ${n}`, case_count: 1 } as never })) });
const kase = (zone: string, access: string | null, over: { assigned?: boolean; priority?: string; word?: string; active?: boolean } = {}): Case => ({
  id: `c-${zone}`, zone_id: zone, confidence_word: over.word ?? 'single_source',
  tasks: access === null ? [] : [{ active: over.active ?? true, priority: over.priority ?? 'medium', assigned_responder_id: over.assigned ? 'resp' : null, safety: { zone_access: access, since: 's' } }],
} as unknown as Case);
const needs = (open: Record<string, number>): Needs => ({ zones: Object.fromEntries(Object.entries(open).map(([z, o]) => [z, { open: o }])) } as unknown as Needs);
const order = (zs: string[], cs: Case[], n: Needs | null = null) => rankAttention(zones(zs), cs, n).map((a) => a.zoneId);

describe('who needs attention first', () => {
  it('puts cut-off zones with nobody assigned first, then cut off with someone, then may be cut off, then the rest', () => {
    const cs = [kase('rest', null), kase('task', 'reachable'), kase('maybe', 'possibly_isolated'), kase('cutAssigned', 'isolated', { assigned: true }), kase('cutOpen', 'isolated')];
    expect(order(['rest', 'task', 'maybe', 'cutAssigned', 'cutOpen'], cs)).toEqual(['cutOpen', 'cutAssigned', 'maybe', 'task', 'rest']);
  });

  it('breaks ties by task priority, then Case confidence, then open needs, then name', () => {
    const cs = [kase('a', 'isolated', { priority: 'low' }), kase('b', 'isolated', { priority: 'high', word: 'stale_verify' }),
                kase('c', 'isolated', { priority: 'high', word: 'corroborated' }), kase('d', 'isolated', { priority: 'high', word: 'corroborated' })];
    expect(order(['a', 'b', 'c', 'd'], cs)).toEqual(['c', 'd', 'b', 'a']);
    expect(order(['a', 'b', 'c', 'd'], cs, needs({ d: 50 }))).toEqual(['d', 'c', 'b', 'a']);
  });

  it('ignores closed tasks when deciding a zone is cut off', () => {
    expect(rankAttention(zones(['x']), [kase('x', 'isolated', { active: false })], null)[0].group).toBe(4);
  });

  it('takes the worst access state of a zone with several Cases and selects its strongest Case', () => {
    const cs = [kase('z', 'reachable', { word: 'stale_verify' }), kase('z', 'isolated', { word: 'corroborated' })];
    cs[1] = { ...cs[1], id: 'strong' } as Case;
    const [a] = rankAttention(zones(['z']), cs, null);
    expect(a.access).toBe('isolated');
    expect(a.caseId).toBe('strong');
  });

  it('returns nothing until zones and Cases have loaded', () => {
    expect(rankAttention(null, [], null)).toEqual([]);
    expect(rankAttention(zones(['z']), null, null)).toEqual([]);
  });
});
