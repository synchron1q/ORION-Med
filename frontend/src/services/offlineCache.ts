// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
// Browser-side persistence (IndexedDB): last state snapshot, protocols and an
// outbox for crew inputs entered while the HEV-1 core is unreachable.
// Every function degrades to a no-op when IndexedDB is unavailable.
const DB_NAME = "hev1";
const DB_VERSION = 1;

type OutboxItem = { id?: number; kind: "pvt" | "psych"; payload: unknown; created_at: string };

function open(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === "undefined") return Promise.resolve(null);
  return new Promise((resolve) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("kv")) db.createObjectStore("kv");
      if (!db.objectStoreNames.contains("outbox")) db.createObjectStore("outbox", { keyPath: "id", autoIncrement: true });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => resolve(null);
  });
}

async function tx<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T | null> {
  const db = await open();
  if (!db) return null;
  return new Promise((resolve) => {
    try {
      const req = fn(db.transaction(store, mode).objectStore(store));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

export const offlineCache = {
  put: (key: string, value: unknown) => tx("kv", "readwrite", (s) => s.put(value, key)),
  get: <T>(key: string) => tx<T>("kv", "readonly", (s) => s.get(key) as IDBRequest<T>),
  queue: (kind: OutboxItem["kind"], payload: unknown) =>
    tx("outbox", "readwrite", (s) => s.add({ kind, payload, created_at: new Date().toISOString() })),
  async pending(): Promise<OutboxItem[]> {
    return (await tx<OutboxItem[]>("outbox", "readonly", (s) => s.getAll() as IDBRequest<OutboxItem[]>)) ?? [];
  },
  remove: (id: number) => tx("outbox", "readwrite", (s) => s.delete(id)),
};
