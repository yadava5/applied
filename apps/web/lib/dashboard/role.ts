/**
 * The role a human types in, and the rules around it — issue #72.
 *
 * Nothing in the Gmail path can supply a role. `cloud/gmail_client.py`
 * batch-fetches with `format=metadata`, so no message body is ever read, and
 * the ATS acknowledgement subjects that ARE read name the employer rather than
 * the job: "Thanks for applying to Supabase", "Thank you for applying with
 * MotherDuck!", "Thank you for applying to Anthropic" all extract nothing. So
 * `position` is `""` on every auto-filed row, permanently, and the only way one
 * ever gets a title is for the person who applied to type it.
 *
 * That makes this module's job narrow and mostly about restraint. It must never
 * produce a role — no placeholder, no guess from the employer, no plausible
 * default — because a title nobody typed, sitting in the field where a real one
 * goes, is indistinguishable from a real one the moment the page is reloaded.
 * The absence is honest; a filled-in guess is not.
 *
 * Logic lives here rather than in the component for the reason `deadline.ts`
 * and `rowActions.ts` do: `.tsx` cannot load under Node's type stripping, so
 * anything worth asserting lives in a plain `.ts` module and the component
 * takes its behaviour from here and nowhere else. See
 * `tests/unit/role-fill.test.mjs`.
 */

/**
 * The ceiling, matching `_MAX_ROLE_LEN` in
 * `backend/jobtracker/cloud/applications.py`. `position` is unbounded `TEXT`
 * and nothing downstream truncates it, so the limit is a real one rather than a
 * display convenience — a pasted job description would otherwise go straight
 * into the column. Kept identical on both sides deliberately: a looser client
 * turns the server's 422 into an unexplained failure, a tighter one refuses
 * titles the API would have accepted.
 */
export const MAX_ROLE_LENGTH = 200;

/**
 * What a draft actually means. `null` is a CLEAR — a field holding three spaces
 * renders as filled and is exactly the invented data #72 exists to prevent.
 *
 * Only the ends are trimmed. Interior spacing is the title's own ("Software
 * Development Engineer, AWS Data Services"), and collapsing it would be this
 * module editing a human's words.
 */
export function normalizeRoleDraft(draft: string): string | null {
  const trimmed = draft.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * Why a draft cannot be sent, or `null` when it can. A blank draft is not an
 * error — it is the clear, which is a legitimate thing to want.
 */
export function roleDraftError(draft: string): string | null {
  const normalized = normalizeRoleDraft(draft);
  if (normalized === null) return null;
  return normalized.length > MAX_ROLE_LENGTH ? ROLE_TOO_LONG : null;
}

/**
 * The provenance qualifier, and the only one there is. `position_source` holds
 * `"user"` for a typed title and NULL for everything else, because "the sync
 * owns this field" is the only other state and it is not a claim worth printing
 * beside an empty role. Anything unrecognised returns `null` rather than being
 * dressed up — the same rule `dueSourceLabel` follows, for the same reason.
 */
export function roleSourceLabel(source: string | null | undefined): string | null {
  return source === "user" ? "set by you" : null;
}

// --- Copy (here so the component can never drift from what is tested) -------

/** No example title appears in any of these. A suggestion is an invention. */
export const ROLE_ADD_LABEL = "Add the role";
export const ROLE_SAVE_LABEL = "Save role";
export const ROLE_CHANGE_LABEL = "Change";
export const ROLE_CLEAR_LABEL = "Clear";
/** Clearing hands the field back to the sync; it is not a removal of anything. */
export const ROLE_CLEAR_HINT = "empties the role — nothing else about the row changes";
/**
 * Stated where the empty role is, so the absence reads as a known limitation
 * rather than as something still loading or quietly broken.
 */
export const ROLE_ABSENT_HINT = "your mail never named one";
export const ROLE_SAVE_FAILED = "Couldn't save the role — nothing changed.";
export const ROLE_CLEAR_FAILED = "Couldn't clear the role — it is unchanged.";
export const ROLE_TOO_LONG = `That is longer than ${MAX_ROLE_LENGTH} characters — shorten it to save.`;
