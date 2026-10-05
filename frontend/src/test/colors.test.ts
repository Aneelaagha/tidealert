import { describe, expect, it } from 'vitest';
import { COLORS, UNSTYLED, colorOf, matchColor } from '../lib/colors';

describe('the color table', () => {
  it('never colors unknown as safe', () => {
    expect(colorOf('risk_level', 'unknown')).not.toEqual(colorOf('risk_level', 'safe'));
  });

  it('separates a missing entry (unstyled) from a deliberate null (not drawn)', () => {
    expect(colorOf('risk_level', 'flooded')).toBeUndefined();
    expect(colorOf('task_status', 'complete')).toBeNull();
    expect(colorOf('risk_level', null)).toBeUndefined();
  });

  it('draws unknown values magenta and leaves null entries out of the map expression', () => {
    const expr = matchColor('task_status');
    expect(expr[expr.length - 1]).toBe(UNSTYLED);
    expect(expr).not.toContain('complete');
    expect(expr).toContain('pending');
  });

  it('keeps every real color away from the unstyled magenta', () => {
    for (const table of Object.values(COLORS)) {
      for (const c of Object.values(table)) expect(c?.toLowerCase()).not.toBe(UNSTYLED);
    }
  });
});

describe('the supply-access colors', () => {
  const states = ['isolated', 'possibly_isolated', 'reconnected', 'reachable', 'not_evaluated'];

  it('colors every state the server can return, none in the unstyled magenta', () => {
    for (const s of states) {
      expect(colorOf('supply_access', s), s).toBeTypeOf('string');
      expect(colorOf('supply_access', s)).not.toEqual(UNSTYLED);
    }
  });

  it('never draws "not assessed" or "reconnected" in the reachable color', () => {
    expect(colorOf('supply_access', 'not_evaluated')).not.toEqual(colorOf('supply_access', 'reachable'));
    expect(colorOf('supply_access', 'reconnected')).not.toEqual(colorOf('supply_access', 'reachable'));
  });

  it('draws an unexpected state magenta', () => {
    expect(colorOf('supply_access', 'open_road')).toBeUndefined();
  });
});
