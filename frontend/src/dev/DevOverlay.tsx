// DEV ONLY. The wrapper both dev tools sit in. It is mounted by App only in a Vite dev build AND only when its URL gate is present:
//   ?tour=1  the guided tour   (camera, highlights and a narration read-along; changes no app state)
//   ?dev=1   the demo conductor (sequences real engine events on the Harvey replay and the listening scenario)
// Neither gate present: App never renders this file, so neither tool's code is fetched. In a production build the import is dead code.
// Each tool's own module is imported here only for its own gate. The shared player (TimelinePlayer) draws the controls for both.
import { useEffect, useRef, useState } from 'react';
import type { Conductor, DevHostBase, BeatName, Host } from './conductor';
import type { StartState, Tour, TourHost, HighlightType } from './tour';
import type { Scene2 } from './scene2';
import { COUNTDOWN_S, PlayerClock, type Line, type PlayerStatus, TimelinePlayer, type Tool, stepIndexAt } from './TimelinePlayer';
import { CompactPanel, GAP_S, SEQUENCE, elapsedIn, sequenceTotals } from './CompactPanel';

export type { DevHostBase as DevHost };
export interface TourData { start(): StartState; extent(): [number, number, number, number] | null; cutOffPoints(): [number, number][] }
export type Gate = 'tour' | 'dev';

export interface Mark { el: Element; type: HighlightType; label: string }

