// DEV ONLY (see demo-driver.ts). The demo conductor: a small panel, shown only in a Vite dev build with ?dev=1.
//   Open on Harvey            the Harvey replay at its start, frozen
//   Isolation beat            plays it: cut-off count, Last call, Aerial priority
//   Silence + Listening beat  opens the listening scenario and plays it
//   Offline beat / Recover    force the connection offline (a real-looking network failure, probe suppressed), and bring it back
//   Reset                     stops everything and reloads the page cold
// The driver's log of what each event used is shown and kept on window.__demo for a scripted run. It writes nothing to the
// database: the runs are precomputed. Never part of a production bundle.
import { useEffect, useRef, useState } from 'react';
import { type BeatName, type Driver, type Host, type LogEntry, createDriver } from './demo-driver';

export interface DevHost extends Host {
  open(beat: BeatName): Promise<{ startMs: number; tickTimes: number[] } | null>;
  active(on: boolean): void;
  offline(on: boolean): void;
  connection(): { state: string; offlineSince: number | null };
}

type Opened = { beat: BeatName; startMs: number; tickTimes: number[] };

export default function DevPanel({ host }: { host: DevHost }) {
  const [state, setState] = useState<'idle' | 'opening' | 'ready' | 'running' | 'done'>('idle');
  const [log, setLog] = useState<LogEntry[]>([]);
  const [msg, setMsg] = useState('');
  const [offline, setOffline] = useState(false);
  const opened = useRef<Opened | null>(null);
  const driver = useRef<Driver | null>(null);
  const poll = useRef<number | undefined>(undefined);

  async function open(beat: BeatName): Promise<boolean> {
    setState('opening'); setMsg('opening…'); setLog([]);
    driver.current?.stop();
    const o = await host.open(beat);
    if (!o) { host.active(false); setState('idle'); setMsg(beat === 'isolation' ? 'could not open: no Harvey replay, or no step at its start time' : 'could not open: no listening scenario in this database'); return false; }
    opened.current = { beat, ...o };
    setState('ready'); setMsg(`${beat === 'isolation' ? 'Harvey replay' : 'listening scenario'} frozen at its start (${new Date(o.startMs).toISOString().slice(0, 16).replace('T', ' ')} UTC)`);
    return true;
  }
  async function play(beat: BeatName) {
    if (opened.current?.beat !== beat || state !== 'ready') { if (!(await open(beat))) return; }
    const o = opened.current!;
    driver.current = createDriver(host, o.tickTimes, o.startMs, beat);
    driver.current.start(); setState('running'); setMsg('running');
    window.clearInterval(poll.current);
    poll.current = window.setInterval(() => {
      setLog(driver.current?.log() ?? []);
      if (driver.current && !driver.current.running()) { window.clearInterval(poll.current); setState('done'); setMsg('finished: frozen (no loop). Reset to run again'); }
    }, 300);
  }
  function goOffline(on: boolean) { host.offline(on); setOffline(on); }
  function reset() {
    driver.current?.stop(); window.clearInterval(poll.current);
    host.offline(false); host.pinZone(''); host.active(false);
    // A cold page: the same address a person opens, without the run and time the page wrote into the URL as it played, so the default run
    // opens. Nothing the conductor showed is left, and it wrote nothing to the database.
    window.location.assign(`${window.location.pathname}?dev=1`);
  }

  useEffect(() => {
    (window as unknown as { __demo: unknown }).__demo = {
      open, play, offline: goOffline, reset, log: () => driver.current?.log() ?? [], state: () => state, connection: () => host.connection(),
    };
    return () => { delete (window as unknown as { __demo?: unknown }).__demo; };
  });

  const busy = state === 'opening' || state === 'running';
  const btn = 'rounded border border-fuchsia-400/50 px-2 py-0.5 disabled:opacity-40';
  return (
    <aside className="fixed bottom-2 left-2 z-[70] w-96 rounded border border-fuchsia-400/60 bg-black/90 p-2 text-xs text-fuchsia-100" aria-label="Dev demo conductor">
      <p className="font-bold uppercase tracking-wider">DEV · demo conductor (off in production)</p>
      <div className="mt-1 flex flex-wrap gap-1.5">
        <button type="button" onClick={() => void open('isolation')} disabled={busy} className={btn}>Open on Harvey</button>
        <button type="button" onClick={() => void play('isolation')} disabled={busy} className={btn}>Isolation beat</button>
        <button type="button" onClick={() => void play('listening')} disabled={busy} className={btn}>Silence + Listening beat</button>
        <button type="button" onClick={() => goOffline(true)} disabled={offline} className={btn}>Offline beat</button>
        <button type="button" onClick={() => goOffline(false)} disabled={!offline} className={btn}>Recover</button>
        <button type="button" onClick={reset} className={btn}>Reset</button>
      </div>
      <p className="mt-1 text-fuchsia-200/80">{state}{msg ? `: ${msg}` : ''}{offline ? ' · FORCED OFFLINE (dev switch)' : ''}</p>
      {log.length > 0 && (
        <ul className="custom-scrollbar mt-1 max-h-40 space-y-0.5 overflow-y-auto">
          {log.map((e) => <li key={e.name + e.scriptedAt} className={e.ok ? '' : 'text-orange-300'}>{e.scriptedAt}s {e.name}: {e.ok ? `@${e.firedAt}s` : ''} {e.value}</li>)}
        </ul>
      )}
    </aside>
  );
}
