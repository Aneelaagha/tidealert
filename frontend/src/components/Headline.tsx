// The plain-language headline under the page: what the run says right now, from the API's own numbers. Replaces the
// scrolling event ticker. Every number is a count of stored rows as of the slider time; nothing is estimated.

import { Siren } from 'lucide-react';
import type { Case, Run, Task, ZonesResponse } from '../lib/api';
import { fmtTime } from '../lib/format';

/** Zones whose active tasks say the zone is cut off, of the zones with Cases, as of the slider time. */
export function headlineFacts(zones: ZonesResponse | null, cases: Case[] | null, tasks: Task[] | null) {
  if (!zones || !cases || !tasks) return null;
  const flagged = zones.features.filter((f) => f.properties.case_count > 0).length;
  const cutOff = new Set(cases.filter((c) => c.tasks.some((t) => t.active && t.safety?.zone_access === 'isolated')).map((c) => c.zone_id)).size;
  // A zone is "assessed" when one of its active tasks carries an access state from the isolation engine. Where the
  // engine never ran (the synthetic scenarios), "0 cut off" would read as "not cut off", so those are counted apart.
  const assessedZones = new Set(cases.filter((c) => c.tasks.some((t) => t.active && t.safety && t.safety.zone_access !== 'not_evaluated')).map((c) => c.zone_id));
  const notAssessed = Math.max(flagged - assessedZones.size, 0);
  const assigned = new Set(tasks.filter((t) => t.active && t.assigned_responder_id).map((t) => t.assigned_responder_id)).size;
  return { flagged, cutOff, notAssessed, assigned, at: zones.at };
}

/** How the run describes itself, in plain words. */
export function runPhrase(run: Run): string {
  if (run.mode === 'replay') return run.event ? `replay of ${run.event}` : 'replay of recorded data';
  if (run.mode === 'mixed') return `mixed scenario: real ${run.event ?? 'recorded'} flood, synthetic responders`;
  if (run.mode === 'scenario') return 'synthetic scenario, not a real event';
  if (run.mode === 'live') return 'live run';
  return run.mode;
}

export function Headline({ run, zones, cases, tasks }: { run: Run | null; zones: ZonesResponse | null; cases: Case[] | null; tasks: Task[] | null }) {
  const f = run ? headlineFacts(zones, cases, tasks) : null;
  return (
    <div className="flex min-h-[2.5rem] flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-accent-cyan/20 bg-navy-panel px-4 py-2 text-sm text-slate-200" aria-live="polite">
      <Siren className="h-4 w-4 shrink-0 text-accent-cyan" />
      {!run || !f ? <span className="text-slate-500">loading the situation…</span> : (
        <>
          <b className={f.cutOff > 0 ? 'text-danger-red' : 'text-white'}>
            {f.flagged === 0 ? 'No zones flagged'
              : f.notAssessed === f.flagged ? `${f.flagged.toLocaleString()} flagged ${f.flagged === 1 ? 'zone' : 'zones'}, cut-off status not assessed`
              : `${f.cutOff.toLocaleString()} of ${f.flagged.toLocaleString()} flagged ${f.flagged === 1 ? 'zone' : 'zones'} cut off`}
          </b>
          {f.notAssessed > 0 && f.notAssessed < f.flagged && <span className="text-slate-400">({f.notAssessed.toLocaleString()} not assessed)</span>}
          <span className="text-slate-500">·</span>
          <span>{f.assigned === 0 ? '0 responders assigned' : `${f.assigned} ${f.assigned === 1 ? 'responder' : 'responders'} assigned`}</span>
          <span className="text-slate-500">·</span>
          <span>{runPhrase(run)}</span>
          <span className="text-slate-500">·</span>
          <span className="text-slate-400">as of <span className="font-mono">{fmtTime(f.at)}</span></span>
        </>
      )}
    </div>
  );
}
