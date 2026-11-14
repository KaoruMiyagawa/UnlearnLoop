import type { SpeakingMetadata } from '../api/speaking';

export interface LocalRecording {
  metadata: SpeakingMetadata;
  blob: Blob;
  pending: boolean;
}

const DATABASE = 'verbatrail-speaking-v1';
const STORE = 'recordings';

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: 'metadata.recording_id' });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error('IndexedDB is blocked'));
  });
}

async function transaction<T>(mode: IDBTransactionMode, operation: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDatabase();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const request = operation(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error ?? new Error('IndexedDB transaction aborted'));
    });
  } finally {
    db.close();
  }
}

export const listRecordings = async (learner: string) =>
  (await transaction<LocalRecording[]>('readonly', store => store.getAll()))
    .filter(item => item.metadata.learner_id === learner);
export const saveRecording = (item: LocalRecording) =>
  transaction<IDBValidKey>('readwrite', store => store.put(item));
export const deleteRecording = (id: string) =>
  transaction<undefined>('readwrite', store => store.delete(id));
