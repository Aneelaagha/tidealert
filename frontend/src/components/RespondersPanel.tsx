// Responders who can serve the run (/responders) and the active tasks assigned to each as of the slider time
// (/tasks). A responder's status is its current one: the database keeps no history of it.

import { Users } from 'lucide-react';
import type { Responder, Run, Task } from '../lib/api';
import { fmtTime, label } from '../lib/format';
import { SafetyNote, safetyTag } from './SafetyNote';
import { Muted, Tag } from './ui';

const STATUS_TONE: Record<string, 'cyan' | 'green' | 'plain'> = { available: 'green', assigned: 'cyan', off_duty: 'plain' };

interface Props {
  run: Run;
  responders: Responder[] | null;
  tasks: Task[] | null;
  error: string | null;
}

export function RespondersPanel({ run, responders, tasks, error }: Props) {
  const assigned = (id: string) => (tasks ?? []).filter((t) => t.active && t.assigned_responder_id === id);

  return (
    <section className="flex h-[420px] flex-col rounded-lg border border-accent-cyan/25 bg-navy-panel p-4 font-mono">
      <h2 className="flex items-center gap-2 border-b border-navy-line pb-2.5 text-xs font-bold uppercase tracking-wider text-white">
        <Users className="h-4 w-4 text-accent-cyan" /> Responders
        {responders && <span className="text-[10px] text-accent-cyan">({responders.length})</span>}
      </h2>
      <div className="custom-scrollbar mt-2 flex-1 space-y-1.5 overflow-y-auto pr-1 text-[11px]">
        {error ? <p className="text-danger-red">{error}</p>
          : !responders ? <p className="text-slate-500">loading responders…</p>
          : !responders.length ? (
            <p className="py-6 text-center text-slate-500">
              No responders are registered for this run{run.mode === 'replay'
                ? ': a replay records what the engines would have created, not who was dispatched.' : '.'}
            </p>
          ) : responders.map((r) => {
            const mine = assigned(r.id);
            return (
              <div key={r.id} className="rounded border border-white/5 bg-navy-deep/65 p-2 text-slate-300">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-bold text-slate-100">{r.name}{r.synthetic && <Muted> (synthetic)</Muted>}</span>
                  <span>CURRENT STATUS: <Tag tone={STATUS_TONE[r.status] ?? 'plain'}>{label(r.status)}</Tag></span>
                </div>
                <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 border-t border-white/5 pt-1.5 text-[10px] text-slate-400">
                  <div>ROLE: <span className="text-slate-200">{r.role}</span></div>
                  <div>TEAM: <span className="text-slate-200">{r.team_id ?? <Muted>none</Muted>}</span></div>
                  <div>LAST PING: <span className="text-slate-200">{r.last_ping_at ? fmtTime(r.last_ping_at) : <Muted>never</Muted>}</span></div>
                  <div>LOCATION: <Muted>{r.has_location ? 'recorded (not shown yet)' : 'none recorded'}</Muted></div>
                </div>
                <div className="mt-1 text-[10px] text-slate-400">
                  ACTIVE TASKS AT THIS TIME: {mine.length
                    ? mine.map((t) => <span key={t.id}><Tag tone="cyan">{label(t.kind)} · {label(t.status)}</Tag>{safetyTag(t.safety)}</span>)
                    : <Muted>none</Muted>}
                </div>
                {mine.map((t) => <SafetyNote key={t.id} safety={t.safety} />)}
              </div>
            );
          })}
      </div>
    </section>
  );
}
