import { describe, expect, it } from 'vitest';
import type { Needs } from '../lib/api';
import { canClose, canOffer } from '../lib/pledges';

const needs = (over: Partial<Needs> = {}): Needs => ({
  run_id: 'r', mode: 'mixed', at: 't', label: '', writable: true, blocked_reason: null, items: ['water'], max_quantity: 1000, max_note: 300, zones: {},
  summary: { zones_with_open_needs: 0, by_item: {}, open_in_cut_off_zones: 0, open_in_possibly_cut_off_zones: 0, cut_off_zone_ids: [], open_pledges: 0, open_pledges_in_cut_off_zones: 0 },
  ...over,
});

describe('when an offer can be made', () => {
  it('waits for the board and gives the server\'s reason on a run that refuses entries', () => {
    expect(canOffer(null, 'Aid', '5', 10).ok).toBe(false);
    expect(canOffer(needs({ writable: false, blocked_reason: 'a replay' }), 'Aid', '5', 10)).toEqual({ ok: false, reason: 'a replay' });
  });

  it('needs a shown name, and says no contact details are kept', () => {
    const r = canOffer(needs(), '  ', '5', 10);
    expect(r.ok).toBe(false);
    expect(r.reason).toContain('no contact details');
  });

  it('allows only a whole number up to what is open and not already offered', () => {
    for (const q of ['', '0', '-1', '2.5', 'ten']) expect(canOffer(needs(), 'Aid', q, 10).ok, q).toBe(false);
    expect(canOffer(needs(), 'Aid', '11', 10).reason).toBe('only 10 is open and not already offered');
    expect(canOffer(needs(), 'Aid', '10', 10)).toEqual({ ok: true, reason: null });
  });
});

describe('when an offer can be closed', () => {
  it('needs an operator name, since there is no login', () => {
    expect(canClose(needs(), ' ').ok).toBe(false);
    expect(canClose(needs(), 'Sam')).toEqual({ ok: true, reason: null });
  });
});
