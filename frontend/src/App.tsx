// TideAlert: one run at a time, read as of a time on the run's clock. Everything shown comes from the API
// (src/lib/api.ts); the run and time are kept in the URL.

import { Map as MapIcon } from 'lucide-react';
import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { EventTicker } from './components/EventTicker';
import { FreshnessBanner } from './components/FreshnessBanner';
import { Header } from './components/Header';
import { Legend } from './components/Legend';
import { ZoneMap } from './components/ZoneMap';
import { ZonePanel } from './components/ZonePanel';
import { api, type Freshness, type Responder, type Run, type Task, type Vocabulary, type ZonesResponse } from './lib/api';
import { readUrl, tickIndex, ticksFor, writeUrl } from './lib/time';

function Panel({ title, children, className = '' }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`flex min-h-0 flex-col rounded-lg border border-accent-cyan/25 bg-navy-panel p-4 ${className}`}>
      <h2 className="mb-2 border-b border-navy-line pb-2 font-mono text-xs font-bold uppercase tracking-wider text-white">{title}</h2>
      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto pr-1">{children}</div>
    </section>
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
  const [responders, setResponders] = useState<Map<string, Responder>>(new Map());
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [status, setStatus] = useState('loading runs…');
  const [error, setError] = useState<string | null>(null);

  const ticks = useMemo(() => (run ? ticksFor(run) : []), [run]);

  const chooseRun = useCallback((next: Run, wantAt: string | null) => {
    const t = ticksFor(next), i = tickIndex(t, wantAt);
    setRun(next);
    setTick(i);
    setAt(t.length ? t[i] : null);
    setSelectedZoneId(null);
  }, []);

  useEffect(() => {
    api.runs().then((body) => {
      setRuns(body.runs);
      setVocabulary(body.vocabulary);
      if (!body.runs.length) { setStatus('No runs in the database.'); return; }
      const url = readUrl(window.location.search);
      chooseRun(body.runs.find((r) => r.id === url.run) ?? body.runs[0], url.at);
    }).catch((e: Error) => setError(e.message));
  }, [chooseRun]);

  // Responders, for names in task histories. Names only: ids are shown if this fails.
  useEffect(() => {
    if (!run) return;
    const ctl = new AbortController();
    setResponders(new Map());
    api.responders(run, ctl.signal).then((b) => setResponders(new Map(b.responders.map((r) => [r.id, r])))).catch(() => {});
    return () => ctl.abort();
  }, [run]);

  // Everything time-dependent, refetched for each committed time.
  useEffect(() => {
    if (!run) return;
    window.history.replaceState(null, '', writeUrl(run.id, at));
    const ctl = new AbortController(), t0 = performance.now();
    setStatus('loading…');
    setError(null);
    setTasks(null);
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
    return () => ctl.abort();
  }, [run, at]);

  const zone = selectedZoneId && zones?.run_id === run?.id
    ? zones?.features.find((f) => f.properties.zone_id === selectedZoneId)?.properties ?? null : null;

  return (
    <div className="flex min-h-screen flex-col pb-6 antialiased selection:bg-cyan-950 selection:text-white">
      <Header runs={runs} run={run} onRun={(id) => { const r = runs.find((x) => x.id === id); if (r) chooseRun(r, null); }}
              ticks={ticks} tick={tick} onTickInput={setTick} onTickCommit={() => setAt(ticks.length ? ticks[tick] : null)} />
      {run && <FreshnessBanner run={run} freshness={freshness} />}

      <main className="mx-auto mt-4 grid w-full max-w-7xl flex-1 grid-cols-1 gap-6 px-6 lg:grid-cols-3">
        <section className="flex flex-col overflow-hidden rounded-lg border border-accent-cyan/20 bg-navy-panel lg:col-span-2">
          <div className="flex items-center gap-2 border-b border-accent-cyan/15 bg-navy-deep px-3 py-1.5 font-mono text-[10px] tracking-wider text-slate-400">
            <MapIcon className="h-3.5 w-3.5 shrink-0 text-accent-cyan" />
            {error ? <span className="text-danger-red">{error}</span> : <span>{status}</span>}
          </div>
          <div className="h-[560px]">
            <ZoneMap run={run} zones={zones} selectedZoneId={selectedZoneId} onSelectZone={setSelectedZoneId} />
          </div>
        </section>

        <div className="flex flex-col gap-6 lg:max-h-[600px]">
          <Panel title="Zone" className="min-h-[260px] flex-1">
            {run ? <ZonePanel runId={run.id} at={zones?.at ?? at} zone={zone} gapReasons={zones?.gap_reasons ?? []}
                              responders={responders} />
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
