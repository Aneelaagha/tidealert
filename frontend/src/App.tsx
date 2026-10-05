// TideAlert: one run at a time, read as of a time on the run's clock. Everything shown comes from the API
// (src/lib/api.ts); the run and time are kept in the URL.

import { Map as MapIcon, UserRound } from 'lucide-react';
import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { AlertsPanel } from './components/AlertsPanel';
import { CopilotPanel } from './components/CopilotPanel';
import { EthicsPanel } from './components/EthicsPanel';
import { EventTicker } from './components/EventTicker';
import { FreshnessBanner } from './components/FreshnessBanner';
import { Header } from './components/Header';
import { Legend } from './components/Legend';
import { RespondersPanel } from './components/RespondersPanel';
import { ZoneMap } from './components/ZoneMap';
import { ZonePanel } from './components/ZonePanel';
import { api, type Case, type Freshness, type Responder, type Run, type Task, type Vocabulary, type ZonesResponse } from './lib/api';
import { readUrl, tickIndex, ticksFor, writeUrl } from './lib/time';

function Panel({ title, children, className = '' }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`flex min-h-0 flex-col rounded-lg border border-accent-cyan/25 bg-navy-panel p-4 ${className}`}>
      <h2 className="mb-2 border-b border-navy-line pb-2 font-mono text-xs font-bold uppercase tracking-wider text-white">{title}</h2>
      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto pr-1">{children}</div>
    </section>
  );
}

const OPERATOR_KEY = 'tidealert.operator';

function storedOperator(): string {
  try { return window.localStorage.getItem(OPERATOR_KEY) ?? ''; } catch { return ''; }
}

