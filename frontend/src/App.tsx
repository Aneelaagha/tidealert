// TideAlert: one run at a time, read as of a time on the run's clock. Everything shown comes from the API
// (src/lib/api.ts); the run and time are kept in the URL.

import { Map as MapIcon, UserRound } from 'lucide-react';
import { type ReactNode, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertsPanel } from './components/AlertsPanel';
import { CopilotPanel } from './components/CopilotPanel';
import { DonationPortal } from './components/DonationPortal';
import { EthicsPanel } from './components/EthicsPanel';
import { Headline } from './components/Headline';
import { FreshnessBanner } from './components/FreshnessBanner';
import { ConnectionBanner } from './components/ConnectionBanner';
import { GaugesPanel } from './components/GaugesPanel';
import { Header } from './components/Header';
import { ReportPanel } from './components/ReportPanel';
import { ValidationPanel } from './components/ValidationPanel';
import { AttentionList } from './components/AttentionList';
import { Legend } from './components/Legend';
import { MapLegend } from './components/MapLegend';
import { ReliefPanel } from './components/ReliefPanel';
import { AerialPanel } from './components/AerialPanel';
import { LastCallPanel } from './components/LastCallPanel';
import { type Layer, MapToolbar } from './components/MapToolbar';
import { RespondersPanel } from './components/RespondersPanel';
import { ZoneMap } from './components/ZoneMap';
import { ZonePanel } from './components/ZonePanel';
import { api, type Case, type DepotAccess, type AerialPriority, type DepotList, type Freshness, type LastCall, type Needs, type ReliefBoard, type Responder, type Run, type SupplyAccess, type Task, type Vocabulary, type ZonesResponse } from './lib/api';
import { cacheKeepView, devForceOffline, dispatch, getConnection, restoreView, startConnectionWatch } from './lib/connection';
import { useConnection } from './lib/useConnection';
import { fmtTime } from './lib/format';
import { rankAttention } from './lib/attention';
import type { DevHost, TourData } from './dev/DevOverlay';
import type { RawSnapshot } from './dev/conductor';
import type { Scene2Facts } from './dev/scene2';
import { headlineFacts } from './components/Headline';
import { type Lead, loadLead, saveLead } from './lib/lastCall';
import { pulseZone } from './lib/pulse';
import { withNeed } from './lib/relief';
import { readUrl, tickIndex, ticksFor, writeUrl } from './lib/time';

function Panel({ title, children, className = '' }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`flex min-h-0 flex-col rounded-lg border border-accent-cyan/25 bg-navy-panel p-4 ${className}`}>
      <h2 className="mb-2 border-b border-navy-line pb-2 text-xs font-bold uppercase tracking-wider text-white">{title}</h2>
      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto pr-1">{children}</div>
    </section>
  );
}

// DEV ONLY: the demo driver. `import.meta.env.DEV` is a literal false in a production build, so this import is dead code there and
// the driver is not in the bundle. In a dev build it also needs ?dev=1 in the URL. No user-facing route can switch it on.
const DevOverlay = import.meta.env.DEV ? lazy(() => import('./dev/DevOverlay')) : null;
// ?demo=1: the Full Demo (the guided tour, then Scene 2, as one live sequence). A third gate; it needs the conductor's read-only view of the page too.
const DEMO_ON = import.meta.env.DEV && typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('demo') === '1';
const DemoOverlay = import.meta.env.DEV ? lazy(() => import('./dev/DemoOverlay')) : null;
const DEV_ON = import.meta.env.DEV && typeof window !== 'undefined' && (new URLSearchParams(window.location.search).get('dev') === '1' || DEMO_ON);
// ?tour=1: the guided tour (camera and highlights only; it changes no state). A separate gate from ?dev=1: each tool's code loads only for its own.
const TOUR_ON = import.meta.env.DEV && typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('tour') === '1';
// Read at load: the page rewrites the URL as the slider moves. Where the Harvey beat opens, if not at the briefed time (dev only).
const HARVEY_START_PARAM = DEV_ON ? new URLSearchParams(window.location.search).get('harveyStart') : null;
/** DEV ONLY: the connection as the page shows it, read back for the offline beat's checks. */
function offlineView() {
  const c = getConnection();
  const banner = [...document.querySelectorAll('[role="status"]')].some((e) => /Offline since/i.test(e.textContent ?? ''));
  const sources = [...document.querySelectorAll('[aria-live="polite"]')].map((e) => e.textContent ?? '').find((t) => /Sources/.test(t)) ?? '';
  return { state: c.state, offlineSince: c.offlineSince, lastLoadedAt: c.lastLoadedAt, recoveredAt: c.recoveredAt, banner,
           cached: (sources.match(/\bcached\b/gi) ?? []).length, unknown: (sources.match(/\bunknown\b/gi) ?? []).length };
}

