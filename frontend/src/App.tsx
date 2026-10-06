// TideAlert: one run at a time, read as of a time on the run's clock. Everything shown comes from the API
// (src/lib/api.ts); the run and time are kept in the URL.

import { Map as MapIcon, UserRound } from 'lucide-react';
import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { AlertsPanel } from './components/AlertsPanel';
import { CopilotPanel } from './components/CopilotPanel';
import { DonationPortal } from './components/DonationPortal';
import { EthicsPanel } from './components/EthicsPanel';
import { Headline } from './components/Headline';
import { FreshnessBanner } from './components/FreshnessBanner';
import { ConnectionBanner } from './components/ConnectionBanner';
import { Header } from './components/Header';
import { Legend } from './components/Legend';
import { type Layer, MapToolbar } from './components/MapToolbar';
import { RespondersPanel } from './components/RespondersPanel';
import { ZoneMap } from './components/ZoneMap';
import { ZonePanel } from './components/ZonePanel';
import { api, type Case, type Freshness, type Needs, type Responder, type Run, type SupplyAccess, type Task, type Vocabulary, type ZonesResponse } from './lib/api';
import { cacheKeepView, dispatch, getConnection, startConnectionWatch } from './lib/connection';
import { useConnection } from './lib/useConnection';
import { fmtTime } from './lib/format';
import { readUrl, tickIndex, ticksFor, writeUrl } from './lib/time';

function Panel({ title, children, className = '' }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`flex min-h-0 flex-col rounded-lg border border-accent-cyan/25 bg-navy-panel p-4 ${className}`}>
      <h2 className="mb-2 border-b border-navy-line pb-2 text-xs font-bold uppercase tracking-wider text-white">{title}</h2>
      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto pr-1">{children}</div>
    </section>
  );
}

const OPERATOR_KEY = 'tidealert.operator';

function storedOperator(): string {
  try { return window.localStorage.getItem(OPERATOR_KEY) ?? ''; } catch { return ''; }
}

/** What the bar says, in plain words: why a replay can't be changed and where to go to try, or what a name is for. */
export function operatorMessage(run: Run, mixed: Run | null): { text: string; why: string | null } {
  if (!run.task_actions_blocked) {
    return { text: 'Your name is stamped, with the slider time, on anything you assign, complete or enter here. There is no login.', why: null };
  }
  const what = run.event ? `a replay of ${run.event}` : 'a replay of recorded data';
  return {
    text: `This is ${what}, so you can look but not change anything. ${mixed ? `To try assigning responders, use the mixed scenario: the real ${run.event ?? 'recorded'} flood with synthetic responders.` : ''}`.trim(),
    why: run.task_actions_blocked,
  };
}

function OperatorBar({ run, runs, operator, onOperator, onRun }: { run: Run; runs: Run[]; operator: string; onOperator: (v: string) => void; onRun: (id: string) => void }) {
  const mixed = run.task_actions_blocked ? runs.find((r) => r.mode === 'mixed' && r.event === run.event && r.event != null) ?? null : null;
  const m = operatorMessage(run, mixed);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-accent-cyan/20 bg-navy-panel px-4 py-2.5 text-sm text-slate-300">
      <label className="flex items-center gap-2">
        <UserRound className="h-4 w-4 text-accent-cyan" /> <span className="text-xs uppercase tracking-wider text-slate-400">Operator</span>
        <input value={operator} onChange={(e) => onOperator(e.target.value)} placeholder="your name"
               className="w-40 rounded border border-navy-line bg-navy-deep p-1 text-slate-100 placeholder-slate-600 focus:border-accent-cyan/60 focus:outline-none" />
      </label>
      <span className="order-last w-full leading-relaxed" title={m.why ?? undefined}>{m.text}</span>
      {mixed && (
        <button type="button" onClick={() => onRun(mixed.id)}
                className="cursor-pointer rounded border border-teal-300/50 bg-teal-950/40 px-3 py-1 text-xs font-bold uppercase text-teal-200 hover:bg-teal-900/50">
          Switch to the mixed scenario
        </button>
      )}
    </div>
  );
}

