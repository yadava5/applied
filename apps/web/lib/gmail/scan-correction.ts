/**
 * Correcting a verdict in the LIVE SCAN — the part that is not the same as
 * correcting a filed one.
 *
 * A filed row is a stored message: `POST /applications/review/{id}/classify`
 * finds it by `(user_id, message_id)` and rewrites its verdict. A scan row is
 * not. The scan reads Gmail directly and stores nothing, so its rows are
 * verdicts about mail this database has never seen, and that same request
 * answered 404 for every one of them.
 *
 * Filing first does not fix it. `POST /gmail/sync` keeps only `needs_review`
 * mail and lifecycle mail at or above the 0.70 review floor
 * (`pipeline.collect_review_items`), so the case this exists for — the
 * assessment email the classifier called `other` at 0% — is dropped by the
 * file step and stays uncorrectable. The backend therefore accepts the
 * message's own metadata as `message` and stores it before applying the
 * correction; `scanMessagePayload` builds exactly that payload.
 *
 * The honest refusal matters as much as the payload: `Email.received_at` is
 * NOT NULL and the sync deliberately skips undated mail rather than inventing
 * a receive time, so a verdict the mine could not date cannot be stored, and
 * the control must say so instead of firing a request that will 422.
 *
 * Dependency-free at runtime (the only imports are types, which Node's type
 * stripping removes) so `tests/unit/` can load it directly.
 */

import type { CategorySummary, InboxVerdict } from "./types";

/**
 * May a row draw the classifier's confidence next to its verdict?
 *
 * Only while the verdict is still the classifier's. A confidence figure
 * rendered beside a category reads as a claim about THAT category — the meter,
 * the percentage and the amber/green hue all say "this is how sure we are of
 * this" — so once a reader has replaced the category, the old number describes
 * a verdict that is no longer on screen. The owner's Inbox drew
 * "rejection · 75% · corrected by you", where 75% was the classifier's
 * certainty about `applied`.
 *
 * A predicate rather than an inline `!v.user_corrected` at the render site,
 * because the render site is a TSX component with no unit test around it and
 * this rule is the whole point of the fix. Here it can be asserted directly.
 *
 * Note this deliberately does NOT clear `v.confidence`: that value is relayed
 * to the sync and classify endpoints, where dropping it files nothing. See
 * `applyVerdictCorrection`.
 */
export function verdictShowsConfidence(v: InboxVerdict): boolean {
  return !v.user_corrected;
}

/**
 * What the classify endpoint needs to STORE a message it has never seen —
 * `ScannedMessageIn` in `backend/jobtracker/cloud/applications.py`.
 *
 * Snake_case because it is wire shape, not view model. `category`,
 * `confidence` and `method` carry the classifier's verdict as the scan showed
 * it, so the stored row starts as a faithful copy of what the reader was
 * looking at and the correction reads as a correction.
 */
export interface ScanMessagePayload {
  sender_email: string;
  received_at: string;
  subject?: string;
  sender_name?: string;
  category?: string;
  confidence?: number;
  method?: string;
}

/**
 * Why a particular scan row cannot be corrected, in the reader's terms. Shown
 * in place of the control — never as a disabled button with no explanation,
 * and never as a button that would fail.
 */
export const UNSTORABLE_ROW_NOTE =
  "no readable date on this message — Applied won't store it, so there's nothing to correct";

/**
 * The persist-then-classify payload for one mined verdict, or `null` when the
 * row cannot honestly be stored.
 *
 * `received_at` null is the real case: the mine reports it for any message
 * whose `Date` header would not parse, and the store refuses those. A missing
 * sender is refused for the same reason it would be useless — the employer is
 * resolved from it, and a row with no sender can never file.
 */
export function scanMessagePayload(v: InboxVerdict): ScanMessagePayload | null {
  const receivedAt = typeof v.received_at === "string" ? v.received_at.trim() : "";
  const senderEmail = typeof v.sender_email === "string" ? v.sender_email.trim() : "";
  if (!receivedAt || !senderEmail) return null;

  const payload: ScanMessagePayload = {
    sender_email: senderEmail,
    received_at: receivedAt,
  };
  if (v.subject) payload.subject = v.subject;
  if (v.sender_name) payload.sender_name = v.sender_name;
  if (v.category) payload.category = v.category;
  if (typeof v.confidence === "number" && Number.isFinite(v.confidence)) {
    payload.confidence = v.confidence;
  }
  if (v.method) payload.method = v.method;
  return payload;
}

/** The mine's own state, as far as a correction is concerned. */
export interface ScanState {
  verdicts: InboxVerdict[];
  /** The counts the chips are drawn from — the whole-set analysis when there
   *  is one, otherwise the tally derived from the rows. */
  summary: CategorySummary;
}

export interface CorrectionResult extends ScanState {
  /** False when nothing moved — an unknown message id, or the same category. */
  changed: boolean;
}

/**
 * Apply one accepted correction to the mine.
 *
 * BOTH halves are the point. Rewriting only the row leaves the chips reading
 * the classifier's tally, and the chips are where the complaint started: an
 * `assessment` chip exists only while some message holds that category, so a
 * correction that never reaches the counts corrects a row into a category the
 * reader still cannot filter by — or even see. The summary is usually the
 * whole-set analysis from `POST /gmail/pipeline`, not a tally of the rendered
 * rows, so it has to be moved deliberately rather than recomputed.
 *
 * `needs_review` is cleared because a human has now reviewed it. `confidence`
 * is LEFT ALONE, and the reason is worth stating because the obvious change
 * here is wrong in two different ways.
 *
 * It cannot be set to 1.0: that is a claim of total certainty, on the
 * classifier's own scale and drawn by the classifier's own meter, behind a
 * label nothing ever scored.
 *
 * It cannot be nulled either, which is less obvious. This object is not only
 * display state — `toPipelineItems` relays it to `/gmail/sync`, where
 * `confidence` is required and GATES PERSISTENCE (auto-file 0.85, review floor
 * 0.70), and `scanMessagePayload` sends it to the classify endpoint to mint the
 * row as a faithful copy of the machine's verdict before the correction is
 * applied on top. A null degrades to 0.0 at both, which is below both gates —
 * the reader's correction would silently file nothing, which is the exact bug
 * `PipelineItem`'s own comment records.
 *
 * So the number stays, correctly, as the MACHINE's report about the machine's
 * verdict — and the fix for "rejection · 75% · corrected by you" belongs at the
 * render, which must not draw a confidence figure beside a verdict the
 * classifier did not produce. That is `verdictShowsConfidence`. The stored row
 * is a separate matter and is handled server-side: the classify endpoint nulls
 * `classification_confidence` (`cloud/applications.py`), so the filed ledger
 * shows no percentage for a corrected row.
 */
export function applyVerdictCorrection(
  state: ScanState,
  messageId: string,
  category: string,
): CorrectionResult {
  const target = state.verdicts.find((v) => v.message_id === messageId);
  if (!target || !category || target.category === category) {
    return { ...state, changed: false };
  }

  const verdicts = state.verdicts.map((v) =>
    v.message_id === messageId
      ? { ...v, category, needs_review: false, user_corrected: true }
      : v,
  );

  const summary: CategorySummary = { ...state.summary };
  const previous = summary[target.category];
  if (typeof previous === "number") {
    const left = previous - 1;
    if (left > 0) summary[target.category] = left;
    else delete summary[target.category];
  }
  summary[category] = (summary[category] ?? 0) + 1;

  return { verdicts, summary, changed: true };
}