const OPERATOR_KEY = 'tidealert.operator';
const PLAY_STEP_MS = 1500; // one 15-minute step of the replay clock per 1.5 s: slow enough for the zones to load each step

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
  const [tasksAt, setTasksAt] = useState<string | null>(null); // the time the loaded tasks are for
  const [cases, setCases] = useState<Case[] | null>(null);
  const [responderList, setResponderList] = useState<Responder[] | null>(null);
  const [responderError, setResponderError] = useState<string | null>(null);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [operator, setOperator] = useState(storedOperator);
  const [ethicsOpen, setEthicsOpen] = useState(false);
  const [portalOpen, setPortalOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [validationOpen, setValidationOpen] = useState(false);
  const [gaugesOpen, setGaugesOpen] = useState(false);
  const [layer, setLayer] = useState<Layer>('risk'); // what the zone fill shows
  const [supply, setSupply] = useState<SupplyAccess | null>(null);
  const [supplyError, setSupplyError] = useState<string | null>(null);
  const [needs, setNeeds] = useState<Needs | null>(null);
  const [needsError, setNeedsError] = useState<string | null>(null);
  const [lastCall, setLastCall] = useState<LastCall | null>(null);
  const [lastCallError, setLastCallError] = useState<string | null>(null);
  const [aerial, setAerial] = useState<AerialPriority | null>(null);
  const [aerialError, setAerialError] = useState<string | null>(null);
  const [lead, setLead] = useState<Lead>(loadLead);
  const [playing, setPlaying] = useState(false);
  const [relief, setRelief] = useState<ReliefBoard | null>(null);
  const [reliefError, setReliefError] = useState<string | null>(null);
  const [depots, setDepots] = useState<DepotList | null>(null);
  const [depotId, setDepotId] = useState<string | null>(null);
  const [depotAccess, setDepotAccess] = useState<DepotAccess | null>(null);
  const [depotError, setDepotError] = useState<string | null>(null);
  const [casesAt, setCasesAt] = useState<string | null>(null); // the time the loaded Cases are for
  const [pendingStart, setPendingStart] = useState<{ runId: string; at: string } | null>(null);
  const [refit, setRefit] = useState(0);
  const [version, setVersion] = useState(0); // bumped after a task action: everything is read again
  const [status, setStatus] = useState('loading runs…');
  const [error, setError] = useState<string | null>(null);

  const conn = useConnection();

  useEffect(() => startConnectionWatch(), []);

  // The server is back: read the view again, so nothing stale stays on screen.
  useEffect(() => { if (conn.recoveredAt) setVersion((v) => v + 1); }, [conn.recoveredAt]);

  // While the server can't be reached the page is read-only, and says so where a write would be: the task actions
  // and the needs and offers forms read the reason from these copies. Nothing is queued.
  const offline = conn.state === 'offline';
  const OFFLINE_REASON = 'offline: the page is read-only until the connection returns';
  const actRun = useMemo(() => (run && offline ? { ...run, task_actions_blocked: OFFLINE_REASON } : run), [run, offline]);
  const ticks = useMemo(() => (run ? ticksFor(run) : []), [run]);
  const needsView = useMemo(() => (needs && offline ? { ...needs, writable: false, blocked_reason: OFFLINE_REASON } : needs), [needs, offline]);

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
  const closeReport = useCallback(() => setReportOpen(false), []);
  const closeValidation = useCallback(() => setValidationOpen(false), []);
  const closeGauges = useCallback(() => setGaugesOpen(false), []);

  const changeOperator = (v: string) => {
    setOperator(v);
    try { window.localStorage.setItem(OPERATOR_KEY, v); } catch { /* not remembered: still works for this visit */ }
  };

  useEffect(() => {
    // Load the saved copy of the last view first, so that with no connection the very first request is answered from
    // it (it is only ever served when a request fails at the network level).
    let alive = true;
    void restoreView().finally(() => {
      if (!alive) return;
      api.runs().then((body) => {
        setRuns(body.runs);
        setVocabulary(body.vocabulary);
        if (!body.runs.length) { setStatus('No runs in the database.'); return; }
        const url = readUrl(window.location.search);
        chooseRun(body.runs.find((r) => r.id === url.run) ?? body.runs[0], url.at);
      }).catch((e: Error) => setError(e.message));
    });
    return () => { alive = false; };
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
    api.tasks(run.id, at, ctl.signal).then((b) => { setTasks(b.tasks); setTasksAt(b.at); })
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message); });
    api.cases(run.id, null, at, ctl.signal).then((b) => { setCases(b.cases); setCasesAt(b.at); })
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

  const ranked = useMemo(() => rankAttention(zones, cases, needs), [zones, cases, needs]);

  // ---- DEV ONLY: what the demo driver is allowed to see and do (dead code in a production build). It sees only what this page has
  // already fetched for the replay step the playhead is at, and drives the page through the same state the slider and Play use.
  const [demo, setDemo] = useState<{ active: boolean; clockMs: number | null; countdownMs: number | null; caption: string | null; pinned: string[]; hidden: string[] }>(
    { active: false, clockMs: null, countdownMs: null, caption: null, pinned: [], hidden: [] });
  const ticksRef = useRef(ticks);
  ticksRef.current = ticks;
  const runsRef = useRef(runs);
  runsRef.current = runs;
  const lastSecond = useRef(-1);
  const changeLeadRef = useRef<(l: Lead) => void>(() => {});
  const snap = useRef<RawSnapshot | null>(null);
  const devNow = useRef<{ run: Run | null; zones: ZonesResponse | null }>({ run: null, zones: null }); // for the conductor's camera targets
  if (DEV_ON) devNow.current = { run, zones };
  if (DEV_ON) {
    const tickAt = ticks[tick] ? Date.parse(ticks[tick]) : null;
    const forStep = (iso: string | undefined | null) => iso != null && tickAt !== null && Date.parse(iso) === tickAt;
    const stepCases = cases && forStep(casesAt) ? cases : null;
    const headline = stepCases && zones && forStep(zones.at) ? headlineFacts(zones, stepCases, []) : null;
    snap.current = {
      mode: run?.mode ?? null,
      tickAt, clockMs: demo.clockMs ?? tickAt ?? 0,
      // The scenario has no isolation evidence (no supply-access or Last call answer to wait for, and the risk layer is shown), so it is
      // ready on the zones, Cases and sources alone; every other run also waits for its supply-access and Last call answers.
      ready: !!zones && forStep(zones.at) && forStep(casesAt) && !!freshness && forStep(freshness.at)
        && (run?.mode === 'scenario' || (forStep(supply?.at) && forStep(lastCall?.at) && forStep(aerial?.at))),
      cases: cases && forStep(casesAt) ? cases.length : null,
      firstCaseAt: cases?.length ? Math.min(...cases.map((c) => Date.parse(c.opened_at))) : null,
      possibly: supply && forStep(supply.at) ? supply.counts.possibly_isolated?.zones ?? null : null,
      cutOff: supply && forStep(supply.at) ? supply.counts.isolated?.zones ?? null : null,
      freshness: freshness ? freshness.sources.map((s) => s.status) : null,
      headlineCutOff: headline ? headline.cutOff : null, headlineFlagged: headline ? headline.flagged : null,
      lastCall: lastCall && forStep(lastCall.at) ? lastCall : null, ranked, pinned: demo.pinned,
      aerial: aerial && forStep(aerial.at) ? aerial.zones.map((z) => ({ rank: z.rank, zoneId: z.zone_id, name: z.zone_name, minutes: z.cut_off_minutes })) : null,
      stepCases, stepZones: zones && forStep(zones.at) ? zones : null, // the conductor reads the scenario's evidence from these
      offline: null,
    };
  }
  // ---- DEV ONLY (?tour=1): what the guided tour may READ. It sees the run, the time and the layer on screen and which zones the engine finds
  // cut off; it is given no setter for any of them. Dead code in a production build.
  const tourNow = useRef<{ run: Run | null; zones: ZonesResponse | null; supply: SupplyAccess | null; layer: Layer; ready: boolean }>({ run: null, zones: null, supply: null, layer: 'risk', ready: false });
  if (TOUR_ON || DEMO_ON) {
    const tickAt = ticks[tick] ? Date.parse(ticks[tick]) : null;
    const forStep = (iso: string | undefined | null) => iso != null && tickAt !== null && Date.parse(iso) === tickAt;
    tourNow.current = { run, zones, supply, layer,
      ready: !!zones && forStep(zones.at) && forStep(casesAt) && forStep(supply?.at) && forStep(lastCall?.at) && forStep(aerial?.at) && !!freshness && forStep(freshness.at) };
  }
  const tourData = useMemo<TourData | null>(() => {
    if (!TOUR_ON && !DEMO_ON) return null;
    return {
      start: () => { const n = tourNow.current; return { mode: n.run?.mode ?? null, event: n.run?.event ?? null, at: n.zones?.at ?? null, layer: n.layer, ready: n.ready, runId: n.run?.id ?? null }; },
      extent: () => tourNow.current.run?.extent ?? null,
      cutOffPoints: () => {
        const { zones: z, supply: sp } = tourNow.current;
        if (!z || !sp) return [];
        const pts: [number, number][] = [];
        for (const f of z.features) {
          if (sp.zones[f.properties.zone_id]?.zone_access !== 'isolated') continue;
          let w = Infinity, e = -Infinity, s = Infinity, n = -Infinity;
          const walk = (c: unknown): void => { if (Array.isArray(c) && typeof c[0] === 'number') { w = Math.min(w, c[0]); e = Math.max(e, c[0]); s = Math.min(s, c[1] as number); n = Math.max(n, c[1] as number); } else if (Array.isArray(c)) c.forEach(walk); };
          walk((f.geometry as { coordinates?: unknown }).coordinates);
          if (Number.isFinite(w)) pts.push([(w + e) / 2, (s + n) / 2]);
        }
        return pts;
      },
    };
  }, []);
  // DEV ONLY (?dev=1, Scene 2): what the scene may READ about the page now. It acts only through clicks and typing in the page itself.
  const sceneNow = useRef<{ run: Run | null; zones: ZonesResponse | null; supply: SupplyAccess | null; needs: Needs | null; tasksAt: string | null; casesAt: string | null; ranked: ReturnType<typeof rankAttention>; selected: string | null; ticks: string[]; tick: number }>(
    { run: null, zones: null, supply: null, needs: null, tasksAt: null, casesAt: null, ranked: [], selected: null, ticks: [], tick: 0 });
  if (DEV_ON) sceneNow.current = { run, zones, supply, needs, tasksAt, casesAt, ranked, selected: selectedZoneId, ticks, tick };
  const devHost = useMemo<DevHost | null>(() => {
    if (!DEV_ON) return null;
    const sceneFacts = (): Scene2Facts => {
      const n = sceneNow.current;
      const tickAt = n.ticks[n.tick] ? Date.parse(n.ticks[n.tick]) : null;
      const same = (iso: string | undefined | null) => iso != null && tickAt !== null && Date.parse(iso) === tickAt;
      return {
        ready: !!n.zones && same(n.zones.at) && same(n.casesAt) && same(n.supply?.at) && same(n.needs?.at) && same(n.tasksAt),
        runId: n.run?.id ?? null, mode: n.run?.mode ?? null, atMs: tickAt, ticks: n.ticks.map((t) => Date.parse(t)), windowEnd: n.run?.window_end ?? null,
        zones: (n.zones?.features ?? []).map((f) => ({ id: f.properties.zone_id, name: f.properties.name, tasks: f.properties.task_count, taskStatus: f.properties.task_count > 0 ? f.properties.task_status : null,
                                                        access: same(n.supply?.at) ? n.supply?.zones[f.properties.zone_id]?.zone_access ?? null : null })),
        ranked: n.ranked.map((a) => ({ zoneId: a.zoneId, name: a.name, group: a.group })),
        selectedZoneId: n.selected, needsWritable: n.needs?.writable ?? null,
      };
    };
    const mixedRun = () => runsRef.current.find((x) => x.mode === 'mixed' && x.event != null && x.peak_at) ?? runsRef.current.find((x) => x.mode === 'mixed') ?? null;
    return {
      demo: {
        // The Harvey replay at the tour's start (2017-08-28 05:15 UTC, coloured by supply access), read-only, nothing open: the Full Demo's first frame.
        openHarvey: async () => {
          const r = runsRef.current.find((x) => x.mode === 'replay' && x.peak_at && x.event?.includes('Harvey'));
          if (!r) return false;
          const start = '2017-08-28T05:15:00.000Z';
          const tickTimes = ticksFor(r).map((t) => Date.parse(t));
          if (!tickTimes.includes(Date.parse(start))) return false;
          chooseRun(r, start);
          setLayer('supply');
          setPortalOpen(false);
          setRefit((n) => n + 1);
          setDemo({ active: false, clockMs: null, countdownMs: null, caption: null, pinned: [], hidden: [] });
          for (let i = 0; i < 120; i++) { await new Promise((res) => setTimeout(res, 250)); if (tourNow.current.ready && tourNow.current.run?.id === r.id && tourNow.current.zones?.at && Date.parse(tourNow.current.zones.at) === Date.parse(start)) return true; }
          return false;
        },
      },
      scene2: {
        mixedRunId: () => mixedRun()?.id ?? null,
        goToTick: (i) => { setPlaying(false); setTick(i); setAt(ticksRef.current[i]); },
        facts: sceneFacts,
        extent: () => devNow.current.run?.extent ?? null,
        zoneGeometry: (id) => devNow.current.zones?.features.find((f) => f.properties.zone_id === id)?.geometry ?? null,
        active: (on) => setDemo(on ? (d) => ({ ...d, active: true }) : { active: false, clockMs: null, countdownMs: null, caption: null, pinned: [], hidden: [] }),
        // The mixed Harvey run at its recorded peak, frozen, nothing open: the scene's starting point.
        open: async () => {
          const r = mixedRun();
          if (!r?.peak_at) return null;
          const tickTimes = ticksFor(r).map((t) => Date.parse(t));
          const want = Date.parse(r.peak_at);
          const startMs = tickTimes.filter((t) => t <= want).at(-1);
          if (startMs === undefined) return null;
          chooseRun(r, ticksFor(r)[tickTimes.indexOf(startMs)]);
          setLayer('supply');
          setPortalOpen(false);
          setRefit((n) => n + 1);
          setDemo({ active: true, clockMs: null, countdownMs: null, caption: null, pinned: [], hidden: [] });
          for (let i = 0; i < 120; i++) { await new Promise((res) => setTimeout(res, 250)); if (sceneFacts().ready && sceneFacts().atMs === startMs && sceneFacts().runId === r.id) break; }
          return { startMs };
        },
      },
      snapshot: () => ({ ...snap.current!, offline: offlineView() }),
      goToTick: (i) => { setPlaying(false); setTick(i); setAt(ticksRef.current[i]); },
      setClock: (ms, second) => {
        const newSecond = second !== lastSecond.current; // decided here, not inside the updater (StrictMode runs updaters twice)
        if (newSecond) lastSecond.current = second;
        setDemo((d) => (d.clockMs === ms && !newSecond ? d : { ...d, clockMs: ms, countdownMs: newSecond ? ms : d.countdownMs }));
      },
      pinZone: (id) => setDemo((d) => (id === '' ? { ...d, pinned: [] } : d.pinned.includes(id) ? d : { ...d, pinned: [...d.pinned, id] })),
      pulseZone,
      caption: (text) => setDemo((d) => (d.caption === text ? d : { ...d, caption: text })),
      frozen: () => setPlaying(false),
      reveal: (panel) => setDemo((d) => (d.hidden.includes(panel) ? { ...d, hidden: d.hidden.filter((x) => x !== panel) } : d)),
      active: (on) => setDemo(on ? (d) => ({ ...d, active: true }) : { active: false, clockMs: null, countdownMs: null, caption: null, pinned: [], hidden: [] }),
      offline: (on) => devForceOffline(on),
      connection: () => ({ state: getConnection().state, offlineSince: getConnection().offlineSince }),
      harveyStart: () => HARVEY_START_PARAM,
      extent: () => devNow.current.run?.extent ?? null,
      zoneGeometry: (id) => devNow.current.zones?.features.find((f) => f.properties.zone_id === id)?.geometry ?? null,
      // Open a beat's run at its start, frozen: the Harvey replay at `wantAt`, the listening scenario at its window start. `hidden`: panels to hold back.
      open: async (beat, wantAt, hidden) => {
        const r = beat === 'isolation' ? runsRef.current.find((x) => x.mode === 'replay' && x.peak_at)
          : runsRef.current.find((x) => x.mode === 'scenario' && x.sources.some((src) => src.name.startsWith('Listening')));
        if (!r) return null;
        const tickTimes = ticksFor(r).map((t) => Date.parse(t));
        const want = Date.parse(beat === 'isolation' ? wantAt ?? '' : r.window_start ?? '');
        const at = tickTimes.filter((t) => t <= want).at(-1); // the last run step at or before the wanted time
        const startMs = Number.isFinite(want) && at !== undefined ? at : null;
        if (startMs === null) return null;
        const startIso = ticksFor(r)[tickTimes.indexOf(startMs)];
        chooseRun(r, startIso);
        setLayer(beat === 'isolation' ? 'supply' : 'risk');
        if (beat === 'isolation') changeLeadRef.current({ reply: 0, decision: 0, travel: 0 });
        setRefit((n) => n + 1);
        setDemo({ active: true, clockMs: startMs, countdownMs: startMs, caption: null, pinned: [], hidden });
        for (let i = 0; i < 120; i++) { await new Promise((res) => setTimeout(res, 250)); if (snap.current?.ready && snap.current.tickAt === startMs) break; }
        return { startMs, tickTimes };
      },
    };
  }, [chooseRun]);

  // "Start here": the run with a recorded peak (the Harvey replay), opened at that tick with the map framed and the
  // first-ranked zone and Case selected once their answers for that time have loaded.
  const startRun = useMemo(() => runs.find((r) => r.mode === 'replay' && r.peak_at) ?? runs.find((r) => r.peak_at) ?? null, [runs]);
  const startHere = () => {
    if (!startRun?.peak_at) return;
    chooseRun(startRun, startRun.peak_at);
    setLayer('supply');
    setPendingStart({ runId: startRun.id, at: startRun.peak_at });
    setRefit((n) => n + 1);
  };
  useEffect(() => {
    if (!pendingStart || !run || run.id !== pendingStart.runId || !zones || zones.run_id !== run.id || !cases || !casesAt) return;
    if (Date.parse(zones.at) !== Date.parse(pendingStart.at) || Date.parse(casesAt) !== Date.parse(pendingStart.at)) return;
    const top = ranked[0];
    if (top) { setSelectedZoneId(top.zoneId); setSelectedCaseId(top.caseId); }
    setPendingStart(null);
  }, [pendingStart, run, zones, cases, casesAt, ranked]);

  // Candidate depots (real OSM fire stations) for runs that have depot access, and the chosen depot's reach as of the
  // slider time. Read only while the layer is on.
  useEffect(() => {
    setDepots(null); setDepotId(null); setDepotAccess(null);
    if (!run) return;
    const ctl = new AbortController();
    api.depots(run.id, ctl.signal).then((d) => { setDepots(d); setDepotId(d.depots[0]?.id ?? null); })
      .catch((e: Error) => { if (e.name !== 'AbortError') setDepots(null); });
    return () => ctl.abort();
  }, [run?.id]);
  useEffect(() => {
    if (layer === 'depot' && depots && !depots.available) setLayer('risk'); // a run without depot access falls back
    if (!run || layer !== 'depot' || !depotId) return;
    const ctl = new AbortController();
    setDepotError(null);
    api.depotAccess(run.id, depotId, at, ctl.signal).then(setDepotAccess)
      .catch((e: Error) => { if (e.name !== 'AbortError') setDepotError(e.message); });
    return () => ctl.abort();
  }, [run, at, layer, depotId, depots, version]);

  // The relief board (needs and test pledges, ranked by each zone's access state at the slider time). A need or pledge the
  // server just answered replaces its row at once; the next read re-ranks.
  useEffect(() => { setRelief(null); }, [run?.id]);
  useEffect(() => {
    if (!run) return;
    const ctl = new AbortController();
    setReliefError(null);
    api.reliefNeeds(run.id, at, ctl.signal).then(setRelief)
      .catch((e: Error) => { if (e.name !== 'AbortError') setReliefError(e.message); });
    return () => ctl.abort();
  }, [run, at, version]);

  // Last call: each flagged zone's recorded cut-off minus the lead time the operator set. Read again at every time step, so the
  // countdown moves as the slider (or Play) moves. The lead is a per-viewer setting, remembered in the browser.
  useEffect(() => { setLastCall(null); }, [run?.id]);
  useEffect(() => {
    if (!run) return;
    const ctl = new AbortController();
    setLastCallError(null);
    api.lastCall(run.id, at, lead, ctl.signal).then(setLastCall)
      .catch((e: Error) => { if (e.name !== 'AbortError') setLastCallError(e.message); });
    return () => ctl.abort();
  }, [run, at, lead, version]);
  // Aerial priority: the cut-off zones ranked for an aerial look, read again at every time step. A ranking only.
  useEffect(() => { setAerial(null); }, [run?.id]);
  useEffect(() => {
    if (!run) return;
    const ctl = new AbortController();
    setAerialError(null);
    api.aerialPriority(run.id, at, ctl.signal).then(setAerial)
      .catch((e: Error) => { if (e.name !== 'AbortError') setAerialError(e.message); });
    return () => ctl.abort();
  }, [run, at, version]);
  const changeLead = (l: Lead) => { setLead(l); saveLead(l); };
  changeLeadRef.current = changeLead;

  // Play: step the replay clock forward one tick at a time so a countdown can be watched. It stops at the end of the window,
  // when the run changes, or on Pause; moving the slider by hand pauses it.
  const tickRef = useRef(tick);
  tickRef.current = tick;
  useEffect(() => {
    if (!playing || !run) return;
    const id = window.setInterval(() => {
      const n = tickRef.current + 1;
      if (n >= ticks.length) { setPlaying(false); return; }
      setTick(n);
      setAt(ticks[n]);
    }, PLAY_STEP_MS);
    return () => window.clearInterval(id);
  }, [playing, run, ticks]);
  useEffect(() => { setPlaying(false); }, [run?.id]);

  const zoneNames = useMemo(() => new Map((zones?.features ?? []).map((f) => [f.properties.zone_id, f.properties.name])), [zones]);

  const zone = selectedZoneId && zones?.run_id === run?.id
    ? zones?.features.find((f) => f.properties.zone_id === selectedZoneId)?.properties ?? null : null;

  return (
    <div className="flex min-h-screen flex-col pb-6 antialiased selection:bg-cyan-950 selection:text-white">
      <Header runs={runs} run={run} onRun={(id) => { const r = runs.find((x) => x.id === id); if (r) chooseRun(r, null); }}
              ticks={ticks} tick={tick} onTickInput={(i) => { setPlaying(false); setTick(i); }} onTickCommit={() => setAt(ticks.length ? ticks[tick] : null)}
              onEthics={() => setEthicsOpen(true)} onReport={() => setReportOpen(true)} onValidation={() => setValidationOpen(true)} onGauges={() => setGaugesOpen(true)} onStart={startRun ? startHere : null} playing={playing} onPlay={() => setPlaying((p) => !p)}
              caseCount={cases && run ? cases.length : null}
              clockLabel={demo.active && demo.clockMs !== null ? fmtTime(new Date(demo.clockMs).toISOString()) : null} caption={demo.active ? demo.caption : null} />
      {ethicsOpen && <EthicsPanel run={run} freshness={freshness} vocabulary={vocabulary} onClose={closeEthics} />}
      <ConnectionBanner conn={conn} asOf={zones ? fmtTime(zones.at) : null} />
      {gaugesOpen && <GaugesPanel onClose={closeGauges} />}
      {validationOpen && <ValidationPanel onClose={closeValidation} />}
      {reportOpen && run && <ReportPanel run={run} at={zones?.at ?? at} onClose={closeReport} />}
      {portalOpen && run && <DonationPortal run={run} needs={needsView} needsError={needsError} operator={operator} at={zones?.at ?? at}
                                           onChanged={() => setVersion((v) => v + 1)} onClose={closePortal} />}
      {run && <FreshnessBanner run={run} freshness={freshness} conn={conn} />}

      <main className="mx-auto mt-4 grid w-full max-w-7xl flex-1 grid-cols-1 gap-6 px-6 lg:grid-cols-3">
        <div className="lg:col-span-3"><Headline run={run} zones={zones} cases={cases} tasks={tasks} /></div>
        <div className="flex flex-col gap-6 lg:col-span-2">
        <section className="flex flex-col overflow-hidden rounded-lg border border-accent-cyan/20 bg-navy-panel">
          <MapToolbar run={run} layer={layer} onLayer={setLayer} supply={supply} supplyError={supplyError} needs={needsView}
                      depots={depots} depotId={depotId} onDepot={setDepotId} depotAccess={depotAccess} depotError={depotError}
                      needsError={needsError} onSelectZone={(id) => { setSelectedZoneId(id); setSelectedCaseId(null); }}
                      onPortal={() => setPortalOpen(true)} />
          <div className="h-[560px]">
            <ZoneMap run={run} zones={zones} selectedZoneId={selectedZoneId} layer={layer} supply={supply} depot={depotAccess} refit={refit} pulseNew={playing || demo.active} flat={demo.active} holdView={demo.active}
                     onSelectZone={(id) => { setSelectedZoneId(id); setSelectedCaseId(null); }}>
              <MapLegend layer={layer} vocabulary={vocabulary} supply={supply} depot={depotAccess} />
            </ZoneMap>
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
            <ReliefPanel run={run} board={relief} error={reliefError} operator={operator} at={zones?.at ?? at} offline={offline}
                         selectedZone={zone ? { id: zone.zone_id, name: zone.name } : null}
                         mixed={runs.find((r) => r.mode === 'mixed' && r.event === run.event && r.event != null) ?? null}
                         onNeed={(n) => { setRelief((b) => (b ? withNeed(b, n) : b)); setVersion((v) => v + 1); }}
                         onSwitch={(id) => { const r = runs.find((x) => x.id === id); if (r) chooseRun(r, zones?.at ?? at); }} />
            <OperatorBar run={run} runs={runs} operator={operator} onOperator={changeOperator}
                         onRun={(id) => { const r = runs.find((x) => x.id === id); if (r) chooseRun(r, zones?.at ?? at); }} />
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <AlertsPanel run={actRun ?? run} animateNew={playing || demo.active} at={zones?.at ?? at} cases={cases} error={null} zoneNames={zoneNames}
                           selectedCaseId={selectedCaseId}
                           onSelectCase={(c) => { setSelectedCaseId(c?.id ?? null); if (c) setSelectedZoneId(c.zone_id); }}
                           operator={operator} responders={responderList ?? []} onActed={() => setVersion((v) => v + 1)} />
              <RespondersPanel run={run} responders={responderList} tasks={tasks} error={responderError} />
            </div>
          </>
        )}
        </div>

        <div className="flex flex-col gap-6">
          <LastCallPanel data={lastCall} error={lastCallError} lead={lead} onLead={changeLead} selectedZoneId={selectedZoneId}
                         onSelect={(id) => { setSelectedZoneId(id); setSelectedCaseId(null); }}
                         pinned={demo.active ? demo.pinned : null} clockMs={demo.active && demo.countdownMs !== null ? demo.countdownMs : undefined} />
          {!(DEV_ON && demo.active && demo.hidden.includes('aerial')) && (
            <AerialPanel data={aerial} error={aerialError} selectedZoneId={selectedZoneId}
                         onSelect={(id) => { setSelectedZoneId(id); setSelectedCaseId(null); }} />
          )}
          <AttentionList items={ranked} selectedZoneId={selectedZoneId}
                         onSelect={(a) => { setSelectedZoneId(a.zoneId); setSelectedCaseId(a.caseId); }} />
          {run && (
            <CopilotPanel key={run.id} run={run} at={zones?.at ?? at} zoneId={zone ? selectedZoneId : null}
                          zoneName={zone?.name ?? null} caseId={selectedCaseId}
                          caseWord={cases?.find((c) => c.id === selectedCaseId)?.confidence_word ?? null} />
          )}
          <Panel title="Zone" className="h-[420px]">
            {run ? <ZonePanel run={run} at={zones?.at ?? at} zone={zone} gapReasons={zones?.gap_reasons ?? []}
                              responders={responders} version={version} supply={supply} supplyError={supplyError}
                              needs={needsView} needsError={needsError} operator={operator} onNeedsChanged={() => setVersion((v) => v + 1)} depotAccess={layer === 'depot' ? depotAccess : null}
                              lastCall={lastCall ? { zone: lastCall.zones.find((z) => z.zone_id === zone?.zone_id), loaded: lastCall.available } : null} />
              : <p className="text-slate-500">loading…</p>}
          </Panel>
          <Panel title="Legend" className="max-h-[300px]">
            {vocabulary ? <Legend vocabulary={vocabulary} supply={supply} /> : <p className="text-slate-500">loading…</p>}
          </Panel>
        </div>
      </main>
      {DevOverlay && DEV_ON && !TOUR_ON && !DEMO_ON && devHost && <Suspense fallback={null}><DevOverlay gate="dev" host={devHost} tour={null} /></Suspense>}
      {DemoOverlay && DEMO_ON && !TOUR_ON && devHost && tourData && <Suspense fallback={null}><DemoOverlay host={devHost} tour={tourData} /></Suspense>}
      {DevOverlay && TOUR_ON && tourData && <Suspense fallback={null}><DevOverlay gate="tour" host={null} tour={tourData} /></Suspense>}
    </div>
  );
}
