// The browser-side copy of the last view, so the page can open with no connection. One snapshot: every response of the
// view on screen (runs, zones, tasks, Cases, needs...), exactly as the server sent them, with when they were saved. It
// is read-only: nothing is recomputed from it, and it is replaced by the next view that loads from the server.
//
// It is stored in the browser's IndexedDB (the zones answer alone is several MB, past localStorage's limit). Browsers
// can refuse or clear it (private windows, cleared site data): then there is simply no copy and the page says so.

export interface Snapshot {
  version: 1;
  savedAt: number; // ms epoch: when the view was saved
  entries: [string, { body: unknown; loadedAt: number }][];
}

export interface Store {
  save(s: Snapshot): Promise<void>;
  load(): Promise<Snapshot | null>;
}

export function validSnapshot(x: unknown): x is Snapshot {
  const s = x as Snapshot | null;
  return !!s && s.version === 1 && typeof s.savedAt === 'number' && Array.isArray(s.entries)
    && s.entries.every((e) => Array.isArray(e) && typeof e[0] === 'string' && !!e[1] && typeof e[1].loadedAt === 'number');
}

const DB = 'tidealert-offline';
const OBJECTS = 'view';
const KEY = 'last';

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(OBJECTS);
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

/** The IndexedDB store, or null where the browser has none (or this is not a browser). */
export function idbStore(): Store | null {
  if (typeof indexedDB === 'undefined') return null;
  return {
    async save(s) {
      const db = await open();
      await new Promise<void>((resolve, reject) => {
        const t = db.transaction(OBJECTS, 'readwrite');
        t.objectStore(OBJECTS).put(s, KEY);
        t.oncomplete = () => resolve();
        t.onerror = () => reject(t.error);
      });
      db.close();
    },
    async load() {
      const db = await open();
      const out = await new Promise<unknown>((resolve, reject) => {
        const r = db.transaction(OBJECTS, 'readonly').objectStore(OBJECTS).get(KEY);
        r.onsuccess = () => resolve(r.result);
        r.onerror = () => reject(r.error);
      });
      db.close();
      return validSnapshot(out) ? out : null;
    },
  };
}
