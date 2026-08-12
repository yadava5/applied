/**
 * The web side of the Gmail sync cursor: when the board was last built, whether
 * it is stale enough to rebuild, and what a sync actually did.
 *
 * `GET /auth/gmail/status` now carries `last_sync_at`, `has_cursor`,
 * `sync_status` and `sync_error` (backend `GmailStatusResponse`). This module
 * is the ONE reading of those fields, so the sidebar, the settings card and the
 * dashboard's auto-sync can never disagree about "recent".
 *
 * Instants, not calendar dates
 * ----------------------------
 * `lib/dashboard/dates.ts` deliberately never constructs a `Date`: the rows it
 * formats carry *calendar dates* (`applied_date`, `created_at`) whose correct
 * rendering is the day their own characters state. `last_sync_at` is the
 * opposite kind of value — an INSTANT, which only means anything relative to
 * `now` — so it does not route through that helper. It is parsed to epoch
 * milliseconds and compared numerically, which is timezone-independent by
 * construction. The backend emits it with an explicit UTC offset precisely so
 * that parse cannot be read as local time (`_iso_utc`, gmail_oauth.py).
 *
 * Hydration
 * ---------
 * "3 minutes ago" is a function of `now`, and the server's `now` is not the
 * browser's — rendering it during SSR is how this app produced React #418
 * before. So relative time is NEVER computed implicitly: {@link relativeSyncLabel}
 * takes `nowMs` as a required argument, and {@link absoluteSyncLabel} — the
 * label the server renders — is a pure function of the input string's
 * characters (parse to epoch, format with `getUTC*` only; no `Intl`, no
 * `toLocale*`). The two labels are swapped after mount by
 * `components/gmail/LastSynced.tsx`.
 *
 * Dependency-free on purpose (the same rule as `lib/dashboard/review.ts`): no
 * React, no `@/` alias, no generated schema, and no import of another `.ts`
 * module — `tests/unit/` loads this file directly under Node's built-in type
 * stripping, which needs explicit `.ts` specifiers that `tsc` rejects without
 * `allowImportingTsExtensions`.
 */

/** The counts `POST /gmail/sync` answers with (backend `SyncResponse`). */
export interface SyncCounts {
  /** Application rows this sync created. */
  created: number;
  /** Existing rows it advanced or refreshed. */
  updated: number;
  /** Total rows the user has after the sync. */
  applications: number;
  /** Messages the sync looked at. */
  scanned: number;
}

/**
 * How old "last synced" may get before the dashboard rebuilds the board by
 * itself: 30 minutes.
 *
 * The rule this replaces was `total === 0` — an account with rows never
 * auto-synced, so new mail only ever appeared if the user pressed Re-sync,
 * which is the complaint. 30 minutes is chosen against the cost model: a stale
 * visit now costs ONE `users.history.list` delta (the sync is incremental
 * whenever a cursor is on file), not a 12-month/750-message re-scan, and the
 * ceiling is one such call per window per user however much they navigate.
 * It also sits ABOVE the 10-minute per-tab `sessionStorage` cooldown in
 * `GmailSyncTrigger`, so this threshold is the gate that actually decides —
 * a shorter one would be decorative.
 */
export const STALE_AFTER_MS = 30 * 60 * 1000;

/** Shown wherever a connection has never completed a sync. */
export const NOT_SYNCED_YET = "not synced yet";

/** A full date+time — the only shape that is an instant. `2026-08-10T19:26:13`. */
const INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

/** A trailing zone designator: `Z`, `+00:00`, `-0500`. */
const HAS_ZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i;

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const WEEK_MS = 7 * DAY_MS;

/**
 * Parse `last_sync_at` to epoch milliseconds, or `null` if it is absent or not
 * an instant.
 *
 * A string with no zone is read as UTC rather than local. The backend always
 * sends one, but the failure mode if it ever stopped is silent and directional
 * — the owner in US Eastern would be told a sync that just finished happened
 * "in 4 hours" — so the defence is cheap and worth having. A bare calendar date
 * (`2026-08-10`) is rejected outright: that is a `dates.ts` value, not an
 * instant, and guessing a time of day for it would invent precision.
 */
export function parseInstant(value: string | null | undefined): number | null {
  if (typeof value !== "string") return null;
  const raw = value.trim();
  if (!INSTANT.test(raw)) return null;
  const ms = Date.parse(HAS_ZONE.test(raw) ? raw : `${raw}Z`);
  return Number.isFinite(ms) ? ms : null;
}

