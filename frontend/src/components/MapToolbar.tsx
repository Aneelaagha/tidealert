// The one bar above the map: what colours the zones (risk level, or supply access), the donation portal, and, on runs
// that take operator-entered needs, a line of what is needed. It replaces three stacked strips. The zones summary
// sits under the map. Nothing here is computed in the browser: counts come from /map/supply-access and /needs, and
// the needs are what operators typed in, never measured.
//
// Layout: the first row is always there. The needs row is reserved from the run's mode (known at load) so it doesn't
// push the page when the answer arrives; the supply counts row appears only when the person switches the layer on.

import { HandHeart, Truck } from 'lucide-react';
import type { Needs, Run, SupplyAccess } from '../lib/api';
import { colorOf, UNSTYLED } from '../lib/colors';
import { label } from '../lib/format';

export type Layer = 'risk' | 'supply';

interface Props {
  run: Run | null;
  layer: Layer;
  onLayer: (l: Layer) => void;
  supply: SupplyAccess | null;
  supplyError: string | null;
  needs: Needs | null;
  needsError: string | null;
  onSelectZone: (zoneId: string) => void;
  onPortal: () => void;
}

const row = 'custom-scrollbar flex items-center gap-2 overflow-x-auto whitespace-nowrap border-b border-accent-cyan/15 bg-navy-deep px-3 text-xs text-slate-400';

export function MapToolbar({ run, layer, onLayer, supply, supplyError, needs, needsError, onSelectZone, onPortal }: Props) {
  const tab = (l: Layer, text: string, title?: string) => (
    <button type="button" onClick={() => onLayer(l)} aria-pressed={layer === l} title={title}
            className={`cursor-pointer rounded border px-2 py-0.5 text-xs font-bold uppercase transition ${
              layer === l ? 'border-accent-cyan bg-cyan-950/60 text-accent-cyan' : 'border-white/10 text-slate-400 hover:text-slate-200'}`}>
      {text}
    </button>
  );
  const s = needs?.summary;
  const takesNeeds = !!run && run.mode !== 'replay';
  return (
    <>
      <div className={`${row} h-9`}>
        <Truck className="h-3.5 w-3.5 shrink-0 text-accent-cyan" />
        <span className="uppercase tracking-wider">Colour zones by</span>
        {tab('risk', 'Risk level')}
        {tab('supply', 'Supply access', supply?.does_not_show ?? 'Route feasibility from the main road network only: no origin, route, distance or vehicle.')}
        {needs?.writable && (
          <button type="button" onClick={onPortal}
                  className="ml-auto flex shrink-0 cursor-pointer items-center gap-1 rounded border border-accent-cyan/50 bg-cyan-950/40 px-2 py-0.5 font-bold uppercase text-accent-cyan hover:bg-cyan-900/50">
            <HandHeart className="h-3 w-3" /> Donation portal
          </button>
        )}
      </div>

      {layer === 'supply' && (
        <div className={`${row} h-8`} title={supply?.does_not_show}>
          {supplyError ? <span className="text-danger-red">{supplyError}</span>
            : !supply ? <span>loading supply access…</span>
            : supply.states.every((st) => !supply.counts[st]?.zones) ? <span>this run has no zones in view, so there is nothing to assess</span>
            : (
              <>
                {supply.states.map((st) => (
                  <span key={st} className="inline-flex items-center gap-1" title={`${supply.counts[st]?.population.toLocaleString() ?? '?'} people recorded in these zones`}>
                    <span className="h-2.5 w-2.5 rounded-sm border border-white/20" style={{ background: colorOf('supply_access', st) ?? UNSTYLED }} />
                    {supply.labels[st] ?? st} <b className="text-slate-200">{supply.counts[st]?.zones.toLocaleString() ?? '?'}</b>
                  </span>
                ))}
                <span className="text-slate-500">zones (access only, not a route)</span>
              </>
            )}
        </div>
      )}

      {takesNeeds && (
        <div className={`${row} h-8`} title={needs?.label}>
          <span className="uppercase tracking-wider">Needs</span>
          {needsError ? <span className="text-danger-red">{needsError}</span>
            : !needs || !s ? <span>loading…</span>
            : s.zones_with_open_needs === 0 ? <span>none entered at this time. Open a zone to enter one.</span>
            : (
              <>
                {Object.entries(s.by_item).map(([item, v]) => (
                  <span key={item}><b className="text-slate-200">{label(item)} {v.remaining.toLocaleString()}</b>{v.pledged > 0 ? ` (${v.pledged.toLocaleString()} offered)` : ''}</span>
                ))}
                {s.open_in_cut_off_zones > 0 && (
                  <>
                    <span className="text-danger-red">· cut off:</span>
                    {s.cut_off_zone_ids.map((id) => (
                      <button key={id} type="button" onClick={() => onSelectZone(id)}
                              className="cursor-pointer rounded border border-danger-red/40 px-1.5 py-px text-danger-red hover:bg-red-950/40">
                        {needs.zones[id]?.name?.replace(/^USGS-\d+ /, '') ?? id.slice(0, 8)}
                      </button>
                    ))}
                  </>
                )}
                {s.open_in_possibly_cut_off_zones > 0 && <span className="text-warning-orange">· {s.open_in_possibly_cut_off_zones} may be cut off</span>}
                {s.open_pledges_in_cut_off_zones > 0 && <span className="text-danger-red">· {s.open_pledges_in_cut_off_zones} {s.open_pledges_in_cut_off_zones === 1 ? 'offer' : 'offers'} to cut-off zones</span>}
                <span className="text-slate-500">· typed in by operators, not measured</span>
              </>
            )}
        </div>
      )}
    </>
  );
}
