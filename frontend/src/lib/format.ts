// Display formatting only: these turn API values into text and never produce a value of their own.

export const fmtTime = (iso: string | null | undefined): string =>
  iso ? new Date(iso).toISOString().replace('T', ' ').slice(0, 16) + ' UTC' : '—';

export const fmtAge = (s: number | null | undefined): string =>
  s == null ? '—' : s < 3600 ? `${Math.round(s / 60)} min` : s < 172800 ? `${(s / 3600).toFixed(1)} h` : `${Math.round(s / 86400)} d`;

export const label = (value: string | null | undefined): string => (value ?? '').replace(/_/g, ' ');