function summary(zones: ZonesResponse, seconds: number | null): string {
  const f = zones.features.map((x) => x.properties);
  const withTask = f.filter((z) => z.task_count > 0);
  const sum = (k: 'task_count' | 'task_awaiting' | 'task_flagged') => withTask.reduce((n, z) => n + z[k], 0);
  // Counted per task, not per zone: a zone's marker shows only its most advanced task.
  return `${f.length.toLocaleString()} zones · ${f.filter((z) => z.case_count > 0).length} with Cases · `
    + `${sum('task_count')} active tasks in ${withTask.length} zones (${sum('task_awaiting')} awaiting assignment, `
    + `${sum('task_flagged')} flagged verify) · ${f.filter((z) => z.coverage_gap_active).length.toLocaleString()} `
    + `with an active coverage gap · ${seconds === null ? 'cached' : `${seconds.toFixed(1)} s`}`;
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
  const [portalOpen, setPortalOpen] = useState(false);
  const [layer, setLayer] = useState<Layer>('risk'); // what the zone fill shows
  const [supply, setSupply] = useState<SupplyAccess | null>(null);
  const [supplyError, setSupplyError] = useState<string | null>(null);
  const [needs, setNeeds] = useState<Needs | null>(null);
  const [needsError, setNeedsError] = useState<string | null>(null);
  const [version, setVersion] = useState(0); // bumped after a task action: everything is read again
  const [status, setStatus] = useState('loading runs…');
  const [error, setError] = useState<string | null>(null);

  const conn = useConnection();

  useEffect(() => startConnectionWatch(), []);

  // The server is back: read the view again, so nothing stale stays on screen.
  useEffect(() => { if (conn.recoveredAt) setVersion((v) => v + 1); }, [conn.recoveredAt]);

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
  const closePortal = useCallback(() => setPortalOpen(false), []);

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
    cacheKeepView(run.id, at); // one view is cached: the one on screen
    setStatus('loading…');
    setError(null);
    setFreshness(null);
    Promise.all([api.zones(run.id, at, ctl.signal), api.freshness(run.id, at, ctl.signal)])
      .then(([z, f]) => {
        setZones(z);
        setFreshness(f);
        // Only a load that came from the server counts as the view's load time (a cached reply arrives offline).
        const fromServer = getConnection().state === 'online';
        if (fromServer) dispatch({ type: 'view_loaded', at: Date.now() });
        setStatus(summary(z, fromServer ? (performance.now() - t0) / 1000 : null));
      })
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    api.tasks(run.id, at, ctl.signal).then((b) => setTasks(b.tasks))
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    api.cases(run.id, null, at, ctl.signal).then((b) => setCases(b.cases))
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    return () => ctl.abort();
  }, [run, at, version]);

  // Supply access is read only when something shows it (the layer, or a selected zone's panel): it is a second
  // answer for the same run and time, kept apart from the zones so that response does not grow.
  const wantSupply = layer === 'supply' || selectedZoneId != null;
  useEffect(() => { setSupply(null); }, [run?.id]);
  useEffect(() => {
    if (!run || !wantSupply) return;
    const ctl = new AbortController();
    setSupplyError(null);
    api.supplyAccess(run.id, at, ctl.signal).then(setSupply)
      .catch((e: Error) => { if (e.name !== 'AbortError') setSupplyError(e.message); });
    return () => ctl.abort();
  }, [run, at, wantSupply, version]);

  // The operator-entered needs board for this run and time: read again after an entry (version) and with each time.
  useEffect(() => { setNeeds(null); }, [run?.id]);
  useEffect(() => {
    if (!run) return;
    const ctl = new AbortController();
    setNeedsError(null);
    api.needs(run.id, at, ctl.signal).then(setNeeds)
      .catch((e: Error) => { if (e.name !== 'AbortError') setNeedsError(e.message); });
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
      <ConnectionBanner conn={conn} />
      {portalOpen && run && <DonationPortal run={run} needs={needs} needsError={needsError} operator={operator} at={zones?.at ?? at}
                                           onChanged={() => setVersion((v) => v + 1)} onClose={closePortal} />}
      {run && <FreshnessBanner run={run} freshness={freshness} conn={conn} />}

      <main className="mx-auto mt-4 grid w-full max-w-7xl flex-1 grid-cols-1 gap-6 px-6 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-2">
        <section className="flex flex-col overflow-hidden rounded-lg border border-accent-cyan/20 bg-navy-panel">
          <MapToolbar run={run} layer={layer} onLayer={setLayer} supply={supply} supplyError={supplyError} needs={needs}
                      needsError={needsError} onSelectZone={(id) => { setSelectedZoneId(id); setSelectedCaseId(null); }}
                      onPortal={() => setPortalOpen(true)} />
          <div className="h-[560px]">
            <ZoneMap run={run} zones={zones} selectedZoneId={selectedZoneId} layer={layer} supply={supply}
                     onSelectZone={(id) => { setSelectedZoneId(id); setSelectedCaseId(null); }} />
          </div>
          {/* The zones summary, under the map. One line that scrolls sideways rather than wrapping, its thin scrollbar
              always taking its space: when "loading…" becomes the summary the bar must not grow and push the page down. */}
          <div className="custom-scrollbar flex items-center gap-2 overflow-x-scroll whitespace-nowrap border-t border-accent-cyan/15 bg-navy-deep px-3 py-1.5 text-xs tracking-wider text-slate-400">
            <MapIcon className="h-3.5 w-3.5 shrink-0 text-accent-cyan" />
            {error ? <span className="text-danger-red">{error}{conn.state !== 'online' && zones ? ` The map and panels still show the view as of ${fmtTime(zones.at)}.` : ''}</span> : <span>{status}</span>}
          </div>
        </section>
        {run && (
          <>
            <OperatorBar run={run} runs={runs} operator={operator} onOperator={changeOperator}
                         onRun={(id) => { const r = runs.find((x) => x.id === id); if (r) chooseRun(r, zones?.at ?? at); }} />
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
            {run ? <ZonePanel run={run} at={zones?.at ?? at} zone={zone} gapReasons={zones?.gap_reasons ?? []}
                              responders={responders} version={version} supply={supply} supplyError={supplyError}
                              needs={needs} needsError={needsError} operator={operator} onNeedsChanged={() => setVersion((v) => v + 1)} />
              : <p className="text-slate-500">loading…</p>}
          </Panel>
          <Panel title="Legend" className="max-h-[300px]">
            {vocabulary ? <Legend vocabulary={vocabulary} supply={supply} /> : <p className="text-slate-500">loading…</p>}
          </Panel>
        </div>
      </main>

      <footer className="mx-auto mt-6 w-full max-w-7xl select-none px-6">
        <Headline run={run} zones={zones} cases={cases} tasks={tasks} />
      </footer>
    </div>
  );
}
