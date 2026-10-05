// Assign and complete for one task. Buttons are greyed out with the reason when the action would certainly be
// refused; otherwise the server decides, and its error (status and detail) is shown exactly as returned.

import { CheckCircle2, Send } from 'lucide-react';
import { useState } from 'react';
import { ApiError, api, type Responder, type Run, type Task } from '../lib/api';
import { OfflineError } from '../lib/connection';
import { fmtTime } from '../lib/format';
import { canAssign, canComplete } from '../lib/taskActions';

interface Props {
  run: Run;
  task: Task;
  operator: string;
  at: string | null; // the slider time: the event is stamped with it
  responders: Responder[];
  onDone: () => void;
}

export function TaskActions({ run, task, operator, at, responders, onDone }: Props) {
  const [responderId, setResponderId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const assign = canAssign(run, task, operator, responders);
  const complete = canComplete(run, task, operator);
  const available = responders.filter((r) => r.status === 'available');

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setResponderId('');
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? `HTTP ${e.status}: ${e.detail}` : e instanceof OfflineError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const acting = { actor: operator.trim(), at: run.mode === 'live' ? null : at };
  const button = 'flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] font-bold uppercase transition disabled:cursor-not-allowed disabled:border-white/5 disabled:bg-navy-deep disabled:text-slate-600';

  return (
    <div className="mt-2 space-y-1.5 border-t border-white/10 pt-2" onClick={(e) => e.stopPropagation()}>
      <div className="flex flex-wrap items-center gap-2">
        <select value={responderId} onChange={(e) => setResponderId(e.target.value)} disabled={!assign.ok || busy}
                aria-label="Responder to assign"
                className="min-w-0 max-w-full rounded border border-accent-cyan/30 bg-navy-deep p-0.5 text-[10px] text-slate-200 focus:border-accent-cyan focus:outline-none disabled:opacity-40">
          <option value="">— available responder —</option>
          {available.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.role})</option>)}
        </select>
        <button disabled={!assign.ok || !responderId || busy} title={assign.reason ?? undefined}
                onClick={() => act(() => api.assign(task.id, responderId, acting))}
                className={`${button} cursor-pointer border-accent-cyan/50 bg-cyan-950/40 text-accent-cyan hover:bg-cyan-900/50`}>
          <Send className="h-3 w-3" /> Assign
        </button>
        <button disabled={!complete.ok || busy} title={complete.reason ?? undefined}
                onClick={() => act(() => api.complete(task.id, acting))}
                className={`${button} cursor-pointer border-safe-green/50 bg-safe-green/10 text-safe-green hover:bg-safe-green/25`}>
          <CheckCircle2 className="h-3 w-3" /> Mark complete
        </button>
        {busy && <span className="text-slate-500">sending…</span>}
      </div>
      {!assign.ok && <p className="text-slate-500">Assign: {assign.reason}</p>}
      {!complete.ok && assign.reason !== complete.reason && <p className="text-slate-500">Complete: {complete.reason}</p>}
      {error && <p className="text-danger-red">{error}</p>}
      {(assign.ok || complete.ok) && at && <p className="text-slate-600">Recorded at the slider time, {fmtTime(at)}.</p>}
    </div>
  );
}
