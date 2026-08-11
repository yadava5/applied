/**
 * Re-dating the demo's fixture rows onto a new calendar day.
 *
 * /demo seeds its store with the UTC day, because that is the only day the
 * server and the hydrating client can agree on (see `useLocalToday.ts`). Once
 * the reader's own day is known and differs, the fixtures have to follow it:
 * the seeds are OFFSETS ("due in 2d", "filed 16 days ago"), and a store dated
 * against one day but bucketed against another shifts every phrase on the page
 * by one for the width of the reader's UTC offset — far enough that Kestrel's
 * "due in 2d" drops out of the pulse strip's `≤2d` cell for readers west of
 * UTC.
 *
 * The rule this module exists to enforce is that re-dating is a MAP over the
 * rows that are there, never a fresh store installed over them. The version it
 * replaced committed pristine fixtures, which discarded whatever the visitor
 * had already done — and no "has anything been touched yet" guard can fix
 * that, because the demo's transports await 300ms before committing, so the
 * guard reads false at exactly the instant it would need to read true. It is
 * also not a once-per-mount event: a visitor who leaves the page open across
 * their own midnight gets a second re-dating, and rebuilding there would reset
 * a board they have been working with.
 *
 * Which fields follow the day:
 *
 *   - `created_at` and `applied_date` are the fixture's filed date. Always
 *     re-dated — nothing a visitor can do changes them.
 *   - `due_at` is re-dated ONLY while `due_source` is `"mail"`, i.e. only while
 *     it is still the fixture's own extracted deadline. `"user"` means a day
 *     someone typed, which is absolute and must not shift; a cleared deadline
 *     has no source and must not come back. Those three cases are why this is
 *     a function with tests rather than a spread.
 *
 * Deliberately import-free, and typed structurally rather than against the
 * API's `Application`, so `node --test` can load it under type stripping — the
 * same rule `age.ts` and `deadline.ts` follow.
 */

/** The only fields re-dating reads or writes. */
export interface DatedRow {
  id: number;
  created_at: string;
  applied_date?: string | null;
  due_at?: string | null;
  due_source?: "user" | "mail" | null;
}

/**
 * `rows`, with their fixture dates taken from `dated` — a lookup of the
 * pristine fixtures built against the new day, by row id. A row with no entry
 * in `dated` (one the visitor added by hand) is returned untouched.
 */
export function redate<T extends DatedRow>(rows: T[], dated: Map<number, DatedRow>): T[] {
  return rows.map((row) => {
    const fresh = dated.get(row.id);
    if (!fresh) return row;
    return {
      ...row,
      created_at: fresh.created_at,
      applied_date: fresh.applied_date ?? null,
      ...(row.due_source === "mail" ? { due_at: fresh.due_at ?? null } : {}),
    };
  });
}

/** The pristine rows of a freshly dated store, indexed by id for {@link redate}. */
export function datedById(rows: DatedRow[]): Map<number, DatedRow> {
  return new Map(rows.map((row) => [row.id, row]));
}
