import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get, post, ApiError } from '../lib/api';
import {
  INITIAL, OfflineError, dispatch, cacheClear, cacheKeepView, cachePut, cacheGet, clock, getConnection, next, offlineSourceLabel,
  resetConnection, isNetworkError, TimeoutError, devForceOffline, isForcedOffline, probe,
} from '../lib/connection';

describe('the connection state machine', () => {
  it('goes online -> checking on a network failure, and to offline only when the probe fails too', () => {
    const c1 = next(INITIAL, { type: 'network_failure', at: 100 });
    expect(c1).toMatchObject({ state: 'checking', offlineSince: 100 });
    const c2 = next(c1, { type: 'probe_failed', at: 200 });
    expect(c2).toMatchObject({ state: 'offline', offlineSince: 100 }); // the outage began at the first failure
  });

  it('returns online on any response and records when', () => {
    const off = next(next(INITIAL, { type: 'network_failure', at: 100 }), { type: 'probe_failed', at: 200 });
    expect(next(off, { type: 'reachable', at: 900 })).toMatchObject({ state: 'online', offlineSince: null, recoveredAt: 900 });
  });

  it('does not mark a recovery when it was never down', () => {
    expect(next(INITIAL, { type: 'reachable', at: 5 }).recoveredAt).toBeNull();
  });

  it('keeps the first failure time when more failures arrive during the outage', () => {
    const c = next(INITIAL, { type: 'network_failure', at: 100 });
    expect(next(c, { type: 'network_failure', at: 150 }).offlineSince).toBe(100);
  });
});

describe('the one-view cache', () => {
  beforeEach(cacheClear);
  it('drops responses for another run or another slider time, and keeps header requests', () => {
    cachePut('/map/zones?run_id=a&at=t1', 1, 0);
    cachePut('/map/zones?run_id=a&at=t2', 2, 0);
    cachePut('/map/zones?run_id=b&at=t1', 3, 0);
    cachePut('/runs', 4, 0);
    cacheKeepView('a', 't1');
    expect(cacheGet('/map/zones?run_id=a&at=t1')).toBeDefined();
    expect(cacheGet('/map/zones?run_id=a&at=t2')).toBeUndefined();
    expect(cacheGet('/map/zones?run_id=b&at=t1')).toBeUndefined();
    expect(cacheGet('/runs')).toBeDefined();
  });
});

describe('what a source reads offline', () => {
  it('shows a live source as unknown, never its load-time status', () => {
    expect(offlineSourceLabel('live', 'fresh', 0)).toMatchObject({ status: 'unknown', unknown: true });
  });
  it('keeps a replay source at its load-time status, labelled cached', () => {
    expect(offlineSourceLabel('replay', 'fresh', 0)).toEqual({ status: 'fresh', note: 'cached', unknown: false });
  });
  it('writes a missing time as --:--', () => { expect(clock(null)).toBe('--:--'); });
});

describe('errors', () => {
  it('treats a fetch TypeError and our timeout as network failures, and an abort as the page\'s own', () => {
    expect(isNetworkError(new TypeError('Failed to fetch'))).toBe(true);
    expect(isNetworkError(new TimeoutError('/x', 4000))).toBe(true);
    expect(isNetworkError(new DOMException('aborted', 'AbortError'))).toBe(false);
  });
});

describe('api.get and api.post while the server is unreachable', () => {
  const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
  beforeEach(() => { cacheClear(); resetConnection(); vi.stubGlobal('fetch', vi.fn()); });
  afterEach(() => { vi.unstubAllGlobals(); });
  const fetchMock = () => globalThis.fetch as unknown as ReturnType<typeof vi.fn>;

  it('serves the same request\'s last response when the network fails', async () => {
    fetchMock().mockResolvedValueOnce(ok({ n: 1 }));
    expect(await get('/map/zones', { run_id: 'a' })).toEqual({ n: 1 });
    fetchMock().mockRejectedValue(new TypeError('Failed to fetch'));
    expect(await get('/map/zones', { run_id: 'a' })).toEqual({ n: 1 });
    expect(getConnection().state).toBe('checking');
  });

  it('fails with OfflineError for a request not loaded before the outage', async () => {
    fetchMock().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(get('/map/tasks', { run_id: 'a' })).rejects.toBeInstanceOf(OfflineError);
  });

  it('does not treat an HTTP error as offline, and does not serve the cache for it', async () => {
    fetchMock().mockResolvedValueOnce(ok({ n: 1 }));
    await get('/x');
    fetchMock().mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }));
    await expect(get('/x')).rejects.toBeInstanceOf(ApiError);
    expect(getConnection().state).toBe('online');
  });

  it('never sends or queues a POST offline', async () => {
    fetchMock().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(post('/copilot/ask', { question: 'q' })).rejects.toThrow(/needs the server, so nothing was sent/);
  });
});

describe('the dev offline switch (the demo conductor)', () => {
  const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
  beforeEach(() => { cacheClear(); resetConnection(); vi.stubGlobal('fetch', vi.fn()); });
  afterEach(() => { devForceOffline(false); vi.unstubAllGlobals(); });
  const fetchMock = () => globalThis.fetch as unknown as ReturnType<typeof vi.fn>;

  it('goes straight to offline, and a request fails like a refused connection: the cache is served, nothing reaches the network', async () => {
    fetchMock().mockResolvedValueOnce(ok({ n: 1 }));
    expect(await get('/map/zones', { run_id: 'a' })).toEqual({ n: 1 });
    fetchMock().mockClear();
    devForceOffline(true, () => 500);
    expect(isForcedOffline()).toBe(true);
    expect(getConnection()).toMatchObject({ state: 'offline', offlineSince: 500 });
    expect(await get('/map/zones', { run_id: 'a' })).toEqual({ n: 1 }); // the last response, as in a real outage
    await expect(get('/map/tasks', { run_id: 'a' })).rejects.toBeInstanceOf(OfflineError);
    await expect(post('/copilot/ask', { question: 'q' })).rejects.toThrow(/needs the server, so nothing was sent/);
    expect(fetchMock()).not.toHaveBeenCalled();
  });

  it('suppresses the probe, so the state is not flipped back online while it is on', async () => {
    devForceOffline(true);
    fetchMock().mockResolvedValue(ok({ mode: 'template' })); // a reachable server: the probe would find it if it ran
    await probe();
    expect(getConnection().state).toBe('offline');
    expect(fetchMock()).not.toHaveBeenCalled();
  });

  it('ignores an answer that was already in flight, and treats a later failure as an outage at once', () => {
    devForceOffline(true, () => 10);
    dispatch({ type: 'reachable', at: 20 }); // a reply that left before the switch went on
    expect(getConnection().state).toBe('offline');
    resetConnection(); // as if it had been online when the switch went on
    dispatch({ type: 'network_failure', at: 30 });
    expect(getConnection().state).toBe('offline');
  });

  it('recovers on the first real answer once it is turned off', async () => {
    devForceOffline(true);
    fetchMock().mockResolvedValue(ok({ mode: 'template' }));
    devForceOffline(false);
    await vi.waitFor(() => expect(getConnection().state).toBe('online'));
    expect(getConnection().recoveredAt).not.toBeNull();
    expect(isForcedOffline()).toBe(false);
  });
});
