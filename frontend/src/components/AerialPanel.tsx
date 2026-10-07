// "Aerial priority": of the zones no dry road reaches, which an aerial asset should look at first. A RANKING only: it tasks
// nothing, shows no feed, no telemetry and no aircraft. On a replay it ranks by how long a zone has been cut off and leaves
// silence out (no opt-in registry existed in 2017), so it shows no score; elsewhere it ranks by silent households. Cell
// coverage is not assessed on any row: no coverage data exists here, so the factor is absent, not zero.

import { Eye } from 'lucide-react';
import type { AerialPriority } from '../lib/api';
import { Mono } from './ui';

interface Props {
  data: AerialPriority | null;
  error: string | null;
  selectedZoneId: string | null;
  onSelect: (zoneId: string) => void;
}

export function AerialPanel({ data, error, selectedZoneId, onSelect }: Props) {
  return (
    <section className="rounded-lg border border-accent-cyan/25 bg-navy-panel p-4" aria-label="Aerial priority">
      <h2 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-white">
        <Eye className="h-4 w-4 text-accent-cyan" /> Aerial priority
        {data?.silence_active && <span className="ml-auto text-[11px] font-normal normal-case text-accent-cyan">Silence inputs active</span>}
      </h2>
      {error ? <p className="mt-2 text-sm text-danger-red">{error}</p>
        : !data ? <p className="mt-2 text-sm text-slate-500">loading…</p>
        : !data.available ? <p className="mt-2 rounded border border-white/10 p-2 text-sm text-slate-400">{data.reason}</p>
        : (
          <>
            {data.zones.length === 0 ? <p className="mt-2 text-sm text-slate-500">{data.empty}</p> : (
              <>
                <p className="mt-1 text-xs text-slate-500">Top {data.shown} of {data.cut_off_zones.toLocaleString()} cut-off zones.</p>
                <ol className="mt-2 space-y-1" aria-label="Aerial priority, highest first">
                  {data.zones.map((z) => (
                    <li key={z.zone_id}>
                      <button type="button" onClick={() => onSelect(z.zone_id)} aria-current={selectedZoneId === z.zone_id}
                              className={`flex w-full min-w-0 cursor-pointer items-start gap-2 rounded border px-2 py-1.5 text-left transition hover:border-accent-cyan/50 ${selectedZoneId === z.zone_id ? 'border-accent-cyan bg-cyan-950/40' : 'border-white/10 bg-navy-deep/60'}`}>
                        <b className="mt-0.5 w-4 shrink-0 text-sm tabular-nums text-accent-cyan">{z.rank}</b>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm text-slate-200" title={z.zone_name}><Mono>{z.zone_name.replace(/^USGS-\d+ /, '')}</Mono></span>
                          <span className="block text-xs text-slate-400">{z.reason_fragments.join(', ')}</span>
                          <span className="block text-xs font-bold text-slate-200">Aerial task recommended</span>
                        </span>
                        {z.score !== null && <span className="shrink-0 text-right text-xs text-slate-400">score <b className="text-sm tabular-nums text-slate-100">{z.score}</b></span>}
                      </button>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </>
        )}
      <p className="mt-2 text-[11px] leading-snug text-slate-500">
        Cell coverage is not assessed: no coverage data exists here, so the ranking leaves it out instead of guessing. "Cut off" means no dry road route, as the engine finds it.
        {data && !data.silence_active && ' Isolation is recorded data.'}
      </p>
    </section>
  );
}
