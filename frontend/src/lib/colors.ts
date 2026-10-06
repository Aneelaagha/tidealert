// The only value -> color table. Every color on the map and in the legend comes from here, keyed by values the API
// returns. A value with no entry draws in UNSTYLED magenta and the legend flags it, so an unexpected value is never
// given a color that looks like a real state. `null` means deliberately not drawn (a closed task leaves no marker).

export const UNSTYLED = '#ff00ff';

export const COLORS: Record<'risk_level' | 'confidence_word' | 'task_status' | 'supply_access' | 'depot_access', Record<string, string | null>> = {
  // Fill. unknown is a neutral grey at low opacity: "not assessed", never green.
  risk_level: { unknown: '#9aa0a6', safe: '#34c759', elevated: '#ff9500', extreme: '#ff3b30' },
  // Case outline; stale_verify is also dashed. Kept clear of the UNSTYLED magenta.
  confidence_word: { corroborated: '#00f0ff', single_source: '#4f8cff', stale_verify: '#a1887f' },
  // The supply-access layer's fill (zone access from the main road network). not_evaluated is the same neutral grey as
  // unknown risk: not assessed, never green. reconnected is the optimistic bound, so it is not the reachable green.
  supply_access: { isolated: '#ff3b30', possibly_isolated: '#ff9500', reconnected: '#5ac8fa', reachable: '#34c759',
                   not_evaluated: '#9aa0a6' },
  // The depot-access layer's fill: can a dry road route reach the zone from the chosen depot. "outside_network" is a zone in
  // another basin's road network: not assessed from this depot, drawn faint grey like not_evaluated, never green.
  depot_access: { reachable: '#34c759', only_if_unknown_roads_passable: '#5ac8fa', not_reachable: '#ff3b30', not_evaluated: '#9aa0a6',
                  outside_network: '#6b7280' },
  // Task marker fill. pending is white (hollow): nobody is on it yet.
  task_status: { pending: '#ffffff', assigned: '#4f8cff', en_route: '#34c759',
                 complete: null, unable_to_reach: null, cancelled: null },
};

export const TASK_VERIFY_EDGE = '#ff9500'; // thick amber edge: verify before dispatch
export const TASK_RADIUS: Record<string, number> = { high: 9, medium: 7, low: 5 };
export const GAP_COLOR = '#8b98a9';
export const SELECTED_COLOR = '#ffffff';

export type Field = keyof typeof COLORS;

/** The color for a value: a string, null (deliberately not drawn), or undefined (no entry: draw UNSTYLED). */
export function colorOf(field: Field, value: string | null | undefined): string | null | undefined {
  if (value == null) return undefined;
  return Object.prototype.hasOwnProperty.call(COLORS[field], value) ? COLORS[field][value] : undefined;
}

/** A MapLibre `match` expression over a feature property, falling back to UNSTYLED. */
export function matchColor(field: Field): unknown[] {
  const pairs = Object.entries(COLORS[field]).filter(([, c]) => c).flat();
  return ['match', ['coalesce', ['get', field], '__null__'], ...pairs, UNSTYLED];
}
