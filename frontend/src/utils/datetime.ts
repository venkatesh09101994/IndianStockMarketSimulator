/**
 * Helpers for showing backend timestamps (stored/returned in UTC) in IST.
 */

/** Parse a backend timestamp. Naive values (no timezone suffix) are treated as UTC. */
export function parseBackendDate(value?: string | null): Date | null {
  if (!value) return null;
  const hasTimezone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value);
  const date = new Date(hasTimezone ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** e.g. "03:45:12 pm" in IST. */
export function formatISTTime(value?: string | null, withSeconds = true): string {
  const date = parseBackendDate(value);
  if (!date) return '—';
  return date.toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
    hour12: true,
  });
}

/** e.g. "22 Nov 2026, 03:45:12 pm" in IST. */
export function formatISTDateTime(value?: string | null): string {
  const date = parseBackendDate(value);
  if (!date) return '—';
  return date.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });
}

/** IST calendar date as YYYY-MM-DD, used for once-per-day keys. */
export function formatISTDateKey(value?: string | null): string {
  const date = value ? (parseBackendDate(value) || new Date()) : new Date();
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value || '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

/** Human-friendly age, e.g. "12s ago", "4m ago", "2h ago". */
export function timeAgo(value?: string | null): string {
  const date = parseBackendDate(value);
  if (!date) return '';
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
