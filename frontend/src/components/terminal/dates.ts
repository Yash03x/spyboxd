/**
 * `new Date('2026-07-31')` is UTC midnight, so in any timezone west of
 * Greenwich `.toLocaleDateString()` renders **30 Jul** — every date-only field
 * in the product (watched_date, added_date, first-watch dates) was drifting a
 * day back for a reader in the Americas, a month back when it landed on the
 * 1st, and the calendar heat grid filed every day under the previous weekday.
 *
 * A date-only string names a calendar day, not an instant; parse it as one.
 * Full timestamps are passed through to the native parser untouched.
 */
export function localDate(value: string): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (match) {
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  }
  return new Date(value);
}

/** The day's own YYYY-MM-DD, from local fields — the inverse of localDate. */
export function dateKey(value: Date): string {
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${value.getFullYear()}-${month}-${day}`;
}

export function formatDay(
  value: string,
  options: Intl.DateTimeFormatOptions = { day: '2-digit', month: 'short', year: 'numeric' },
): string {
  return localDate(value).toLocaleDateString('en-GB', options);
}
