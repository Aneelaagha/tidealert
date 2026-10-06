// "Last call": for each flagged zone, how long until the latest moment a dispatch could still set out before its roads close.
// last call = the engine's recorded cut-off time - the lead time you set. In this replay the cut-off times are known in
// hindsight and stand in for a forecast, and it is per zone, not per household. The page never says a zone is "lost" or
// "unreachable by any channel": cut off means no dry road route out, and roads reopen.

import { Hourglass } from 'lucide-react';
import { useState } from 'react';
import type { LastCall, LastCallZone } from '../lib/api';
import { type Lead, fmtCountdown, parseMinutes, totalLead } from '../lib/lastCall';
import { Mono, Time } from './ui';

function Countdown({ z }: { z: LastCallZone }) {
  if (z.status === 'counting') return <><b className="text-2xl tabular-nums text-warning-orange">{fmtCountdown(z.minutes_to_last_call ?? 0)}</b><span className="text-xs text-slate-400"> to last call</span></>;
  if (z.status === 'passed') return <><b className="text-lg text-danger-red">Last call passed</b><span className="text-xs text-slate-400"> · cut off in {fmtCountdown(z.minutes_to_cutoff ?? 0)}</span></>;
  return null;
}

export function ZoneLastCall({ z }: { z: LastCallZone | undefined }) {
  if (!z) return <span className="text-slate-500">no recorded cut-off for this zone, so no last call</span>;
  if (z.status === 'counting') return <span><b className="tabular-nums text-warning-orange">{fmtCountdown(z.minutes_to_last_call ?? 0)}</b> to last call (<Time t={z.last_call_at} />); cut off <Time t={z.cutoff_at} /></span>;
  if (z.status === 'passed') return <span><b className="text-danger-red">last call passed</b>; cut off in {fmtCountdown(z.minutes_to_cutoff ?? 0)} (<Time t={z.cutoff_at} />)</span>;
  if (z.status === 'cut_off') return <span>cut off since <Time t={z.cutoff_at} /></span>;
  return <span>reconnected: a dry route is open again (the optimistic bound, not a guarantee)</span>;
}

interface Props {
  data: LastCall | null;
  error: string | null;
  lead: Lead;
  onLead: (l: Lead) => void;
  onSelect: (zoneId: string) => void;
  selectedZoneId: string | null;
  limit?: number;
}

export function LastCallPanel({ data, error, lead, onLead, onSelect, selectedZoneId, limit = 6 }: Props) {
  const [draft, setDraft] = useState({ reply: String(lead.reply), decision: String(lead.decision), travel: String(lead.travel) });
  const set = (k: keyof Lead, v: string) => {
    setDraft((d) => ({ ...d, [k]: v }));
    const n = parseMinutes(v);
    if (n !== null) onLead({ ...lead, [k]: n });
  };
  const bad = (k: keyof Lead) => parseMinutes(draft[k]) === null;
  const field = (k: keyof Lead, label: string) => (
    <label className="flex min-w-0 flex-col gap-0.5 text-xs text-slate-400">{label}
      <input value={draft[k]} onChange={(e) => set(k, e.target.value)} inputMode="numeric" aria-label={`${label} in minutes`} aria-invalid={bad(k)}
             className={`w-full min-w-0 rounded border bg-navy-deep p-1 text-sm tabular-nums text-slate-100 focus:outline-none ${bad(k) ? 'border-danger-red' : 'border-accent-cyan/30 focus:border-accent-cyan'}`} />
    </label>
  );
  const rows = (data?.zones ?? []).filter((z) => z.status === 'counting' || z.status === 'passed').slice(0, limit);
  return (
    <section className="rounded-lg border border-warning-orange/30 bg-navy-panel p-4" aria-label="Last call">
      <h2 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-white">
        <Hourglass className="h-4 w-4 text-warning-orange" /> Last call
        <span className="ml-auto text-[11px] font-normal normal-case text-slate-500">latest a dispatch could still set out</span>
      </h2>
      <div className="mt-2 grid grid-cols-3 gap-2">
        {field('reply', 'Reply wait')}{field('decision', 'Decision')}{field('travel', 'Travel')}
      </div>
      <p className="mt-1 text-xs text-slate-400">
        Lead time <b className="text-slate-200">{totalLead(lead)} min</b>, set by you, not measured.{' '}
        {totalLead(lead) === 0 && 'With none set, last call is the cut-off time itself.'}
      </p>

      {error ? <p className="mt-2 text-sm text-danger-red">{error}</p>
        : !data ? <p className="mt-2 text-sm text-slate-500">loading…</p>
        : !data.available ? <p className="mt-2 rounded border border-white/10 p-2 text-sm text-slate-400">{data.reason}</p>
        : (
          <>
            <p className="mt-2 text-sm text-slate-300">
              <b className="tabular-nums text-warning-orange">{data.counts.counting}</b> counting down · <b className="tabular-nums text-danger-red">{data.counts.passed}</b> past last call ·{' '}
              <b className="tabular-nums text-slate-100">{data.counts.cut_off}</b> cut off · <b className="tabular-nums text-sky-200">{data.counts.reconnected}</b> reconnected
            </p>
            {rows.length === 0 ? <p className="mt-2 text-sm text-slate-500">No zone is counting down at this time.</p> : (
              <ol className="mt-2 space-y-1" aria-label="Soonest last call first">
                {rows.map((z) => (
                  <li key={z.zone_id}>
                    <button type="button" onClick={() => onSelect(z.zone_id)} aria-current={selectedZoneId === z.zone_id}
                            className={`flex w-full min-w-0 cursor-pointer items-center justify-between gap-2 rounded border px-2 py-1.5 text-left transition hover:border-accent-cyan/50 ${selectedZoneId === z.zone_id ? 'border-accent-cyan bg-cyan-950/40' : 'border-white/10 bg-navy-deep/60'}`}>
                      <span className="min-w-0 flex-1 truncate text-sm text-slate-200" title={z.zone_name}><Mono>{z.zone_name.replace(/^USGS-\d+ /, '')}</Mono>{z.was_reconnected && <span className="ml-1 text-xs text-sky-300">(reconnected, cut off again)</span>}</span>
                      <span className="shrink-0 text-right"><Countdown z={z} /></span>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      <p className="mt-2 text-[11px] leading-snug text-slate-500">
        Replay: the engine's recorded cut-off times are known in hindsight and stand in for a forecast; a live system needs a river forecast. Per zone, not per household.
        "Cut off" means no dry road route out: roads reopen, and it says nothing about phones or other ways to reach people.
      </p>
    </section>
  );
}
