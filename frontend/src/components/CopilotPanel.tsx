// The copilot: questions about this run as of the slider time, answered by /copilot/ask from the database only.
// Each answer shows how it was made (MODEL or TEMPLATE, and why), what it couldn't assess, and whether real
// household data was involved. The log is display only: the backend answers every question on its own.

import { CornerDownLeft, Cpu, Info, Terminal } from 'lucide-react';
import { type FormEvent, useEffect, useRef, useState } from 'react';
import { ApiError, api, type CopilotAnswer, type CopilotStatus, type Run } from '../lib/api';
import { OfflineError } from '../lib/connection';
import { answerLabels, intentAvailability } from '../lib/copilot';
import { label } from '../lib/format';
import { Tag, Time } from './ui';

interface Entry {
  id: number;
  asked: string; // the question, or the intent button's label
  answer?: CopilotAnswer;
  notice?: string; // a 422: the copilot can't answer yet (a selection is missing, or the time is outside the run)
  error?: string; // anything else: a real failure, shown with its HTTP status
}

interface Props {
  run: Run;
  at: string | null;
  zoneId: string | null;
  zoneName: string | null;
  caseId: string | null;
  caseWord: string | null;
}

function AnswerCard({ a, statusMode }: { a: CopilotAnswer; statusMode: string }) {
  const l = answerLabels(a, statusMode);
  return (
    <div className="max-w-[95%] rounded-md border border-white/5 bg-navy-deep/65 p-2.5 text-xs leading-relaxed text-slate-200">
      <div className="mb-1.5 flex flex-wrap items-center gap-1">
        <Tag tone={a.mode === 'model' ? 'cyan' : 'plain'}>{l.badge}</Tag>
        {l.outOfScope && <Tag tone="amber">OUT OF SCOPE</Tag>}
        {a.intent && <Tag>{label(a.intent)}</Tag>}
        {l.servedBy && <span className="text-xs text-slate-500">served by {l.servedBy}</span>}
        {l.rewritten && <span className="text-xs text-slate-500">· first draft rejected by the check; rewritten</span>}
      </div>
      <p className="mb-1.5 text-xs text-slate-500">{l.fellBack ? 'Fell back to templates: ' : ''}{l.reason}</p>
      <div className="whitespace-pre-line font-sans text-[13px]">{a.answer}</div>
      {l.unknowns.length > 0 && (
        <p className="mt-1.5 text-xs text-slate-400">Not assessed or missing: {l.unknowns.join(', ')}</p>
      )}
      {l.households && (
        <p className="mt-1 text-xs text-slate-400">
          Built from {l.households.households} household(s), {l.households.real} real
          {l.households.real > 0 ? ': real household data is never sent to an external model.' : ' (all synthetic).'}
        </p>
      )}
      {l.retryAfter != null && (
        <p className="mt-1 text-xs text-warning-orange">Model questions are rate limited: available again in about {l.retryAfter} s.</p>
      )}
    </div>
  );
}