/**
 * Should the board be rebuilt from Gmail?
 *
 * Never synced, or a timestamp we cannot read, counts as stale — the honest
 * answer to "we don't know when this last ran" is to run it. A stamp in the
 * FUTURE is not stale: that is clock skew between the browser and the backend,
 * and treating it as stale would sync on every visit for as long as the skew
 * lasts. Re-firing is bounded regardless by the caller's cooldown.
 */
export function isStale(
  lastSyncAt: string | null | undefined,
  nowMs: number,
  thresholdMs: number = STALE_AFTER_MS,
): boolean {
  const ms = parseInstant(lastSyncAt);
  if (ms === null) return true;
  if (ms > nowMs) return false;
  return nowMs - ms >= thresholdMs;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/**
 * The absolute instant, in UTC — `2026-08-10 19:26 UTC`.
 *
 * Deliberately built from `getUTC*` and nothing else. `toLocaleString` /
 * `Intl` would render differently on the UTC server and the reader's browser,
 * which is the hydration mismatch this whole module exists to avoid, and would
 * also make the string depend on the machine's locale data.
 */
export function absoluteInstant(value: string | null | undefined): string | null {
  const ms = parseInstant(value);
  if (ms === null) return null;
  const d = new Date(ms);
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
  );
}

function plural(n: number, unit: string): string {
  return `${n} ${unit}${n === 1 ? "" : "s"} ago`;
}

/**
 * How long ago `value` was, relative to `nowMs` — "3 minutes ago".
 *
 * `nowMs` is a required parameter, not `Date.now()` read internally: that is
 * what makes this function safe to unit-test and impossible to call by accident
 * during a server render.
 */
export function relativeSince(value: string | null | undefined, nowMs: number): string | null {
  const ms = parseInstant(value);
  if (ms === null) return null;

  const diff = nowMs - ms;
  // Ahead of us (clock skew) or within the last minute — both read as "just now".
  if (diff < MINUTE_MS) return "just now";
  if (diff < HOUR_MS) return plural(Math.floor(diff / MINUTE_MS), "minute");
  if (diff < DAY_MS) return plural(Math.floor(diff / HOUR_MS), "hour");
  if (diff < WEEK_MS) return plural(Math.floor(diff / DAY_MS), "day");
  // Past a week, "37 days ago" is less useful than the date itself.
  return `on ${absoluteInstant(value)}`;
}

/**
 * The label the SERVER renders (and the browser's first render reproduces
 * exactly): absolute, and a pure function of the input's characters.
 */
export function absoluteSyncLabel(value: string | null | undefined): string {
  const absolute = absoluteInstant(value);
  return absolute === null ? NOT_SYNCED_YET : `last synced ${absolute}`;
}

/** The label the browser swaps in after mount, once `now` is knowable. */
export function relativeSyncLabel(value: string | null | undefined, nowMs: number): string {
  const relative = relativeSince(value, nowMs);
  return relative === null ? NOT_SYNCED_YET : `last synced ${relative}`;
}

/**
 * The same fact for tight rows — "synced 3 minutes ago". Used where the Sync
 * button sits right beside it and already carries the noun; the full sentence
 * stays the default everywhere else.
 */
export function compactSyncLabel(value: string | null | undefined, nowMs: number): string {
  const relative = relativeSince(value, nowMs);
  return relative === null ? NOT_SYNCED_YET : `synced ${relative}`;
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

/**
 * What a sync actually did, in the user's terms — "3 filed, 1 already known".
 *
 * `created` is new application rows; `updated` is rows this sync advanced or
 * refreshed, which from the user's side is mail the board already knew about.
 * The zero case names `scanned` because that is the only case where "we looked
 * and there was nothing" is the useful thing to say — a mine that found no
 * *filable* mail must not read as a failure.
 *
 * Tolerant of a partial body on purpose: this reads a `fetch().json()` result,
 * and a proxy that answered 200 with something unexpected should degrade to an
 * honest sentence rather than "undefined filed".
 */
export function filedSummary(outcome: Partial<SyncCounts> | null | undefined): string {
  const data = outcome ?? {};
  const created = count(data.created);
  const updated = count(data.updated);
  const scanned = count(data.scanned);

  if (created > 0 && updated > 0) return `${created} filed, ${updated} already known`;
  if (created > 0) return `${created} filed`;
  if (updated > 0) return `nothing new · ${updated} already known`;
  return scanned > 0 ? `nothing to file · ${scanned} scanned` : "nothing to file";
}
