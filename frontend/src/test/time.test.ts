import { describe, expect, it } from 'vitest';
import { tickIndex, ticksFor, readUrl, writeUrl } from '../lib/time';

const RUN = { mode: 'scenario', window_start: '2026-09-10T14:00:00+00:00', window_end: '2026-09-10T17:00:00+00:00' };

describe('the run clock', () => {
  it('steps every 15 minutes across the window, both ends included', () => {
    const t = ticksFor(RUN);
    expect(t).toHaveLength(13);
    expect(t[0]).toBe('2026-09-10T14:00:00.000Z');
    expect(t[12]).toBe('2026-09-10T17:00:00.000Z');
  });

  it('has no stops for a live run', () => {
    expect(ticksFor({ ...RUN, mode: 'live' })).toEqual([]);
    expect(ticksFor({ ...RUN, window_start: null })).toEqual([]);
  });

  it('finds a requested time in any ISO form, else the end of the window', () => {
    const t = ticksFor(RUN);
    expect(tickIndex(t, '2026-09-10T15:30:00Z')).toBe(6);
    expect(tickIndex(t, '2026-09-10T15:30:00+00:00')).toBe(6);
    expect(tickIndex(t, '2026-09-10T15:31:00Z')).toBe(12);
    expect(tickIndex(t, 'garbage')).toBe(12);
    expect(tickIndex(t, null)).toBe(12);
    expect(tickIndex([], null)).toBe(0);
  });

  it('round-trips the run and time through the URL', () => {
    const q = writeUrl('abc', '2026-09-10T15:30:00.000Z');
    expect(readUrl(q)).toEqual({ run: 'abc', at: '2026-09-10T15:30:00.000Z' });
    expect(readUrl(writeUrl('abc', null))).toEqual({ run: 'abc', at: null });
  });
});
