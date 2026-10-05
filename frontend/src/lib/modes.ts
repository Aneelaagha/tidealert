// How each run mode is labelled. A run's mode is registered on the server and never inferred here; a mode this table
// doesn't know draws in the unstyled magenta.

export const MODE_BADGE: Record<string, { label: string; className: string }> = {
  replay: { label: 'REPLAY', className: 'border-purple-400/60 bg-purple-950/40 text-purple-300' },
  scenario: { label: 'SCENARIO', className: 'border-warning-orange/60 bg-orange-950/30 text-warning-orange' },
  live: { label: 'LIVE', className: 'border-danger-red/60 bg-red-950/30 text-danger-red' },
  // Its own colour and a striped fill, so it can't be read as Harvey (purple) or a pure scenario (orange).
  mixed: { label: 'MIXED: REAL FLOOD + SYNTHETIC RESPONDERS', className: 'mixed-badge border-teal-300/70 text-teal-200' },
};

export const MODE_MEANING: Record<string, string> = {
  replay: 'a past event replayed from its recorded data: what the system would have shown at the time',
  scenario: 'synthetic households and scripted replies: a test, not real people or a real event',
  live: 'real-time sources (no live run exists yet)',
  mixed: "a real recorded event (Harvey's flood and isolation results) with a synthetic layer on top (responders and "
    + 'their assignments): the flood is real, the responders and anything they cause are not',
};

export function modeBadge(mode: string): { label: string; className: string } {
  return MODE_BADGE[mode] ?? { label: mode.toUpperCase(), className: 'border-unstyled bg-unstyled/20 text-unstyled' };
}
