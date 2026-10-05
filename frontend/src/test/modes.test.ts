import { describe, expect, it } from 'vitest';
import { MODE_BADGE, MODE_MEANING, modeBadge } from '../lib/modes';

describe('run mode labels', () => {
  it('gives the mixed scenario its own badge, unlike Harvey (replay) or a pure scenario', () => {
    const mixed = modeBadge('mixed');
    expect(mixed.label).toMatch(/^MIXED/);
    expect(mixed.label).toMatch(/SYNTHETIC RESPONDERS/);
    for (const other of ['replay', 'scenario', 'live']) expect(mixed.className).not.toBe(MODE_BADGE[other].className);
    expect(mixed.className).not.toMatch(/purple|orange/);
  });

  it('explains every mode the server can return, the mixed one as real flood plus synthetic people', () => {
    for (const m of ['replay', 'scenario', 'live', 'mixed']) expect(MODE_MEANING[m]).toBeTruthy();
    expect(MODE_MEANING.mixed).toMatch(/flood is real.*not/);
  });

  it('draws an unknown mode in the unstyled magenta', () => {
    expect(modeBadge('rehearsal').className).toMatch(/unstyled/);
  });
});
