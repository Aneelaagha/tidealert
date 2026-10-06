// A small legend on the map for what the zone colour means right now, from the same colour table and vocabulary the
// full Legend panel uses. A value with no colour is shown in the unstyled magenta, as everywhere else.

import type { SupplyAccess, Vocabulary } from '../lib/api';
import { UNSTYLED, colorOf } from '../lib/colors';

const SUPPLY_FALLBACK: Record<string, string> = { isolated: 'cut off', possibly_isolated: 'may be cut off', reconnected: 'reconnected', reachable: 'reachable', not_evaluated: 'not assessed' };

export function MapLegend({ layer, vocabulary, supply }: { layer: 'risk' | 'supply'; vocabulary: Vocabulary | null; supply: SupplyAccess | null }) {
  const rows = layer === 'risk'
    ? (vocabulary?.risk_level ?? []).map((v) => ({ key: v, text: v === 'unknown' ? 'unknown (not assessed)' : v, color: colorOf('risk_level', v) }))
    : (supply?.states ?? Object.keys(SUPPLY_FALLBACK)).map((v) => ({ key: v, text: supply?.labels[v] ?? SUPPLY_FALLBACK[v] ?? v, color: colorOf('supply_access', v) }));
  return (
    <div className="pointer-events-none absolute bottom-7 left-2 z-10 rounded-md border border-white/15 bg-navy-deep/90 px-2.5 py-2 text-xs text-slate-300" aria-label="Map legend">
      <p className="mb-1 font-bold uppercase tracking-wider text-slate-400">{layer === 'risk' ? 'Zone risk level' : 'Supply access'}</p>
      {rows.map((r) => (
        <p key={r.key} className="flex items-center gap-1.5 py-px">
          <span className="h-3 w-4 shrink-0 rounded-sm border border-white/20" style={{ background: r.color ?? UNSTYLED }} />{r.text}
        </p>
      ))}
      <p className="mt-1 flex items-center gap-1.5 border-t border-white/10 pt-1"><span className="h-3 w-3 shrink-0 rounded-full border-2 border-slate-900 bg-white" />open task</p>
    </div>
  );
}
