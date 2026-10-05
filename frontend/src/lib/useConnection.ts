// The connection store (lib/connection.ts) as a React hook.

import { useSyncExternalStore } from 'react';
import { type Connection, getConnection, subscribe } from './connection';

export function useConnection(): Connection {
  return useSyncExternalStore(subscribe, getConnection);
}
