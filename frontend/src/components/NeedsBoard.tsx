// The run's operator-entered needs at a glance: totals by item, and which open needs are in cut-off zones. These are
// claims typed in by people, never measured, and the strip says so. Where entries are refused (a replay), it says
// why in the server's words. A fixed-height row, so it doesn't push the page when the answer arrives.

import { PackageOpen } from 'lucide-react';
import type { Needs } from '../lib/api';
import { label } from '../lib/format';

export function NeedsBoard({ needs, error, onSelectZone, onPortal }: { needs: Needs | null; error: string | null; onSelectZone: (zoneId: string) => void; onPortal: () => void }) {
  const s = needs?.summary;
  return (
    <div className="custom-scrollbar flex h-9 items-center gap-2 overflow-x-scroll whitespace-nowrap border-b border-accent-cyan/15 bg-navy-deep px-3 font-mono text-[10px] text-slate-400"
         title={needs?.label}>
      <PackageOpen className="h-3.5 w-3.5 shrink-0 text-accent-cyan" />
      <span className="uppercase tracking-wider">Needs board</span>
      {needs?.writable && (
        <button type="button" onClick={onPortal}
                className="cursor-pointer rounded border border-accent-cyan/50 bg-cyan-950/40 px-1.5 py-px font-bold uppercase text-accent-cyan hover:bg-cyan-900/50">
          Donation portal
        </button>
      )}
      {error ? <span className="text-danger-red">{error}</span>
        : !needs || !s ? <span>loading…</span>
        : !needs.writable && s.zones_with_open_needs === 0 ? <span>off for this run: {needs.blocked_reason}</span>
        : s.zones_with_open_needs === 0 ? <span>nothing entered at this time. Open a zone to enter a need.</span>
        : (
          <>
            {Object.entries(s.by_item).map(([item, v]) => (
              <span key={item}><b className="text-slate-200">{label(item)} {v.remaining.toLocaleString()}</b> in {v.zones} {v.zones === 1 ? 'zone' : 'zones'}{v.pledged > 0 ? ` (${v.pledged.toLocaleString()} offered)` : ''}</span>
            ))}
            {s.open_in_cut_off_zones > 0 && (
              <>
                <span className="text-danger-red">· {s.open_in_cut_off_zones} {s.open_in_cut_off_zones === 1 ? 'zone' : 'zones'} with open needs cut off:</span>
                {s.cut_off_zone_ids.map((id) => (
                  <button key={id} type="button" onClick={() => onSelectZone(id)}
                          className="cursor-pointer rounded border border-danger-red/40 px-1.5 py-px text-danger-red hover:bg-red-950/40">
                    {needs.zones[id]?.name ?? id.slice(0, 8)}
                  </button>
                ))}
              </>
            )}
            {s.open_pledges_in_cut_off_zones > 0 && <span className="text-danger-red">· {s.open_pledges_in_cut_off_zones} {s.open_pledges_in_cut_off_zones === 1 ? 'offer is' : 'offers are'} to cut-off zones</span>}
            {s.open_in_possibly_cut_off_zones > 0 && <span className="text-warning-orange">· {s.open_in_possibly_cut_off_zones} may be cut off</span>}
            <span className="text-slate-500">· entered by operators, not measured</span>
          </>
        )}
    </div>
  );
}
