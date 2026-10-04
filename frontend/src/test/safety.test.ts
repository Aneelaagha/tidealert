import { describe, expect, it } from 'vitest';
import type { Safety } from '../lib/api';
import { safetyLabel } from '../components/SafetyNote';

const s = (over: Partial<Safety>): Safety => ({ zone_access: 'reachable', since: null, mechanism: null, reason: '',
  warnings: [], assignment_note: null, ...over });

describe('task safety badges', () => {
  it('flags cut-off zones, and cut-off-after-assignment above that', () => {
    expect(safetyLabel(s({ zone_access: 'isolated' }))?.text).toBe('ZONE CUT OFF');
    expect(safetyLabel(s({ zone_access: 'isolated',
      warnings: [{ code: 'isolated_after_assignment', severity: 'high', since: null, text: '' }] }))?.text).toBe('CUT OFF AFTER ASSIGNMENT');
    expect(safetyLabel(s({ zone_access: 'possibly_isolated' }))?.tone).toBe('amber');
  });

  it('says "not assessed" rather than nothing, and never badges reconnected or reachable as a problem', () => {
    expect(safetyLabel(s({ zone_access: 'not_evaluated' }))?.text).toBe('ACCESS NOT ASSESSED');
    expect(safetyLabel(s({ zone_access: 'reconnected' }))).toBeNull();
    expect(safetyLabel(s({ zone_access: 'reachable' }))).toBeNull();
    expect(safetyLabel(undefined)).toBeNull();
  });
});
