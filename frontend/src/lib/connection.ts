// Whether the TideAlert server can be reached, and since when. Offline mode is a CONNECTION state that sits above
// everything the page shows: nothing is recomputed in the browser, the last view loaded stays on screen, and each
// panel says it is cached. Per-source freshness (/map/freshness) is not extended with a new status; it is frozen at
// its load-time value, and for a live run the page shows it as unknown, because a live source's status can't be
// known without the server (docs/offline-mode.md).
//
// Detection: there is no WebSocket in this app (every panel fetches on demand), so the signals are a request that
// fails at the network level (connection refused, DNS, timeout: never an HTTP 4xx/5xx, which is a server error, not
// offline), the browser's online/offline events, and a cheap connection watch that pings /copilot/status.

export type ConnState = 'online' | 'checking' | 'offline';

export interface Connection {
  state: ConnState;
  offlineSince: number | null; // ms epoch: the first network failure of this outage
  lastLoadedAt: number | null; // ms epoch: when the current view last loaded from the server
  recoveredAt: number | null; // ms epoch: when the server was reached again after an outage
}

export type ConnEvent =
  | { type: 'network_failure'; at: number } // a request could not reach the server
  | { type: 'probe_failed'; at: number } // the confirming probe could not reach it either
  | { type: 'reachable'; at: number } // any HTTP response, error statuses included
  | { type: 'view_loaded'; at: number };

export const INITIAL: Connection = { state: 'online', offlineSince: null, lastLoadedAt: null, recoveredAt: null };

/** The state machine, pure: online -> checking on a network failure; checking -> offline when a probe fails too;
 *  any response -> online (recoveredAt set if it was not online). */
export function next(c: Connection, e: ConnEvent): Connection {
  switch (e.type) {
    case 'network_failure':
      return c.state === 'online' ? { ...c, state: 'checking', offlineSince: e.at } : c;
    case 'probe_failed':
      return c.state === 'offline' ? c : { ...c, state: 'offline', offlineSince: c.offlineSince ?? e.at };
    case 'reachable':
      return c.state === 'online' ? c : { ...c, state: 'online', offlineSince: null, recoveredAt: e.at };
    case 'view_loaded':
      return { ...c, lastLoadedAt: e.at };
  }
}

// ---------------------------------------------------------------- the store (one per page)
let conn: Connection = INITIAL;
const listeners = new Set<() => void>();

export const getConnection = (): Connection => conn;
export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function dispatch(e: ConnEvent): void {
  const was = conn;
  conn = next(conn, e);
  if (conn !== was) listeners.forEach((l) => l());
  if (conn.state === 'checking' && was.state !== 'checking') void probe();
}
/** For tests. */
export function resetConnection(): void { conn = INITIAL; }

// ---------------------------------------------------------------- network errors and timeouts
/** Timeouts per request (B): cheap endpoints fail fast so the banner appears quickly on camera; /map/zones is about
 *  6 MB for Harvey and legitimately slow, so it keeps 10 s. */
export const TIMEOUT_MS = 4000;
export const SLOW_TIMEOUT_MS: Record<string, number> = { '/map/zones': 10000 };
export const PROBE_PATH = '/copilot/status';
export const WATCH_INTERVAL_MS = 5000;

export class TimeoutError extends Error {
  constructor(path: string, ms: number) { super(`${path}: no response within ${ms / 1000} s`); this.name = 'TimeoutError'; }
}

/** The request could not reach the server: fetch's TypeError (connection refused, DNS, offline) or our timeout. An
 *  abort by the page itself (a newer request replaced it) is not a network failure. */
export function isNetworkError(e: unknown): boolean {
  return e instanceof TypeError || (e instanceof Error && e.name === 'TimeoutError');
}

