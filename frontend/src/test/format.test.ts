import { describe, expect, it } from 'vitest';
import { sourceId, sourceStatus } from '../lib/format';

describe('the sources row', () => {
  it('names a gauge by its ID alone', () => {
    expect(sourceId('USGS 08074500 continuous')).toBe('08074500');
    expect(sourceId('NWS alerts')).toBe('NWS alerts'); // no ID: the name as stored
  });
  it('says "fresh" alone, and a stale source with its age in hours', () => {
    expect(sourceStatus('fresh', 0)).toBe('fresh');
    expect(sourceStatus('stale', 38700)).toBe('stale 10.8h');
    expect(sourceStatus('stale', 1800)).toBe('stale 30m');
    expect(sourceStatus('no_data', null)).toBe('no data');
    expect(sourceStatus('event_driven', null)).toBe('event-driven');
  });
});