export function CopilotPanel({ run, at, zoneId, zoneName, caseId, caseWord }: Props) {
  const [status, setStatus] = useState<CopilotStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState(false); // how the copilot works: behind the info icon, not on the page
  const nextId = useRef(1);
  const log = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ctl = new AbortController();
    api.copilotStatus(ctl.signal).then(setStatus)
      .catch((e: Error) => { if (e.name !== 'AbortError') setStatusError(e.message); });
    return () => ctl.abort();
  }, []);

  // Keep the newest answer in view by scrolling the log itself (scrollIntoView would also scroll the page).
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [entries]);

  async function ask(asked: string, question: string, intent: string | null) {
    const id = nextId.current++;
    setEntries((xs) => [...xs, { id, asked }]);
    setBusy(true);
    try {
      const answer = await api.ask({ run_id: run.id, question, intent, at: run.mode === 'live' ? null : at,
                                     zone_id: zoneId, case_id: caseId });
      setEntries((xs) => xs.map((x) => (x.id === id ? { ...x, answer } : x)));
    } catch (e) {
      const update = e instanceof ApiError && e.status === 422 ? { notice: e.detail }
        : { error: e instanceof ApiError ? `HTTP ${e.status}: ${e.detail}` : e instanceof OfflineError ? e.message : String(e) };
      setEntries((xs) => xs.map((x) => (x.id === id ? { ...x, ...update } : x)));
    } finally {
      setBusy(false);
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    setText('');
    void ask(q, q, null);
  };

  const intents = status ? Object.entries(status.intents) : [];
  // Disabled buttons grouped by what they're missing, e.g. "zone status, zone cases, briefing: needs a zone: …".
  const missing = new Map<string, string[]>();
  for (const [k] of intents) {
    const a = status ? intentAvailability(k, status.needs, zoneId, caseId) : null;
    if (a && !a.ok && a.reason) missing.set(a.reason, [...(missing.get(a.reason) ?? []), label(k)]);
  }

  return (
    <section className="flex h-[560px] flex-col rounded-lg border border-accent-cyan/25 bg-navy-panel p-4 ">
      <div className="flex items-start justify-between gap-2 border-b border-navy-line pb-2.5">
        <div>
          <h2 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-white">
            <Terminal className="h-4 w-4 text-accent-cyan" /> Copilot
            {status && (
              <span className={`rounded border px-1.5 py-0.5 text-[11px] font-bold ${status.mode === 'model'
                ? 'border-accent-cyan/30 bg-accent-cyan/10 text-accent-cyan' : 'border-white/15 bg-white/5 text-slate-300'}`}>
                {status.mode.toUpperCase()} MODE
              </span>
            )}
          </h2>
          {statusError && <p className="mt-1 text-xs text-danger-red">{statusError}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button type="button" onClick={() => setInfo((v) => !v)} aria-expanded={info} aria-label="How the copilot works" title="How the copilot works"
                  className="cursor-pointer rounded p-0.5 text-slate-500 hover:text-accent-cyan">
            <Info className="h-4 w-4" />
          </button>
          <Cpu className={`h-4 w-4 ${busy ? 'animate-spin text-accent-cyan' : 'text-slate-600'}`} />
        </div>
      </div>
      {info && (
        <div className="mt-2 space-y-1 rounded border border-white/10 bg-navy-deep/70 p-2 text-xs text-slate-400">
          <p>{status?.reason ?? 'checking the copilot…'}</p>
          <p>Each question is answered on its own: the copilot doesn't see earlier messages. Answers use only this run's data, as of the slider time.</p>
        </div>
      )}

      <p className="mt-2 text-xs text-slate-400">
        Asking about: {zoneName ? <span className="text-slate-200">{zoneName}</span> : 'no zone selected'}
        {caseId && <> · Case <span className="text-slate-200">{caseWord}</span></>}
        {at && <> · as of <Time t={at} /></>}
      </p>

      <div ref={log} className="custom-scrollbar mt-2 flex-1 space-y-3 overflow-y-auto pr-1">
        {!entries.length && (
          <p className="px-3 pt-2 text-center text-sm leading-relaxed text-slate-500">Pick a question below, or type your own.</p>
        )}
        {entries.map((x) => (
          <div key={x.id} className="space-y-1.5">
            <div className="flex justify-end">
              <div className="max-w-[90%] rounded-md border border-accent-cyan/30 bg-cyan-950/25 p-2 text-xs text-accent-cyan">{x.asked}</div>
            </div>
            {x.answer ? <AnswerCard a={x.answer} statusMode={status?.mode ?? 'template'} />
              : x.notice ? (
                <div className="max-w-[95%] rounded-md border border-warning-orange/30 bg-orange-950/20 p-2 text-xs text-slate-200">
                  <span className="font-bold text-warning-orange">Can't answer yet: </span>{x.notice}
                </div>
              )
              : x.error ? <p className="text-xs text-danger-red">{x.error}</p>
              : <p className="animate-pulse text-xs text-accent-cyan">answering from the database…</p>}
          </div>
        ))}
      </div>

      {status && (
        <div className="mb-2 mt-2">
          <div className="flex flex-wrap gap-1.5">
            {intents.map(([intent, what]) => {
              const avail = intentAvailability(intent, status.needs, zoneId, caseId);
              return (
                <button key={intent} type="button" disabled={!avail.ok || busy} title={avail.reason ?? what}
                        onClick={() => ask(label(intent), '', intent)}
                        className="cursor-pointer rounded-md border border-white/10 bg-navy-deep px-2.5 py-1.5 text-xs font-semibold text-slate-200 transition hover:border-accent-cyan/50 hover:text-accent-cyan disabled:cursor-not-allowed disabled:opacity-40">
                  {label(intent)}
                </button>
              );
            })}
          </div>
          {[...missing].map(([reason, names]) => (
            <p key={reason} className="mt-1.5 text-xs text-slate-500">{names.join(', ')}: {reason}.</p>
          ))}
        </div>
      )}

      <form onSubmit={submit} className="flex overflow-hidden rounded border border-navy-line bg-navy-deep">
        <input value={text} onChange={(e) => setText(e.target.value)} disabled={busy} aria-label="Question"
               placeholder={busy ? 'answering…' : 'Ask about this run, e.g. what is the status of this zone?'}
               className="flex-1 border-none bg-transparent px-3 py-2 text-xs text-slate-100 placeholder-slate-600 outline-none" />
        <button type="submit" disabled={busy || !text.trim()} aria-label="Ask"
                className="flex cursor-pointer items-center border-l border-navy-line bg-cyan-950/60 px-3 text-accent-cyan disabled:cursor-not-allowed disabled:opacity-50">
          <CornerDownLeft className="h-3.5 w-3.5" />
        </button>
      </form>
    </section>
  );
}