/** The tour's highlight boxes. They are drawn here, over the page, from each element's own rectangle: nothing in the app's markup is touched. */
export function HighlightLayer({ marks }: { marks: Mark[] }) {
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
  // ?dev=1 has two timelines: the three beats, and Scene 2 (one coordinator, one decision, on the mixed run).
  const [scene, setScene] = useState<'beats' | 'scene2'>('beats');
  const sceneRef = useRef(scene);
  sceneRef.current = scene;
  const scene2 = useRef<Scene2 | null>(null);
  // The conductor runs its three beats as one sequence: which beat, and the gap left before the next one starts (ms, null: not in a gap).
  const seq = useRef(0);
  const gap = useRef<number | null>(null);
  const meta = useRef<{ durations: number[]; stepCounts: number[]; titles: string[] } | null>(null);
  const reported = useRef(new Set<string>());
  const cam = useRef<ReturnType<typeof import('./camera').createCamera> | null>(null);
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

  // ---- the conductor's beat lengths, for the step and time read-out (its module loads here, only under ?dev=1)
  useEffect(() => {
    if (gate !== 'dev') return;
    void import('./conductor').then(({ BEATS }) => {
      meta.current = {
        durations: SEQUENCE.map((b) => BEATS[b].pacing.endAtS),
        stepCounts: SEQUENCE.map((b) => BEATS[b].script.filter((e) => e.name !== 'silence').length),
        titles: SEQUENCE.map((b) => ({ isolation: 'Beat 1: isolation on the Harvey replay', listening: 'Beat 2: silence and listening on the scenario', offline: 'Beat 3: offline' }[b])),
      };
    });
  }, [gate]);

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
      if (gate === 'dev') force((n) => n + 1); // the compact panel reads the clock
      if (!t || !['running', 'paused'].includes(statusRef.current)) return;
      if (gate === 'dev' && sceneRef.current === 'beats' && gap.current !== null) {
        // The 2 s between beats counts down only while running, so Pause holds it.
        if (statusRef.current === 'running') {
          gap.current -= 100;
          if (gap.current <= 0) { gap.current = null; seq.current += 1; void selectBeat(SEQUENCE[seq.current], true); }
        }
        return;
      }
      t.tick();
      if (gate === 'dev' && sceneRef.current === 'beats') reportToConsole(t as Conductor);
      if (t.finished()) {
        if (gate === 'dev' && sceneRef.current === 'beats' && seq.current < SEQUENCE.length - 1) gap.current = GAP_S * 1000;
        else { clock.pause(); setMarks([]); setStatus('finished'); }
      }
    }, 100);
    return () => window.clearInterval(id);
  }, [clock]);

  // ---- controls
  // The conductor's logs go to the console only; a skipped event is warned about there.
  function reportToConsole(t: Conductor) {
    for (const e of t.log()) {
      const key = `${seq.current}:${e.scriptedAt}:${e.name}`;
      if (reported.current.has(key)) continue;
      reported.current.add(key);
      const line = `[conductor] ${SEQUENCE[seq.current]} ${e.scriptedAt}s ${e.name}: ${e.ok ? `fired @${e.firedAt}s` : 'NOT FIRED'} (${e.replay}) ${e.value}`;
      if (e.ok) console.info(line); else console.warn(line);
    }
  }
  // Play, for the conductor: after the countdown, Beat 1, a 2 s gap, Beat 2, a 2 s gap, Beat 3, then it stops.
  function playSequence() {
    const s = statusRef.current;
    if (s === 'paused') { clock.play(); setStatus('running'); return; }
    if (s === 'running' || s === 'countdown' || s === 'opening') return;
    setStatus('countdown');
    let n = COUNTDOWN_S;
    setCountdown(n);
    const step = () => {
      n -= 1;
      if (n > 0) { setCountdown(n); timers.current.push(setTimeout(step, 1000)); return; }
      clearCountdown();
      seq.current = 0; gap.current = null;
      void selectBeat(SEQUENCE[0], true);
    };
    timers.current.push(setTimeout(step, 1000));
  }
  function play() {
    if (gate === 'dev') { if (sceneRef.current === 'scene2') void playScene2(); else playSequence(); return; }
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
  function pause() { clock.pause(); cam.current?.stop(); (window as unknown as { __map?: { stop(): void } }).__map?.stop(); setStatus('paused'); }
  async function restart() {
    clearCountdown(); clock.pause();
    if (gate === 'tour') {
      const t = tool.current as Tour;
      t.stop(); clock.seek(0); t.seek(0); setStatus('ready'); setMessage(null);
    } else if (sceneRef.current === 'scene2') {
      await prepareScene2();
    } else {
      // Back to Beat 1 at t=0 with nothing left over: the forced-offline switch off, pinned countdowns cleared, the run reopened at its start.
      // (The beats write nothing to the database; this is all the state they hold.)
      gap.current = null; seq.current = 0; reported.current.clear(); cam.current?.stop(); cam.current?.clear();
      host?.offline(false); host?.pinZone('');
      await selectBeat('isolation');
    }
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

  // ---- Scene 2: its own module, only under ?dev=1 and only when its tab is chosen
  function switchScene(next: 'beats' | 'scene2') {
    if (next === sceneRef.current) return;
    clearCountdown(); tool.current?.stop(); tool.current = null; scene2.current = null; clock.pause(); clock.seek(0);
    setMarks([]); setMessage(null); host?.offline(false); host?.pinZone(''); host?.active(false);
    gap.current = null; seq.current = 0;
    sceneRef.current = next; setScene(next); setStatus('idle');
  }
  /** Open the mixed run at its peak and build the scene; ready only when no earlier demo rows are left on the board. */
  async function prepareScene2(): Promise<boolean> {
    if (!host) return false;
    clearCountdown(); tool.current?.stop(); clock.pause(); clock.seek(0); setMessage(null); setMarks([]);
    setStatus('opening');
    const o = await host.scene2.open();
    if (!o) { host.active(false); setStatus('idle'); setMessage('Could not open: there is no mixed Harvey run in this database.'); return false; }
    const { createScene2 } = await import('./scene2');
    const t = createScene2(host.scene2, { highlight: (items) => setMarks(items) }, clock);
    scene2.current = t; tool.current = t as unknown as typeof tool.current;
    const pre = await t.precheck();
    if (pre) { setStatus('idle'); setMessage(pre); return false; }
    setStatus('ready');
    return true;
  }
  async function playScene2() {
    const s = statusRef.current;
    if (s === 'paused') { clock.play(); setStatus('running'); return; }
    if (s === 'running' || s === 'countdown' || s === 'opening') return;
    if (s !== 'ready' && !(await prepareScene2())) return;
    setMessage(null); setStatus('countdown');
    let n = COUNTDOWN_S;
    setCountdown(n);
    const step = () => {
      n -= 1;
      if (n > 0) { setCountdown(n); timers.current.push(setTimeout(step, 1000)); return; }
      clearCountdown();
      clock.pause(); clock.seek(0); clock.play();
      scene2.current?.start();
      setStatus('running');
    };
    timers.current.push(setTimeout(step, 1000));
  }
  async function resetScene2() {
    if (!host) return;
    const { resetDemo } = await import('./scene2');
    setMessage(await resetDemo(host.scene2));
  }

  // ---- the conductor: its own module, only under ?dev=1
  async function selectBeat(b: BeatName, auto = false) {
    if (!host) return;
    clearCountdown(); tool.current?.stop(); clock.pause(); clock.seek(0); setMessage(null);
    for (const k of [...reported.current]) if (k.startsWith(`${SEQUENCE.indexOf(b)}:`)) reported.current.delete(k);
    setStatus('opening');
    const { createConductor, withListening, BEATS, HARVEY_START } = await import('./conductor');
    const { createCamera, frameCenter, planMove, geometryCentroid } = await import('./camera');
    // The camera layer: targets come from the loaded data (the run's extent, a zone's own centroid); an unknown target holds the view.
    const map = () => (window as unknown as { __map?: import('./camera').MapView }).__map ?? null;
    cam.current ??= createCamera(map, (d) => { const line = `[camera] ${d.label}: ${d.move ? `${d.move.mode} to zoom ${d.move.zoom} over ${d.move.duration} ms` : d.note}`; if (d.move) console.info(line); else console.warn(line); });
    const places = { extent: () => host.extent(), zoneCenter: (id: string) => geometryCentroid(host.zoneGeometry(id)) };
    const look: Host['look'] = (label, spec, zones, why) => {
      if (!spec) { cam.current!.hold(label, why ?? 'no target'); return; }
      const c = frameCenter(spec.frame, zones, places);
      if (!c) { cam.current!.hold(label, `the loaded data does not give a ${spec.frame} target`); return; }
      cam.current!.go(label, planMove(spec, c, map()?.getZoom() ?? spec.zoom));
    };
    const adapted: Host = { ...host, snapshot: () => withListening(host.snapshot()), look };
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
    if (auto) { clock.play(); tool.current.start(); setStatus('running'); } else setStatus('ready');
  }
  async function openHarvey() {
    if (!host) return;
    clearCountdown(); tool.current?.stop(); tool.current = null; beat.current = null; clock.pause(); clock.seek(0);
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
      switchScene, resetScene2, prepareScene2, scene: () => sceneRef.current, scene2Log: () => scene2.current?.log() ?? [],
      status: () => statusRef.current, message: () => message, clock: () => clock.time(),
      log: () => tool.current?.log?.() ?? [], report: () => tool.current?.report?.() ?? [], snaps: () => tool.current?.snaps?.() ?? [],
      line: () => tool.current?.line(clock.time()) ?? null, camMoves: () => cam.current?.moves() ?? [], marks: () => marks.map((m) => ({ label: m.label, type: m.type })),
    };
    return () => { delete (window as unknown as { __dev?: unknown }).__dev; };
  });

  const t = tool.current;
  const btn = 'rounded border border-fuchsia-400/50 px-2 py-0.5 disabled:opacity-40';
  const extra = <div className="mt-1 flex gap-1.5"><button type="button" onClick={reset} className={btn}>Reload clean</button></div>;

  // The conductor's compact panel: where the sequence is, from the beat lengths and the clock.
  let devLine: Line | null = null; let stepN = 0; let stepM = 0; let elapsed = 0; let total = 0;
  if (gate === 'dev' && scene === 'scene2') {
    stepM = t?.steps.length ?? 19; total = t?.duration ?? 116;
    const into = Math.min(clock.time(), total);
    stepN = t ? Math.max(stepIndexAt(t.steps, into) + 1, 0) : 0; elapsed = into;
    devLine = message ? { text: message }
      : status === 'opening' ? { text: 'Opening the mixed run…' }
      : status === 'finished' ? { text: 'Scene 2 done. Press Reset to remove its rows, then Restart to run it again.' }
      : t && ['running', 'paused'].includes(status) ? t.line(into) : null;
  } else if (gate === 'dev') {
    const m = meta.current;
    const totals = m ? sequenceTotals(m.durations, m.stepCounts) : { seconds: 0, steps: 0 };
    stepM = totals.steps; total = totals.seconds;
    const inBeat = Math.min(clock.time(), t?.duration ?? 0);
    if (m) {
      stepN = m.stepCounts.slice(0, seq.current).reduce((x, y) => x + y, 0) + (t ? Math.max(stepIndexAt(t.steps, inBeat) + 1, 0) : 0);
      elapsed = elapsedIn(seq.current, m.durations, gap.current !== null ? m.durations[seq.current] : inBeat);
    }
    devLine = message ? { text: message }
      : gap.current !== null && m ? { text: `Next: ${m.titles[seq.current + 1] ?? ''}` }
      : status === 'opening' ? { text: 'Opening the next beat…' }
      : status === 'finished' ? { text: 'All three beats done. Press Restart to run them again.' }
      : t && ['running', 'paused'].includes(status) ? t.line(inBeat) : null;
  }
  return (
    <>
      {(gate === 'tour' || (gate === 'dev' && scene === 'scene2')) && <HighlightLayer marks={marks} />}
      {caption && <div className="pointer-events-none fixed left-1/2 top-16 z-[65] -translate-x-1/2 rounded bg-black/80 px-3 py-1 text-sm text-white" data-dev-caption>{caption}</div>}
      {gate === 'dev' ? (
        <CompactPanel clock={clock} status={status} line={devLine} countdown={countdown} stepN={stepN} stepM={stepM} elapsed={elapsed} total={total}
                      onPlay={play} onPause={pause} onRestart={() => void restart()} onSpeed={speed}
                      scene={scene} onScene={switchScene} onReset={() => void resetScene2()} />
      ) : (
        <TimelinePlayer title="Guided tour" steps={t?.steps ?? []} duration={t?.duration ?? 84} clock={clock} status={status}
                        line={t ? t.line(Math.min(clock.time(), t.duration)) : null} message={message} countdown={countdown}
                        onPlay={play} onPause={pause} onRestart={() => void restart()} onSkip={skip} onSpeed={speed} extra={extra} />
      )}
    </>
  );
}
