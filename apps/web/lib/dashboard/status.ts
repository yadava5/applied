/**
 * The statuses an application may hold — the ONE definition the UI reads from.
 *
 * The bug this exists to make impossible: `ApplicationCard` carried its own
 * literal `STATUS_CHOICES` array containing `assessment`, a value the API has
 * never accepted. Choosing it answered
 *
 *   422 · Input should be 'applied', 'interviewing', 'offered', 'rejected',
 *         'accepted', 'withdrawn' or 'ghosted'
 *
 * while the API's own `ghosted` was missing from the dropdown entirely. Two
 * lists drifted because there were two lists. There is now one, and the
 * component imports it rather than restating it.
 *
 * It mirrors `ApplicationStatus` in `backend/jobtracker/database/models.py` —
 * the enum the PATCH validates against — in ITS declaration order, which is
 * also the order `GET /applications/statuses` serves. Matching that order is
 * not cosmetic: it is what lets a later test assert this list equals the
 * endpoint's outright, instead of comparing sorted sets and missing a member.
 *
 * `assessment` is PRESENT, as of 2026-08-12, and that is a reversal: it used to
 * be absent here on the grounds that it was only a classifier category that
 * mapped to `interviewing`. It is a stage now — the decision and its reasons
 * are in `CATEGORY_TO_STATUS` in `backend/jobtracker/database/models.py`, and
 * `summary.ts` gives it a column of its own rather than folding it in. Note
 * what that means for this file's own history: the card's old `<select>` was
 * offering the right word for the wrong reason, and the fix was still to delete
 * the second list, not to keep it.
 *
 * Reading `GET /applications/statuses` at runtime would close the loop
 * entirely, but it needs a proxy route (`app/api/...`) to carry the JWT, so it
 * is a follow-up; until then the unit tests assert this list against the exact
 * values the API's own 422 names.
 *
 * Deliberately free of imports and of React so `node --test` can load it
 * directly under type stripping — same rule as `review.ts` and `dates.ts`.
 */

/** Every status the API's PATCH accepts, in the enum's own declaration order. */
export const APPLICATION_STATUSES = [
  "applied",
  "assessment",
  "interviewing",
  "offered",
  "rejected",
  "accepted",
  "withdrawn",
  "ghosted",
] as const;

export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number];

/** Narrowing guard — the only sanctioned way to ask "would the API take this?". */
export function isApplicationStatus(value: unknown): value is ApplicationStatus {
  return typeof value === "string" && (APPLICATION_STATUSES as readonly string[]).includes(value);
}

/** Rows arrive with whatever the classifier wrote; normalize before comparing. */
export function normalizeStatus(status: string | null | undefined): string {
  return typeof status === "string" ? status.trim().toLowerCase() : "";
}

export interface StatusOption {
  value: string;
  label: string;
  /**
   * True for a value the API would reject. Such a value only ever appears
   * because the row already holds it (a legacy or classifier-written status):
   * it is rendered so the control shows the row's REAL state, and disabled so
   * it can never be submitted. The old code substituted "applied" for anything
   * unrecognized, i.e. the card displayed a stage the row was not at.
   */
  disabled: boolean;
}

/**
 * The options the stage control should render for a row currently at `current`.
 *
 * Always the canonical list; plus, when the row holds something outside it, a
 * leading disabled entry naming what the row actually is.
 */
export function statusOptions(current: string | null | undefined): StatusOption[] {
  const options: StatusOption[] = APPLICATION_STATUSES.map((value) => ({
    value,
    label: value,
    disabled: false,
  }));
  const raw = normalizeStatus(current);
  if (!isApplicationStatus(raw)) {
    options.unshift({ value: raw, label: `${raw || "unknown"} (legacy)`, disabled: true });
  }
  return options;
}

/** The value the stage control must show for `current` — never a substitute. */
export function statusSelectValue(current: string | null | undefined): string {
  return normalizeStatus(current);
}
