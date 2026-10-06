// DEV ONLY (see demo-driver.ts). A small panel, shown only in a Vite dev build with ?dev=1: Arm the scene (open the Harvey replay at
// its start, supply-access layer, no lead time), Start the driver, Reset. The driver's log of what each event used is shown and
// kept on window.__demo for a scripted run. Never part of a production bundle.
import { useEffect, useRef, useState } from 'react';
import { type Driver, type Host, type LogEntry, createDriver } from './demo-driver';

export interface DevHost extends Host {
  prepare(): Promise<{ startMs: number; tickTimes: number[] } | null>;
  active(on: boolean): void;
}

export default function DevPanel({ host }: { host: DevHost }) {
  const [state, setState] = useState<'idle' | 'arming' | 'ready' | 'running' | 'done'>('idle');
  const [log, setLog] = useState<LogEntry[]>([]);
  const [msg, setMsg] = useState('');
  const armed = useRef<{ startMs: number; tickTimes: number[] } | null>(null);
  const driver = useRef<Driver | null>(null);

  async function arm() {
    setState('arming'); setMsg('arming…'); setLog([]);
    driver.current?.stop();
    host.active(true);
    const a = await host.prepare();
    if (!a) { host.active(false); setState('idle'); setMsg('could not find a start: no Harvey replay with Cases'); return; }
    armed.current = a; setState('ready'); setMsg(`frozen at the scene start (${new Date(a.startMs).toISOString().slice(0, 16).replace('T', ' ')} UTC)`);
  }
  function start() {
    if (!armed.current) return;
    driver.current = createDriver(host, armed.current.tickTimes, armed.current.startMs);
    driver.current.start(); setState('running'); setMsg('running');
    const poll = window.setInterval(() => {
      setLog(driver.current?.log() ?? []);
      if (driver.current && !driver.current.running()) { window.clearInterval(poll); setState('done'); setMsg('finished: frozen (no loop). Reset to run again'); }
    }, 300);
  }
  function reset() { driver.current?.stop(); host.active(false); host.pinZone(''); setState('idle'); setMsg(''); setLog([]); }

  useEffect(() => {
    (window as unknown as { __demo: unknown }).__demo = { arm, start, log: () => driver.current?.log() ?? [], state: () => state };
    return () => { delete (window as unknown as { __demo?: unknown }).__demo; };
  });

  return (
    <aside className="fixed bottom-2 left-2 z-[70] w-80 rounded border border-fuchsia-400/60 bg-black/90 p-2 text-xs text-fuchsia-100" aria-label="Dev demo driver">
      <p className="font-bold uppercase tracking-wider">DEV · demo driver (off in production)</p>
      <div className="mt-1 flex gap-1.5">
        <button type="button" onClick={arm} disabled={state === 'arming' || state === 'running'} className="rounded border border-fuchsia-400/50 px-2 py-0.5 disabled:opacity-40">Arm</button>
        <button type="button" onClick={start} disabled={state !== 'ready'} className="rounded border border-fuchsia-400/50 px-2 py-0.5 disabled:opacity-40">Start</button>
        <button type="button" onClick={reset} className="rounded border border-fuchsia-400/50 px-2 py-0.5">Reset</button>
      </div>
      <p className="mt-1 text-fuchsia-200/80">{state}{msg ? `: ${msg}` : ''}</p>
      {log.length > 0 && (
        <ul className="custom-scrollbar mt-1 max-h-40 space-y-0.5 overflow-y-auto">
          {log.map((e) => <li key={e.name + e.scriptedAt} className={e.ok ? '' : 'text-orange-300'}>{e.scriptedAt}s {e.name}: {e.ok ? `@${e.firedAt}s` : ''} {e.value}</li>)}
        </ul>
      )}
    </aside>
  );
}
