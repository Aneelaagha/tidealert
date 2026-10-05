import { describe, expect, it } from 'vitest';
import type { Needs } from '../lib/api';
import { canEnter } from '../lib/needs';

const needs = (over: Partial<Needs> = {}): Needs => ({
  run_id: 'r', mode: 'mixed', at: 't', label: 'Entered by an operator', writable: true, blocked_reason: null,
  items: ['water'], max_quantity: 1000, max_note: 300, zones: {},
  summary: { zones_with_open_needs: 0, by_item: {}, open_in_cut_off_zones: 0, open_in_possibly_cut_off_zones: 0, cut_off_zone_ids: [], open_pledges: 0, open_pledges_in_cut_off_zones: 0 },
  ...over,
});

describe('when a need can be entered', () => {
  it('waits for the board to load', () => {
    expect(canEnter(null, 'Sam', '5')).toEqual({ ok: false, reason: 'the needs board is loading' });
  });

  it('gives the server\'s own reason on a run that refuses entries (a replay)', () => {
    const r = canEnter(needs({ writable: false, blocked_reason: 'run X is a replay of a recorded event' }), 'Sam', '5');
    expect(r).toEqual({ ok: false, reason: 'run X is a replay of a recorded event' });
  });

  it('needs an operator name: there is no login, so the name is the only record of who entered it', () => {
    expect(canEnter(needs(), '   ', '5').ok).toBe(false);
    expect(canEnter(needs(), 'Sam', '5')).toEqual({ ok: true, reason: null });
  });

  it('accepts only a whole number from 1 to the server\'s maximum', () => {
    for (const q of ['', ' ', '0', '-2', '1.5', 'ten', '1001']) expect(canEnter(needs(), 'Sam', q).ok, q).toBe(false);
    expect(canEnter(needs(), 'Sam', '1000').ok).toBe(true);
  });
});
