// Display formatting only: these turn API values into text and never produce a value of their own.

export const fmtTime = (iso: string | null | undefined): string =>
  iso ? new Date(iso).toISOString().replace('T', ' ').slice(0, 16) + ' UTC' : '—';

/** A source's short name: its gauge ID when it has one (USGS 08074500 continuous -> 08074500), else the name as stored. */
export const sourceId = (name: string): string => name.match(/\d{6,}/)?.[0] ?? name;

/** A source's status for the sources row: just "fresh", or "stale 10.8h" with how old it is, in hours. */
export function sourceStatus(status: string, ageSeconds: number | null | undefined): string {
  if (status === 'no_data') return 'no data';
  if (status === 'event_driven') return 'event-driven';
  if (status === 'stale' && ageSeconds != null) return `stale ${ageSeconds < 3600 ? `${Math.round(ageSeconds / 60)}m` : `${(ageSeconds / 3600).toFixed(1)}h`}`;
  return label(status);
}

export const fmtAge = (s: number | null | undefined): string =>
  s == null ? '—' : s < 3600 ? `${Math.round(s / 60)} min` : s < 172800 ? `${(s / 3600).toFixed(1)} h` : `${Math.round(s / 86400)} d`;

export const label = (value: string | null | undefined): string => (value ?? '').replace(/_/g, ' ');