function OperatorBar({ run, operator, onOperator }: { run: Run; operator: string; onOperator: (v: string) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg border border-accent-cyan/20 bg-navy-panel px-4 py-2 font-mono text-[10.5px] text-slate-400">
      <label className="flex items-center gap-2 uppercase">
        <UserRound className="h-3.5 w-3.5 text-accent-cyan" /> Operator
        <input value={operator} onChange={(e) => onOperator(e.target.value)} placeholder="your name"
               className="w-40 rounded border border-navy-line bg-navy-deep p-1 normal-case text-slate-100 placeholder-slate-600 focus:border-accent-cyan/60 focus:outline-none" />
      </label>
      {run.task_actions_blocked
        ? <span>Task actions are off for this run. Server: <span className="text-slate-300">{run.task_actions_blocked}</span></span>
        : <span>Task actions write to this run's data, stamped with the slider time and your name (there is no login).</span>}
    </div>
  );
}

function summary(zones: ZonesResponse, seconds: number): string {
  const f = zones.features.map((x) => x.properties);
  const withTask = f.filter((z) => z.task_count > 0);
  const sum = (k: 'task_count' | 'task_awaiting' | 'task_flagged') => withTask.reduce((n, z) => n + z[k], 0);
  // Counted per task, not per zone: a zone's marker shows only its most advanced task.
  return `${f.length.toLocaleString()} zones · ${f.filter((z) => z.case_count > 0).length} with Cases · `
    + `${sum('task_count')} active tasks in ${withTask.length} zones (${sum('task_awaiting')} awaiting assignment, `
    + `${sum('task_flagged')} flagged verify) · ${f.filter((z) => z.coverage_gap_active).length.toLocaleString()} `
    + `with an active coverage gap · ${seconds.toFixed(1)} s`;
}

export default function App() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [vocabulary, setVocabulary] = useState<Vocabulary | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [tick, setTick] = useState(0); // the slider position (moves while dragging)
  const [at, setAt] = useState<string | null>(null); // the committed time every request uses
  const [zones, setZones] = useState<ZonesResponse | null>(null);
  const [freshness, setFreshness] = useState<Freshness | null>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [cases, setCases] = useState<Case[] | null>(null);
  const [responderList, setResponderList] = useState<Responder[] | null>(null);
  const [responderError, setResponderError] = useState<string | null>(null);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [operator, setOperator] = useState(storedOperator);
  const [ethicsOpen, setEthicsOpen] = useState(false);
  const [version, setVersion] = useState(0); // bumped after a task action: everything is read again
  const [status, setStatus] = useState('loading runs…');
  const [error, setError] = useState<string | null>(null);

  const ticks = useMemo(() => (run ? ticksFor(run) : []), [run]);

  const chooseRun = useCallback((next: Run, wantAt: string | null) => {
    const t = ticksFor(next), i = tickIndex(t, wantAt);
    setRun(next);
    setTick(i);
    setAt(t.length ? t[i] : null);
    setSelectedZoneId(null);
    setSelectedCaseId(null);
  }, []);

  const closeEthics = useCallback(() => setEthicsOpen(false), []);

  const changeOperator = (v: string) => {
    setOperator(v);
    try { window.localStorage.setItem(OPERATOR_KEY, v); } catch { /* not remembered: still works for this visit */ }
  };

  useEffect(() => {
    api.runs().then((body) => {
      setRuns(body.runs);
      setVocabulary(body.vocabulary);
      if (!body.runs.length) { setStatus('No runs in the database.'); return; }
      const url = readUrl(window.location.search);
      chooseRun(body.runs.find((r) => r.id === url.run) ?? body.runs[0], url.at);
    }).catch((e: Error) => setError(e.message));
  }, [chooseRun]);

  // A different run: nothing from the previous one may stay on screen while the new one loads.
  useEffect(() => {
    setCases(null);
    setTasks(null);
    setResponderList(null);
  }, [run?.id]);

  // Responders: the panel, the assign choices, and names in task histories.
  useEffect(() => {
    if (!run) return;
    const ctl = new AbortController();
    setResponderError(null);
    api.responders(run, ctl.signal).then((b) => setResponderList(b.responders))
      .catch((e: Error) => { if (e.name !== 'AbortError') setResponderError(e.message); });
    return () => ctl.abort();
  }, [run, version]);
  const responders = useMemo(() => new Map((responderList ?? []).map((r) => [r.id, r])), [responderList]);

  // Everything time-dependent, refetched for each committed time.
  useEffect(() => {
    if (!run) return;
    window.history.replaceState(null, '', writeUrl(run.id, at));
    const ctl = new AbortController(), t0 = performance.now();
    setStatus('loading…');
    setError(null);
    setFreshness(null);
    Promise.all([api.zones(run.id, at, ctl.signal), api.freshness(run.id, at, ctl.signal)])
      .then(([z, f]) => {
        setZones(z);
        setFreshness(f);
        setStatus(summary(z, (performance.now() - t0) / 1000));
      })
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    api.tasks(run.id, at, ctl.signal).then((b) => setTasks(b.tasks))
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    api.cases(run.id, null, at, ctl.signal).then((b) => setCases(b.cases))
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    return () => ctl.abort();
  }, [run, at, version]);

  const zoneNames = useMemo(() => new Map((zones?.features ?? []).map((f) => [f.properties.zone_id, f.properties.name])), [zones]);

  const zone = selectedZoneId && zones?.run_id === run?.id
    ? zones?.features.find((f) => f.properties.zone_id === selectedZoneId)?.properties ?? null : null;

  return (
    <div className="flex min-h-screen flex-col pb-6 antialiased selection:bg-cyan-950 selection:text-white">
      <Header runs={runs} run={run} onRun={(id) => { const r = runs.find((x) => x.id === id); if (r) chooseRun(r, null); }}
              ticks={ticks} tick={tick} onTickInput={setTick} onTickCommit={() => setAt(ticks.length ? ticks[tick] : null)}
              onEthics={() => setEthicsOpen(true)} />
      {ethicsOpen && <EthicsPanel run={run} freshness={freshness} vocabulary={vocabulary} onClose={closeEthics} />}
      {run && <FreshnessBanner run={run} freshness={freshness} />}

      <main className="mx-auto mt-4 grid w-full max-w-7xl flex-1 grid-cols-1 gap-6 px-6 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-2">
        <section className="flex flex-col overflow-hidden rounded-lg border border-accent-cyan/20 bg-navy-panel">
          {/* One line that scrolls sideways rather than wrapping, its thin scrollbar always taking its space: when
              "loading…" becomes the summary the bar must not grow and push the page down. */}
          <div className="custom-scrollbar flex items-center gap-2 overflow-x-scroll whitespace-nowrap border-b border-accent-cyan/15 bg-navy-deep px-3 py-1.5 font-mono text-[10px] tracking-wider text-slate-400">
            <MapIcon className="h-3.5 w-3.5 shrink-0 text-accent-cyan" />
            {error ? <span className="text-danger-red">{error}</span> : <span>{status}</span>}
          </div>
          <div className="h-[560px]">
            <ZoneMap run={run} zones={zones} selectedZoneId={selectedZoneId}
                     onSelectZone={(id) => { setSelectedZoneId(id); setSelectedCaseId(null); }} />
          </div>
        </section>
        {run && (
          <>
            <OperatorBar run={run} operator={operator} onOperator={changeOperator} />
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <AlertsPanel run={run} at={zones?.at ?? at} cases={cases} error={null} zoneNames={zoneNames}
                           selectedCaseId={selectedCaseId}
                           onSelectCase={(c) => { setSelectedCaseId(c?.id ?? null); if (c) setSelectedZoneId(c.zone_id); }}
                           operator={operator} responders={responderList ?? []} onActed={() => setVersion((v) => v + 1)} />
              <RespondersPanel run={run} responders={responderList} tasks={tasks} error={responderError} />
            </div>
          </>
        )}
        </div>

        <div className="flex flex-col gap-6">
          {run && (
            <CopilotPanel key={run.id} run={run} at={zones?.at ?? at} zoneId={zone ? selectedZoneId : null}
                          zoneName={zone?.name ?? null} caseId={selectedCaseId}
                          caseWord={cases?.find((c) => c.id === selectedCaseId)?.confidence_word ?? null} />
          )}
          <Panel title="Zone" className="h-[420px]">
            {run ? <ZonePanel runId={run.id} at={zones?.at ?? at} zone={zone} gapReasons={zones?.gap_reasons ?? []}
                              responders={responders} version={version} />
              : <p className="text-slate-500">loading…</p>}
          </Panel>
          <Panel title="Legend" className="max-h-[300px]">
            {vocabulary ? <Legend vocabulary={vocabulary} /> : <p className="text-slate-500">loading…</p>}
          </Panel>
        </div>
      </main>

      <footer className="mx-auto mt-6 w-full max-w-7xl select-none px-6">
        <EventTicker tasks={tasks} error={null} />
      </footer>
    </div>
  );
}
