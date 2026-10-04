// A task's zone access and warnings (from the server's `safety` block). Warnings are shown as given; the states
// without a warning are still stated, so "not assessed" never reads as safe.

import { ShieldAlert } from 'lucide-react';
import type { Safety } from '../lib/api';
import { fmtTime } from '../lib/format';
import { Tag } from './ui';

/** The engine's reason without its confidence arithmetic (the evidence list shows it) or a leading state word
 *  the sentence already says ("reconnected: …"). */
const shortReason = (r: string) => r.split('; confidence')[0].replace(/^(reconnected|stranded|submerged):\s*/, '');

/** The short badge for a task's zone access, or null when there's nothing to flag. */
export function safetyLabel(s: Safety | undefined): { text: string; tone: 'red' | 'amber' | 'plain' } | null {
  if (!s) return null;
  if (s.warnings.some((w) => w.code === 'isolated_after_assignment')) return { text: 'CUT OFF AFTER ASSIGNMENT', tone: 'red' };
  if (s.zone_access === 'isolated') return { text: 'ZONE CUT OFF', tone: 'red' };
  if (s.zone_access === 'possibly_isolated') return { text: 'MAY BE CUT OFF', tone: 'amber' };
  if (s.zone_access === 'not_evaluated') return { text: 'ACCESS NOT ASSESSED', tone: 'plain' };
  return null;
}

export function safetyTag(s: Safety | undefined) {
  const l = safetyLabel(s);
  return l && <Tag tone={l.tone}>{l.text}</Tag>;
}

export function SafetyNote({ safety }: { safety: Safety | undefined }) {
  if (!safety) return null;
  return (
    <div className="mt-1.5 space-y-1 text-[10.5px]">
      {safety.warnings.map((w, i) => (
        <div key={i} className={`flex gap-1.5 rounded border p-1.5 ${w.severity === 'high'
          ? 'border-danger-red/40 bg-red-950/30 text-red-200' : 'border-warning-orange/40 bg-orange-950/20 text-orange-200'}`}>
          <ShieldAlert className="mt-px h-3.5 w-3.5 shrink-0" /> <span>{w.text}</span>
        </div>
      ))}
      {safety.zone_access === 'reconnected' && (
        <p className="text-slate-400">Zone reconnected at {fmtTime(safety.since)}: {shortReason(safety.reason)}. This is the
          optimistic bound (roads of unknown flooding taken as passable), not a guarantee of a dry route.</p>
      )}
      {safety.zone_access === 'not_evaluated' && (
        <p className="text-slate-400">Isolation not assessed for this zone ({shortReason(safety.reason)}): this is not a sign it's safe.</p>
      )}
      {safety.zone_access === 'reachable' && <p className="text-slate-500">Reachable: {safety.reason}.</p>}
      {safety.zone_access === 'isolated' && safety.reason && (
        <p className="text-slate-500">Engine: {safety.reason.split('; confidence')[0]}.</p>
      )}
      {safety.assignment_note && <p className="text-slate-500">{safety.assignment_note}.</p>}
    </div>
  );
}
