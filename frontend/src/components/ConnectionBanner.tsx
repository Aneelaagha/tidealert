// The connection state, above everything else on the page. Shown only while the server can't be reached, and for
// the moment it comes back. Nothing here recomputes a value: the panels keep what was last loaded.

import { WifiOff } from 'lucide-react';
import { type Connection, clock, stamp } from '../lib/connection';

export function ConnectionBanner({ conn, asOf }: { conn: Connection; asOf?: string | null }) {
  if (conn.state === 'online') return null;
  const offline = conn.state === 'offline';
  return (
    <div role="status" aria-live="polite"
         className={`flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-6 py-1.5 text-xs ${
           offline ? 'border-danger-red/40 bg-red-950/40 text-red-200' : 'border-warning-orange/40 bg-orange-950/30 text-orange-200'}`}>
      <WifiOff className="h-3.5 w-3.5 shrink-0" />
      {offline && conn.restoredFrom && !conn.sawServer ? (
        <>
          <b>Opened offline: read-only.</b>
          <span>This is the copy of the last view saved at {stamp(conn.restoredFrom)}, as of {asOf ?? 'the time shown'}. Nothing here is current,
            nothing can be changed, and questions to the copilot are not sent.</span>
        </>
      ) : offline ? (
        <>
          <b>Offline since {clock(conn.offlineSince)}.</b>
          <span>Showing the view loaded at {clock(conn.lastLoadedAt)}; every panel is cached and read-only. Nothing is
            recomputed here. Questions to the copilot, task actions, needs and offers need the server and will not be sent.</span>
        </>
      ) : <b>Can't reach the server. Checking the connection…</b>}
    </div>
  );
}
