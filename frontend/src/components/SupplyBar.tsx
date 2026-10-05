// The map's colour layer switch, and (for the supply layer) what it counts. Supply access is route feasibility from
// the main road network only; the server's own statement of what it does not show is on the bar's tooltip and in the
// legend, and the bar says it in short.

import { Truck } from 'lucide-react';
import type { SupplyAccess } from '../lib/api';
import { colorOf, UNSTYLED } from '../lib/colors';

export type Layer = 'risk' | 'supply';

export function SupplyBar({ layer, onLayer, supply, error }:
  { layer: Layer; onLayer: (l: Layer) => void; supply: SupplyAccess | null; error: string | null }) {
  const tab = (l: Layer, text: string) => (
    <button type="button" onClick={() => onLayer(l)} aria-pressed={layer === l}
            className={`cursor-pointer rounded border px-2 py-0.5 text-[10px] font-bold uppercase transition ${
              layer === l ? 'border-accent-cyan bg-cyan-950/60 text-accent-cyan' : 'border-white/10 text-slate-400 hover:text-slate-200'}`}>
      {text}
    </button>
  );
  return (
    <div className="custom-scrollbar flex items-center gap-2 overflow-x-scroll whitespace-nowrap border-b border-accent-cyan/15 bg-navy-deep px-3 py-1.5 font-mono text-[10px] text-slate-400"
         title={supply?.does_not_show}>
      <Truck className="h-3.5 w-3.5 shrink-0 text-accent-cyan" />
      <span className="uppercase tracking-wider">Zone colour</span>
      {tab('risk', 'Risk level')}
      {tab('supply', 'Supply access')}
      {layer === 'supply' && (error ? <span className="text-danger-red">{error}</span>
        : !supply ? <span>loading supply access…</span>
        : supply.states.every((s) => !supply.counts[s]?.zones) ? <span>this run has no zones in view, so there is nothing to assess</span>
        : (
          <>
            {supply.states.map((s) => (
              <span key={s} className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-sm border border-white/20" style={{ background: colorOf('supply_access', s) ?? UNSTYLED }} />
                {supply.labels[s] ?? s}: <b className="text-slate-200">{supply.counts[s]?.zones.toLocaleString() ?? '?'}</b> zones
                ({supply.counts[s]?.population.toLocaleString() ?? '?'} people)
              </span>
            ))}
            <span className="text-slate-500">· route feasibility from the main road network only: no origin, route, distance or vehicle</span>
          </>
        ))}
    </div>
  );
}
