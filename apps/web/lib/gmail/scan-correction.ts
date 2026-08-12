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
 * `needs_review` is cleared because a human has now reviewed it; `confidence`
 * is left alone, exactly as the backend leaves `classification_confidence`
 * alone. The number was the machine's report of its own certainty and stays
 * true as that — overwriting it with 1.0 would put a claim the classifier
 * never made behind the user's label.
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
