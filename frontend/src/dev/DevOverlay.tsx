// DEV ONLY. The wrapper both dev tools sit in. It is mounted by App only in a Vite dev build AND only when its URL gate is present:
//   ?tour=1  the guided tour   (camera, highlights and a narration read-along; changes no app state)
//   ?dev=1   the demo conductor (sequences real engine events on the Harvey replay and the listening scenario)
// Neither gate present: App never renders this file, so neither tool's code is fetched. In a production build the import is dead code.
// Each tool's own module is imported here only for its own gate. The shared player (TimelinePlayer) draws the controls for both.
import { useEffect, useRef, useState } from 'react';
import type { Conductor, DevHostBase, BeatName, Host, LogEntry } from './conductor';
import type { StartState, Tour, TourHost, HighlightType } from './tour';
import { COUNTDOWN_S, PlayerClock, type PlayerStatus, TimelinePlayer, type Tool } from './TimelinePlayer';

export type { DevHostBase as DevHost };
export interface TourData { start(): StartState; extent(): [number, number, number, number] | null; cutOffPoints(): [number, number][] }
export type Gate = 'tour' | 'dev';

interface Mark { el: Element; type: HighlightType; label: string }

/** The tour's highlight boxes. They are drawn here, over the page, from each element's own rectangle: nothing in the app's markup is touched. */
function HighlightLayer({ marks }: { marks: Mark[] }) {
  const [, setFrame] = useState(0);
  useEffect(() => {
    if (marks.length === 0) return;
    let raf = 0;
    const loop = () => { setFrame((n) => n + 1); raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [marks]);
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-[60]" data-dev-highlights>
      {marks.map((m) => {
        const r = m.el.getBoundingClientRect();
        const box = { left: r.left - 4, top: r.top - 4, width: r.width + 8, height: r.height + 8 };
        const cls = m.type === 'pulse' ? 'animate-pulse border-[3px] border-fuchsia-400 bg-fuchsia-400/10'
          : m.type === 'dim' ? 'border-[3px] border-fuchsia-400 shadow-[0_0_0_100vmax_rgba(0,0,0,0.6)]' : 'border-[3px] border-fuchsia-400';
        return <div key={m.label} className={`absolute rounded ${cls}`} style={box} data-dev-highlight={m.label} data-type={m.type} data-rect={`${Math.round(box.left)},${Math.round(box.top)},${Math.round(box.width)},${Math.round(box.height)}`} />;
      })}
    </div>
  );
}

export default function DevOverlay({ gate, host, tour }: { gate: Gate; host: DevHostBase | null; tour: TourData | null }) {
  const clock = useRef(new PlayerClock()).current;
  const tool = useRef<(Tool & Partial<Conductor> & Partial<Tour>) | null>(null);
  const beat = useRef<BeatName | null>(null);
  const [status, setStatus] = useState<PlayerStatus>(gate === 'tour' ? 'idle' : 'idle');
  const [message, setMessage] = useState<string | null>(null);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [marks, setMarks] = useState<Mark[]>([]);
  const [caption, setCaption] = useState<string | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [, setOffline] = useState(false);
  const [, force] = useState(0);
  const statusRef = useRef(status);
  statusRef.current = status;
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearCountdown = () => { timers.current.forEach(clearTimeout); timers.current = []; setCountdown(null); };

  // ---- the tour: built from its own module, only under ?tour=1
  useEffect(() => {
    if (gate !== 'tour' || !tour) return;
    let cancelled = false;
    void import('./tour').then(({ createTour }) => {
      if (cancelled) return;
      const map = () => (window as unknown as { __map?: TourHost['map'] extends () => infer M ? M : never }).__map ?? null;
      const t = createTour({ start: tour.start, map, extent: tour.extent, cutOffPoints: tour.cutOffPoints },
        { highlight: (items) => setMarks(items), caption: setCaption }, clock);
      tool.current = t;
      setStatus('ready');
    });
    return () => { cancelled = true; tool.current?.stop(); };
  }, [gate, tour, clock]);

  // While the tour has not started, say why it cannot (the page may still be loading, or be on the wrong run).
  useEffect(() => {
    if (gate !== 'tour') return;
    const id = window.setInterval(() => {
      const t = tool.current as Tour | null;
      if (!t || !['ready', 'refused'].includes(statusRef.current)) return;
      const why = t.refusal();
      setMessage(why);
      setStatus(why ? 'refused' : 'ready');
    }, 500);
    return () => window.clearInterval(id);
  }, [gate]);

  // ---- the shared tick: 100 ms, for whichever tool is loaded
  useEffect(() => {
    const id = window.setInterval(() => {
      const t = tool.current;
      if (!t || !['running', 'paused'].includes(statusRef.current)) return;
      t.tick();
      if (t.log) setLog(t.log());
      if (t.finished()) { clock.pause(); setStatus('finished'); }
    }, 100);
    return () => window.clearInterval(id);
  }, [clock]);

  // ---- controls
  function play() {
    const t = tool.current;
    if (!t) return;
    if (statusRef.current === 'paused') { clock.play(); setStatus('running'); return; }
    if (statusRef.current !== 'ready' && statusRef.current !== 'finished') return;
    if (statusRef.current === 'finished') { restart(); return; }
    setStatus('countdown');
    let n = COUNTDOWN_S;
    setCountdown(n);
    const step = () => {
      n -= 1;
      if (n > 0) { setCountdown(n); timers.current.push(setTimeout(step, 1000)); return; }
      clearCountdown();
      const why = gate === 'tour' ? (t as Tour).refusal?.() ?? null : null;
      if (why) { setMessage(why); setStatus('refused'); return; }
      clock.pause(); clock.seek(0); clock.play();
      t.start();
      setStatus('running');
    };
    timers.current.push(setTimeout(step, 1000));
  }
  function pause() { clock.pause(); (window as unknown as { __map?: { stop(): void } }).__map?.stop(); setStatus('paused'); }
  async function restart() {
    clearCountdown(); clock.pause();
    if (gate === 'tour') {
      const t = tool.current as Tour;
      t.stop(); clock.seek(0); t.seek(0); setStatus('ready'); setMessage(null);
    } else if (beat.current) await selectBeat(beat.current);
  }
  function skip(i: number) {
    const t = tool.current;
    if (!t) return;
    clearCountdown();
    t.seek(i);
    if (statusRef.current === 'ready' || statusRef.current === 'finished') { setStatus('paused'); }
    force((n) => n + 1);
  }
  function speed(x: number) { clock.setSpeed(x); force((n) => n + 1); }

  // ---- the conductor: its own module, only under ?dev=1
  async function selectBeat(b: BeatName) {
    if (!host) return;
    clearCountdown(); tool.current?.stop(); clock.pause(); clock.seek(0); setLog([]); setMessage(null);
    setStatus('opening');
    const { createConductor, withListening, BEATS, HARVEY_START } = await import('./conductor');
    const adapted: Host = { ...host, snapshot: () => withListening(host.snapshot()) };
    let startMs: number; let tickTimes: number[] = [];
    if (b === 'offline') {
      host.offline(false); setOffline(false);
      startMs = host.snapshot().clockMs;
    } else {
      const o = await host.open(b, host.harveyStart() ?? HARVEY_START, BEATS[b].hidden);
      if (!o) { host.active(false); setStatus('idle'); setMessage(b === 'isolation' ? 'Could not open: no Harvey replay, or no step at its start time.' : 'Could not open: no listening scenario in this database.'); return; }
      startMs = o.startMs; tickTimes = o.tickTimes;
    }
    beat.current = b;
    tool.current = createConductor(adapted, tickTimes, startMs, b, clock);
    setStatus('ready');
  }
  async function openHarvey() {
    if (!host) return;
    clearCountdown(); tool.current?.stop(); tool.current = null; beat.current = null; clock.pause(); clock.seek(0); setLog([]);
    setStatus('opening');
    const { BEATS, HARVEY_START } = await import('./conductor');
    const o = await host.open('isolation', host.harveyStart() ?? HARVEY_START, BEATS.isolation.hidden);
    setStatus('idle');
    setMessage(o ? `Harvey replay frozen at its start (${new Date(o.startMs).toISOString().slice(0, 16).replace('T', ' ')} UTC). Pick a beat.` : 'Could not open: no Harvey replay, or no step at its start time.');
  }
  function goOffline(on: boolean) { host?.offline(on); setOffline(on); }
  function reset() {
    clearCountdown(); tool.current?.stop(); host?.offline(false); host?.pinZone(''); host?.active(false);
    // A cold page: the address a person opens, without the run and time the page wrote into the URL as it played. Nothing the tools showed
    // is left, and neither wrote anything to the database.
    window.location.assign(`${window.location.pathname}?${gate === 'tour' ? 'tour' : 'dev'}=1`);
  }

  // a handle for scripted browser checks
  useEffect(() => {
    (window as unknown as { __dev: unknown }).__dev = {
      gate, play, pause, restart, skip, speed, selectBeat, openHarvey, offline: goOffline, reset,
      status: () => statusRef.current, message: () => message, clock: () => clock.time(),
      log: () => tool.current?.log?.() ?? [], report: () => tool.current?.report?.() ?? [], snaps: () => tool.current?.snaps?.() ?? [],
      line: () => tool.current?.line(clock.time()) ?? null, marks: () => marks.map((m) => ({ label: m.label, type: m.type })),
    };
    return () => { delete (window as unknown as { __dev?: unknown }).__dev; };
  });

  const t = tool.current;
  const btn = 'rounded border border-fuchsia-400/50 px-2 py-0.5 disabled:opacity-40';
  const busy = status === 'opening' || status === 'running' || status === 'countdown';
  const extra = gate === 'dev' ? (
    <>
      <div className="mt-1 flex flex-wrap gap-1.5">
        <button type="button" onClick={() => void openHarvey()} disabled={busy} className={btn}>Open on Harvey</button>
        <button type="button" onClick={() => void selectBeat('isolation')} disabled={busy} className={btn}>Isolation beat</button>
        <button type="button" onClick={() => void selectBeat('listening')} disabled={busy} className={btn}>Silence + Listening beat</button>
        <button type="button" onClick={() => void selectBeat('offline')} disabled={busy} className={btn}>Offline beat</button>
        <button type="button" onClick={() => goOffline(false)} className={btn}>Recover</button>
        <button type="button" onClick={reset} className={btn}>Reset</button>
      </div>
      {log.length > 0 && (
        <ul className="custom-scrollbar mt-1 max-h-28 space-y-0.5 overflow-y-auto text-[11px]">
          {log.map((e) => <li key={e.name + e.scriptedAt} className={e.ok ? '' : 'text-orange-300'}>{e.scriptedAt}s {e.name}: {e.ok ? `@${e.firedAt}s` : ''} {e.value}</li>)}
        </ul>
      )}
    </>
  ) : (
    <div className="mt-1 flex gap-1.5"><button type="button" onClick={reset} className={btn}>Reload clean</button></div>
  );
  return (
    <>
      {gate === 'tour' && <HighlightLayer marks={marks} />}
      {caption && <div className="pointer-events-none fixed left-1/2 top-16 z-[65] -translate-x-1/2 rounded bg-black/80 px-3 py-1 text-sm text-white" data-dev-caption>{caption}</div>}
      <TimelinePlayer title={gate === 'tour' ? 'Guided tour' : t?.title ?? 'Demo conductor'} steps={t?.steps ?? []} duration={t?.duration ?? (gate === 'tour' ? 84 : 0)} clock={clock} status={status}
                      line={t ? t.line(Math.min(clock.time(), t.duration)) : null} message={message} countdown={countdown}
                      onPlay={play} onPause={pause} onRestart={() => void restart()} onSkip={skip} onSpeed={speed} extra={extra} />
    </>
  );
}