/** fetch with a timeout; the caller's signal still aborts it. Rejects with TimeoutError when the time runs out. */
export async function fetchTimed(url: string, init: RequestInit, ms: number, signal?: AbortSignal): Promise<Response> {
  const ctl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; ctl.abort(); }, ms);
  const onAbort = () => ctl.abort();
  signal?.addEventListener('abort', onAbort);
  try {
    return await fetch(url, { ...init, signal: ctl.signal });
  } catch (e) {
    if (timedOut) throw new TimeoutError(url.split('?')[0], ms);
    throw e;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}

let probing = false;
/** One request to the cheapest endpoint: any HTTP response means reachable. */
export async function probe(now: () => number = Date.now): Promise<void> {
  if (probing) return;
  probing = true;
  try {
    await fetchTimed(PROBE_PATH, {}, TIMEOUT_MS);
    dispatch({ type: 'reachable', at: now() });
  } catch (e) {
    if (isNetworkError(e)) dispatch({ type: 'probe_failed', at: now() });
  } finally {
    probing = false;
  }
}

/** The connection watch: a probe every WATCH_INTERVAL_MS (a failure while online enters "checking" and is confirmed
 *  by a second probe), and on the browser's online/offline events. Returns a stop function. */
export function startConnectionWatch(): () => void {
  const tick = async () => {
    if (conn.state === 'online') {
      try {
        await fetchTimed(PROBE_PATH, {}, TIMEOUT_MS);
      } catch (e) {
        if (isNetworkError(e)) dispatch({ type: 'network_failure', at: Date.now() });
      }
    } else {
      await probe();
    }
  };
  const timer = setInterval(() => { void tick(); }, WATCH_INTERVAL_MS);
  const onChange = () => { void tick(); };
  window.addEventListener('online', onChange);
  window.addEventListener('offline', onChange);
  return () => {
    clearInterval(timer);
    window.removeEventListener('online', onChange);
    window.removeEventListener('offline', onChange);
  };
}

// ---------------------------------------------------------------- the one-view response cache
/** The last response for each URL of the current view, kept in memory only (no service worker, no IndexedDB: a
 *  reload while offline is not supported). Served when the same request fails at the network level. */
const cache = new Map<string, { body: unknown; loadedAt: number }>();

export function cachePut(url: string, body: unknown, at: number): void { cache.set(url, { body, loadedAt: at }); }
export function cacheGet(url: string): { body: unknown; loadedAt: number } | undefined { return cache.get(url); }
export function cacheClear(): void { cache.clear(); }

/** Keep one view: drop responses for another run or another slider time. Requests without run_id/at (the header's
 *  /runs, /copilot/status, /data-practices) stay. */
export function cacheKeepView(runId: string, at: string | null): void {
  for (const url of [...cache.keys()]) {
    const q = new URLSearchParams(url.split('?')[1] ?? '');
    if ((q.has('run_id') && q.get('run_id') !== runId) || (q.has('at') && q.get('at') !== at)) cache.delete(url);
  }
}

/** Raised for a request that fails offline: a read that was not loaded before the outage, or a write or question
 *  (which are never cached or queued). */
export class OfflineError extends Error {
  constructor(path: string, write = false) {
    super(write ? `Offline: ${path} needs the server, so nothing was sent. Try again when the connection is back.`
                : `Offline: ${path} was not loaded before the connection dropped.`);
    this.name = 'OfflineError';
  }
}

/** HH:MM in the viewer's local time, for "offline since" and "loaded" labels. */
export function clock(ms: number | null): string {
  if (ms == null) return '--:--';
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** How one source reads in the freshness banner while offline. Live: unknown (its status can't be known without the
 *  server). Replay or scenario: its load-time status, labelled cached (the data is historical; nothing new arrives). */
export function offlineSourceLabel(mode: string, status: string, offlineSince: number | null):
  { status: string; note: string; unknown: boolean } {
  if (mode === 'live') return { status: 'unknown', note: `offline since ${clock(offlineSince)}`, unknown: true };
  return { status, note: 'cached', unknown: false };
}
