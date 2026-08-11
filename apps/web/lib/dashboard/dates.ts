/**
 * The dashboard's ONE date formatter — deliberately `Date`-free.
 *
 * The rows we render carry two differently-shaped timestamps: `applied_date`
 * is date-only (`"2026-08-10"`, which `new Date()` reads as UTC midnight) and
 * `created_at` is a naive local timestamp (`"2026-08-10T21:19:13"`, no `Z`,
 * which `new Date()` reads in the RUNTIME's zone). Formatting either through
 * `Date`/`toLocaleDateString` therefore produced two different answers for one
 * calendar day — "Aug 9" on a card next to "Aug 10, 2026" in the feed — and,
 * because the server runs in UTC while the browser runs in the user's zone, a
 * text hydration mismatch (minified React error #418) in production.
 *
 * So we never construct a `Date` and never consult a locale: we read the
 * calendar parts straight out of the string and name the month ourselves. The
 * output is a pure function of the characters in the input, which makes it
 * identical on the server and in the browser, in every timezone.
 *
 * The trade-off is explicit: a string that carries a zone (`...Z`, `+05:30`)
 * is rendered as the calendar day IT states, not as the reader's local day.
 * That is the same rule for every surface, which is the property we need.
 */

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

/** Leading `YYYY-MM-DD` of an ISO date or timestamp; anything after it is ignored. */
const CALENDAR_PREFIX = /^(\d{4})-(\d{2})-(\d{2})(?:[T ]|$)/;

/** What every formatter here renders when there is no usable date. */
export const NO_DATE = "—";

interface CalendarDate {
  year: number;
  month: number;
  day: number;
}

/** Parse the calendar parts, or `null` for absent/malformed/out-of-range input. */
function calendarParts(value: string | null | undefined): CalendarDate | null {
  if (typeof value !== "string") return null;
  const match = CALENDAR_PREFIX.exec(value.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12) return null;
  if (day < 1 || day > 31) return null;
  return { year, month, day };
}

/** "Aug 10" — the compact form for cards and dense rows. */
export function shortDate(value: string | null | undefined): string {
  const parts = calendarParts(value);
  return parts ? `${MONTHS[parts.month - 1]} ${parts.day}` : NO_DATE;
}

/** "Aug 10, 2026" — the long form for the activity feed. */
export function longDate(value: string | null | undefined): string {
  const parts = calendarParts(value);
  return parts ? `${MONTHS[parts.month - 1]} ${parts.day}, ${parts.year}` : NO_DATE;
}

/**
 * The single "when was this filed" field, so the board and the activity feed
 * can never disagree: the real received date from the mail, falling back to the
 * row's own creation timestamp. Structurally typed so this module stays free of
 * the generated API schema (and of any import cycle with `summary.ts`).
 */
export function filedAt(app: { applied_date?: string | null; created_at: string }): string {
  return app.applied_date ?? app.created_at;
}
