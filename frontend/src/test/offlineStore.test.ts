import { beforeEach, describe, expect, it } from 'vitest';
import { INITIAL, cacheClear, cacheGet, cachePut, cacheSize, dispatch, getConnection, next, persistNow, resetConnection, restoreView } from '../lib/connection';
import { type Snapshot, type Store, validSnapshot } from '../lib/offlineStore';

function fakeStore(initial: Snapshot | null = null): Store & { saved: Snapshot | null } {
  const s = { saved: initial, async save(x: Snapshot) { s.saved = x; }, async load() { return s.saved; } };
  return s;
}

beforeEach(() => { cacheClear(); resetConnection(); });

describe('the saved copy of the last view', () => {
  it('saves the view in memory with when it was saved, and restores it into a fresh page', async () => {
    const store = fakeStore();
    cachePut('/runs', { runs: [1] }, 100);
    cachePut('/map/zones?run_id=r&at=t', { features: [] }, 110);
    await persistNow(store, 5000);
    expect(store.saved?.savedAt).toBe(5000);
    expect(store.saved?.entries.map((e) => e[0])).toEqual(['/runs', '/map/zones?run_id=r&at=t']);

    cacheClear(); resetConnection(); // a new page load
    expect(await restoreView(store)).toBe(true);
    expect(cacheGet('/runs')?.body).toEqual({ runs: [1] });
    expect(getConnection()).toMatchObject({ restoredFrom: 5000, lastLoadedAt: 5000, sawServer: false });
  });

  it('saves nothing when there is no view, and restores nothing when there is no copy', async () => {
    const store = fakeStore();
    await persistNow(store, 1);
    expect(store.saved).toBeNull();
    expect(await restoreView(fakeStore())).toBe(false);
    expect(await restoreView(null)).toBe(false);
    expect(getConnection().restoredFrom).toBeNull();
  });

  it('drops restored entries the server did not refresh once the server answers, and keeps the refreshed ones', async () => {
    const store = fakeStore({ version: 1, savedAt: 9, entries: [['/runs', { body: 'old runs', loadedAt: 1 }], ['/map/supply-access?run_id=r', { body: 'old supply', loadedAt: 1 }]] });
    await restoreView(store);
    expect(cacheSize()).toBe(2);
    cachePut('/runs', 'new runs', 50); // the server answered this one
    dispatch({ type: 'reachable', at: 60 });
    expect(cacheGet('/runs')?.body).toBe('new runs');
    expect(cacheGet('/map/supply-access?run_id=r')).toBeUndefined(); // an old copy must not be served later as if current
    expect(getConnection().sawServer).toBe(true);
  });

  it('keeps the restored copy while the server has never answered', async () => {
    await restoreView(fakeStore({ version: 1, savedAt: 9, entries: [['/runs', { body: 'saved', loadedAt: 1 }]] }));
    dispatch({ type: 'network_failure', at: 10 });
    expect(cacheGet('/runs')?.body).toBe('saved');
    expect(getConnection().sawServer).toBe(false); // so the banner says "opened offline", not "offline since"
  });

  it('refuses a snapshot it does not recognise', () => {
    expect(validSnapshot({ version: 2, savedAt: 1, entries: [] })).toBe(false);
    expect(validSnapshot({ version: 1, savedAt: 'x', entries: [] })).toBe(false);
    expect(validSnapshot({ version: 1, savedAt: 1, entries: [['u', { loadedAt: 1 }]] })).toBe(true);
    expect(validSnapshot({ version: 1, savedAt: 1, entries: [['u']] })).toBe(false);
    expect(validSnapshot(null)).toBe(false);
  });

  it('a storage failure leaves the page working with no copy', async () => {
    const broken: Store = { async save() { throw new Error('quota'); }, async load() { throw new Error('blocked'); } };
    cachePut('/runs', 1, 1);
    await expect(persistNow(broken, 1)).resolves.toBeUndefined();
    expect(await restoreView(broken)).toBe(false);
  });

  it('the state machine records the restore without changing the connection state', () => {
    expect(next(INITIAL, { type: 'restored', savedAt: 7 })).toMatchObject({ state: 'online', restoredFrom: 7, lastLoadedAt: 7 });
  });
});
