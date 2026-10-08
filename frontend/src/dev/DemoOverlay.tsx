// DEV ONLY (?demo=1). The Full Demo's panel: [Check] [Play / Pause] [Restart], a read-along strip, the pre-flight result, and the six named
// resume points under "Checkpoints". It is a small tab ("▶ Demo") while the sequence plays, so nothing of it is on screen during the demo;
// it opens again at the end, or on a click. The tour and Scene 2 are loaded here, by dynamic import, only for this gate.
import { useEffect, useRef, useState } from 'react';
import type { CheckItem, FullDemo } from './demo';
import { HighlightLayer, type Mark } from './DevOverlay';
import type { DevHostBase } from './conductor';
import type { TourData } from './DevOverlay';
import { PlayerClock, fmtClock } from './TimelinePlayer';

export default function DemoOverlay({ host, tour }: { host: DevHostBase; tour: TourData }) {
  const clock = useRef(new PlayerClock()).current;
  const demo = useRef<FullDemo | null>(null);
  const mods = useRef<{ CHECKPOINTS: typeof import('./demo').CHECKPOINTS; DEMO_DURATION_S: number; TOTAL_STEPS: number; preflight: typeof import('./demo').preflight; resetDemo: typeof import('./scene2').resetDemo; scene: import('./scene2').Scene2; tour: import('./tour').Tour } | null>(null);
  const [marks, setMarks] = useState<Mark[]>([]);
  const [caption, setCaption] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);
  const [checks, setChecks] = useState<CheckItem[] | null>(null);
  const [checking, setChecking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [, force] = useState(0);
  const [ready, setReady] = useState(false);
  const checkedOk = checks !== null && checks.every((c) => c.ok);

  // Build the tour, Scene 2 and the composite once, then open the first frame and run the pre-flight check.
  useEffect(() => {
    let dead = false;
    void (async () => {
      const [d, t, s] = await Promise.all([import('./demo'), import('./tour'), import('./scene2')]);
      if (dead) return;
      const map = () => (window as unknown as { __map?: import('./tour').MapLike }).__map ?? null;
      const tourTool = t.createTour({ start: tour.start, map, extent: tour.extent, cutOffPoints: tour.cutOffPoints }, { highlight: (items) => setMarks(items), caption: setCaption }, clock);
      const offset = { time: () => clock.time() - d.SCENE2_AT };
      const sceneTool = s.createScene2(host.scene2, { highlight: (items) => setMarks(items) }, offset);
      const dh: import('./demo').DemoHost = {
        openHarvey: () => host.demo.openHarvey(),
        openMixed: async () => !!(await host.scene2.open()),
        caption: (text) => host.caption(text ?? ''),
        scrollTop: () => window.scrollTo({ top: 0, behavior: 'auto' }),
        stopMap: () => (map() as { stop(): void } | null)?.stop(),
        log: (l) => console.info(l),
      };
      demo.current = d.createFullDemo({ tour: tourTool, scene: sceneTool, clock, host: dh });
      mods.current = { CHECKPOINTS: d.CHECKPOINTS, DEMO_DURATION_S: d.DEMO_DURATION_S, TOTAL_STEPS: d.TOTAL_STEPS, preflight: d.preflight, resetDemo: s.resetDemo, scene: sceneTool, tour: tourTool };
      setReady(true);
      await restart();
    })();
    return () => { dead = true; demo.current?.stop(); };
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      const d = demo.current;
      if (!d) return;
      const before = d.status();
      d.tick();
      if (before === 'running' && d.status() === 'finished') setExpanded(true); // the end: open up, so the operator can Restart or jump
      force((n) => n + 1);
    }, 100);
    return () => window.clearInterval(id);
  }, []);

  async function runCheck() {
    if (!mods.current) return;
    setChecking(true); setMessage(null);
    try { setChecks(await mods.current.preflight()); } finally { setChecking(false); }
  }
  async function restart() {
    const d = demo.current;
    if (!d) return;
    setMarks([]); setCaption(null); setMessage(null);
    const why = await d.prepare();
    if (why) setMessage(why);
    await runCheck();
  }
  async function reset() {
    if (!mods.current) return;
    setMessage(await mods.current.resetDemo(host.scene2));
    await runCheck();
  }
  async function jump(id: Parameters<FullDemo['jump']>[0]) {
    const why = await demo.current?.jump(id);
    setMessage(why ?? null);
    setMarks([]);
  }
  function play() {
    const d = demo.current;
    if (!d) return;
    if (d.status() === 'ready' && checkedOk) { setExpanded(false); d.play(); } else if (d.status() === 'paused') d.play();
    force((n) => n + 1);
  }

  useEffect(() => {
    (window as unknown as { __demo: unknown }).__demo = {
      status: () => demo.current?.status() ?? 'idle', clock: () => clock.time(), line: () => demo.current?.line(clock.time()) ?? null,
      step: () => demo.current?.stepAt(clock.time()) ?? 0, jump, play, pause: () => demo.current?.pause(), restart, check: runCheck, reset,
      checks: () => checks, log: () => demo.current?.log() ?? [], sceneLog: () => mods.current?.scene.log() ?? [], tourReport: () => mods.current?.tour.report() ?? [], marks: () => marks.map((m) => m.label),
      expanded: () => expanded, caption: () => caption, message: () => message,
    };
    return () => { delete (window as unknown as { __demo?: unknown }).__demo; };
  });

  const d = demo.current;
  const status = d?.status() ?? 'idle';
  const t = Math.min(clock.time(), mods.current?.DEMO_DURATION_S ?? 203);
  const line = d?.line(t) ?? null;
  const running = status === 'running';
  const btn = 'rounded border border-fuchsia-400/50 px-2.5 py-0.5 disabled:opacity-40';
  const canPlay = status === 'paused' || (status === 'ready' && checkedOk);

  return (
    <>
      <HighlightLayer marks={marks} />
      {caption && <div className="pointer-events-none fixed left-1/2 top-16 z-[65] -translate-x-1/2 rounded bg-black/80 px-3 py-1 text-sm text-white" data-dev-caption>{caption}</div>}
      {!expanded ? (
        <button type="button" onClick={() => setExpanded(true)} aria-label="Open the Full Demo controls" data-dev-player data-demo-collapsed
                className="fixed bottom-2 right-2 z-[70] rounded border border-fuchsia-400/60 bg-black/92 px-2 py-1 text-xs font-bold text-fuchsia-100">▶ Demo {fmtClock(t)}</button>
      ) : (
        <aside className="fixed bottom-2 right-2 z-[70] w-80 rounded border border-fuchsia-400/60 bg-black/92 text-xs text-fuchsia-100" aria-label="Full Demo" data-dev-player data-demo-panel>
          <button type="button" onClick={() => setExpanded(false)} aria-expanded="true" title="Collapse"
                  className="flex w-full items-center justify-between border-b border-fuchsia-400/30 px-2 py-0.5 text-left text-[10px] font-bold uppercase tracking-wider">
            <span>▼ Full Demo</span><span className="font-normal normal-case text-fuchsia-200/70">dev only · {status}</span>
          </button>
          <div className="space-y-1 p-1.5">
            <div className="max-h-[4.2rem] min-h-[3.2rem] overflow-y-auto text-[13px] leading-snug text-white" aria-live="polite" data-dev-line>
              {message ? <span className="text-orange-200">{message}</span>
                : line && status !== 'ready' && status !== 'idle' ? <>{line.text}{line.skipped ? <span className="text-fuchsia-200/60"> (skipped)</span> : null}</>
                : <span className="text-fuchsia-200/60">{status === 'preparing' ? 'Opening…' : checks === null ? 'Press Check.' : checkedOk ? 'All checks pass. Press Play.' : 'Fix the red item, then Check again.'}</span>}
            </div>
            <div className="text-[10px] text-fuchsia-200/60">step {d?.stepAt(t) ?? 0} of {mods.current?.TOTAL_STEPS ?? 32} · {fmtClock(t)} / {fmtClock(mods.current?.DEMO_DURATION_S ?? 203)}</div>
            <div className="flex gap-1.5">
              <button type="button" onClick={() => void runCheck()} disabled={checking || running || !ready} className={btn}>{checking ? 'Checking…' : 'Check'}</button>
              <button type="button" onClick={running ? () => { d?.pause(); force((n) => n + 1); } : play} disabled={!running && !canPlay} className={btn}>{running ? 'Pause' : 'Play'}</button>
              <button type="button" onClick={() => void restart()} disabled={!ready || status === 'preparing'} className={btn}>Restart</button>
            </div>
            {checks && (
              <ul className="space-y-0.5" aria-label="Pre-flight check">
                {checks.map((c) => (
                  <li key={c.id} className={c.ok ? 'text-green-300' : 'text-red-300'} data-check={c.id} data-ok={c.ok}>
                    <b>{c.ok ? 'PASS' : 'FAIL'}</b> {c.label}: <span className={c.ok ? 'text-fuchsia-200/70' : ''}>{c.detail}</span>
                    {!c.ok && c.fix ? <> — {c.fix}{c.reset ? <button type="button" onClick={() => void reset()} className="ml-1 rounded border border-red-300/60 px-1.5 text-red-100">Reset</button> : null}</> : null}
                  </li>
                ))}
              </ul>
            )}
            <details>
              <summary className="cursor-pointer text-fuchsia-200/80">Checkpoints ▾</summary>
              <div className="mt-1 grid grid-cols-2 gap-1" data-checkpoints>
                {(mods.current?.CHECKPOINTS ?? []).map((c) => (
                  <button key={c.id} type="button" onClick={() => void jump(c.id)} disabled={status === 'preparing'} data-checkpoint={c.id}
                          className="rounded border border-fuchsia-400/40 px-1.5 py-0.5 text-left disabled:opacity-40">{c.label}</button>
                ))}
              </div>
            </details>
          </div>
        </aside>
      )}
    </>
  );
}
