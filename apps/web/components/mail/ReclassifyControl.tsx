"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { MailText } from "@/components/mail/MailText";
import { ApplicationPicker } from "@/components/review/ApplicationPicker";
import {
  CLASSIFY_FAILED,
  asksWhichApplication,
  canNameCompany,
  canSubmitReview,
  classifyDecisionBody,
  confirmCompanyPrompt,
  employerPromptFor,
  readClassifyOutcome,
  rowStaysInQueue,
  type CandidateApplication,
  type ReviewAssignment,
} from "@/lib/dashboard/review";
import { safeText } from "@/lib/security/hostileText";
import type { ScanMessagePayload } from "@/lib/gmail/scan-correction";
import { liveClassify, type ClassifyFn } from "@/lib/gmail/transport";

/**
 * The correction affordance the filed-mail view exists for: every stored
 * verdict — including one already reviewed or already linked to a row, which
 * the needs-review queue can never show again — gets a way to be corrected.
 *
 * Same wire contract as the review queue, read through the same
 * `readClassifyOutcome`: a 2xx does NOT mean a row was filed. When the backend
 * cannot name the employer it answers `needs_employer: true` and files
 * nothing, so this control keeps the panel open, says what is missing, and
 * asks for the company instead of pretending the click worked.
 *
 * The category list starts at a placeholder on purpose — the control must not
 * answer for the user (a preselected value is how absent-minded clicks become
 * training examples). Choices mirror the review queue's: classifier categories
 * the classify endpoint accepts, with "other" meaning "not job related".
 *
 * IT ALSO ASKS WHICH APPLICATION (#560). This control used to send a literal
 * `null` in the `application_id` position — it never asked, so it never had an
 * answer to send. For a message NOT already filed against a row, at an employer
 * holding several, the backend then had no link to outrank its tie-break and
 * `_pick_application` rule 4 filed the correction onto the employer's OLDEST
 * row: measured, two Northwind rows and a blind correction moved row 1 to
 * `interviewing` on the strength of a message nobody had said was about it.
 * That is #554's defect on this surface, and it is answered with #554's picker
 * — the same `ApplicationPicker`, the same `asksWhichApplication` predicate,
 * the same wire — not with a second way of asking the same question.
 *
 * The three cases, and the two of them that must ask NOTHING are as
 * load-bearing as the one that asks:
 *
 *   - ALREADY FILED against a row → no question. The message's own link beats
 *     every tie-break in `_resolve_application_for_email` (#546 / #548), so
 *     the correction lands where the human already put it. This is the common
 *     case in the filed ledger and it costs the reader nothing.
 *   - UNLINKED, one candidate (or none) → no question. One option is not a
 *     question, and the tie-break has the right row to land on anyway.
 *   - UNLINKED, several candidates, a lifecycle category → asked, and the
 *     answer rides the request as `application_id` / `none_of_these`.
 */
const CATEGORY_CHOICES: { value: string; label: string }[] = [
  { value: "applied", label: "applied" },
  // The label is the CATEGORY's word, not the stage's. `EmailCategory.INTERVIEW`
  // is "interview" (models.py:131); `ApplicationStatus.INTERVIEWING` is
  // "interviewing" (:109). Two vocabularies on purpose -- one names what a
  // message IS, the other names where a card SITS -- and this list asks the
  // first question, so it answers in the first vocabulary. #425.
  { value: "interview", label: "interview" },
  { value: "assessment", label: "assessment" },
  { value: "offer", label: "offer" },
  { value: "rejection", label: "rejection" },
  { value: "other", label: "not job related" },
];

const PLACEHOLDER = "";

export function ReclassifyControl({
  messageId,
  subject,
  company,
  candidates,
  linkedApplicationId,
  message,
  onCorrected,
  classify = liveClassify,
}: {
  messageId: string;
  /** For the control's accessible name — three bare "reclassify" buttons in a
   *  list are indistinguishable to a screen reader. */
  subject: string;
  /**
   * The LINKED application's employer name, if this message has one — it
   * prefills the "we couldn't name the employer" ask.
   *
   * Not the employer the mail itself names, and not what decides which rows
   * are offered: it is null on every unlinked row, which is the whole
   * population the picker is for. `candidates` carries that answer, matched
   * from `employer_token` (#560).
   */
  company: string | null;
  /**
   * The board rows this message could be about — its employer's, matched by
   * `reviewCandidates`. REQUIRED, and deliberately not defaulted to `[]`: a
   * mount that cannot see the user's board has to say so, rather than inherit
   * silence from a default and quietly stop asking a question this control
   * exists to ask. The live scan is the mount that says so, and says why.
   *
   * Fewer than two is not a question and renders nothing.
   */
  candidates: readonly CandidateApplication[];
  /**
   * The application this message is already filed against, or `null`.
   *
   * With a link there is nothing to ask: it outranks the backend's tie-break
   * (#546 / #548), so the correction cannot walk onto a sibling row. It is the
   * row id and not a boolean because the two surfaces that pass it read it
   * from `application_id` directly, and a boolean derived at the call site is
   * one more place for the two to disagree. A DISMISSED row still counts as a
   * link: `_company_rows` returns dismissed rows deliberately, so the backend's
   * link-first branch still finds it.
   */
  linkedApplicationId: number | null;
  /**
   * The message's own metadata, for a row that may not be STORED yet — every
   * row in the live-scan view. Absent for the filed ledger, whose rows are
   * stored by definition. Without it the backend has nothing to correct and
   * answers 404, so a scan row whose metadata cannot be built (no receive
   * time) must not render this control at all; `scanMessagePayload` decides
   * that, and the caller shows `UNSTORABLE_ROW_NOTE` instead.
   */
  message?: ScanMessagePayload;
  /**
   * Told the accepted category once the correction sticks. The filed view
   * needs nothing here — `router.refresh()` re-renders it from the server —
   * but the scan view's rows are client state the server does not know about,
   * so it updates its own row, its chip counts and its session snapshot.
   */
  onCorrected?: (category: string) => void;
  /** The transport seam. Defaults to the real proxy call; `/demo/scan` passes
   *  the simulated one so the control is reachable without a session. */
  classify?: ClassifyFn;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState(PLACEHOLDER);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Set when the backend filed nothing because it couldn't name the employer. */
  const [employerPrompt, setEmployerPrompt] = useState<string | null>(null);
  const [namedCompany, setNamedCompany] = useState(company ?? "");
  /** The spelling already on the board that the typed company looks like. */
  const [suggestion, setSuggestion] = useState<string | null>(null);
  /**
   * Which application this correction is about. `null` is UNANSWERED and
   * nothing is checked; `"none"` is a deliberate choice. The two used to share
   * `null` in the queue's copy of this control, with the discarding option
   * pre-selected, and that is the defect #554 measured — see `ReviewAssignment`.
   */
  const [assignment, setAssignment] = useState<ReviewAssignment>(null);
  /** The two nodes the focus effects below hand the reader's place to. */
  const categoryRef = useRef<HTMLSelectElement | null>(null);
  const doneRef = useRef<HTMLParagraphElement | null>(null);

  const showPicker = asksWhichApplication({ category, candidates, linkedApplicationId });
  const canSend = canSubmitReview(category, showPicker, assignment);
  /**
   * The apply button's state: a write is in flight, or the decision is not
   * answerable yet. STATED with `aria-disabled` and enforced in the handler —
   * never with the DOM's `disabled` (#425).
   *
   * A FOCUSED element that becomes `disabled` is blurred by the browser to
   * `<body>` and never gets the focus back, and this button is exactly where
   * the reader is standing when the write starts: they pressed Enter on it.
   * Measured on `/demo/scan`, standing on apply: `document.activeElement` was
   * `<body>` at t=8ms with the node still in the document, and the unmount that
   * swaps the panel for "corrected" is a downstream event at t=170ms. So the
   * blur is caused by the attribute, not by the reparent — character for
   * character the defect #777 fixed on `ApplicationRow` / `ApplicationDetail`,
   * whose `StageSelect` header carries that measurement. For THAT defect,
   * restoring focus afterwards is not the repair: the node never leaves the
   * page, so a restore would be racing a blur it cannot see coming. It says
   * nothing about the case where this control removes the focused node
   * ITSELF — there is no race to lose then, and a deliberate move is the only
   * place focus can come from. See the two focus effects below.
   *
   * It also blurred a SECOND time, at the far end of the same correction: a
   * `needs_employer` answer clears `busy` and sets `employerPrompt`, and the
   * conjunct below then flipped the still-focused button straight back to
   * `disabled`. One expression, two blurs, one fix.
   *
   * The employer conjunct stays OUT of `apply()` deliberately — the two
   * confirmation buttons re-send with an explicit company and must not be
   * refused over the empty box they are answering.
   */
  const applyLocked =
    busy || !canSend || (employerPrompt !== null && !canNameCompany(namedCompany));

  async function apply(answer?: { company?: string; confirmNewCompany?: boolean }) {
    // ENFORCED HERE, NOT ON THE BUTTON, for the reason `canSubmitReview`'s own
    // docstring gives: the two confirmation buttons and the employer prompt all
    // re-send this decision without consulting the apply button's own state.
    // A gate written only there is a gate with three side doors.
    //
    // `busy` joins it for #425's sake. The in-flight lock is `aria-disabled`
    // now, which is ADVISORY — the browser still delivers the click, and
    // `aria-disabled` on its own would make a mid-write second apply MORE
    // reachable than it was before. Dropping the call at the one point every
    // re-send passes through is what makes the lock real.
    if (!canSend || busy) return;
    setBusy(true);
    setError(null);
    const named = (answer?.company ?? namedCompany).trim();
    const sendCompany = answer?.company !== undefined || employerPrompt !== null;
    try {
      const res = await classify(
        messageId,
        // Built by the SHARED builder, which is what puts the user's answer on
        // the wire. The `null` that used to sit in the assignment position here
        // is #560.
        classifyDecisionBody({
          category,
          // Only send the company once the backend has asked for it — sending
          // it up front would override an employer the mail itself names.
          company: sendCompany ? named : null,
          candidates,
          linkedApplicationId,
          assignment,
          message,
          confirmNewCompany: answer?.confirmNewCompany,
        }),
      );
      const outcome = readClassifyOutcome(res.ok, res.body);
      if (rowStaysInQueue(outcome)) {
        if (outcome.kind === "needs-confirmation") {
          setNamedCompany(named);
          setSuggestion(outcome.suggestedCompany);
        } else if (outcome.kind === "needs-employer") {
          setSuggestion(null);
          setEmployerPrompt(employerPromptFor(employerPrompt ? named : ""));
        } else {
          setError(outcome.detail);
        }
        setBusy(false);
        return;
      }
      // The correction stuck. Refresh re-renders the server list (and the
      // rail's counts) with the new verdict; the local "corrected" note covers
      // the gap so the click is never silent. `onCorrected` is the scan view's
      // half of the same job: its rows are client state, so a refresh alone
      // would leave the verdict it just changed reading the old category.
      setDone(true);
      setBusy(false);
      onCorrected?.(category);
      router.refresh();
    } catch {
      setError(CLASSIFY_FAILED);
      setBusy(false);
    }
  }

  /**
   * THE OTHER HALF OF #425: focus after an UNMOUNT, which is a different
   * defect from the `disabled` blur above and takes the opposite repair.
   *
   * That one was an ATTRIBUTE on a node still in the document, so the fix was
   * to stop setting it. These two are the case where the focused node is
   * REMOVED — by this component, in the commit its own state change causes.
   * Nothing is racing anything: React has replaced the tree by the time an
   * effect runs and the browser has already parked focus on `<body>`.
   *
   * Measured on /demo/scan at 1024x768 with the 8ms sampler in
   * `tests/e2e/stage-focus.spec.ts`, before this fix:
   *
   *   - pressing `reclassify`: the trigger detaches at t=8-9ms and
   *     `document.activeElement` reads BODY for the whole 1200ms window.
   *   - an apply that FILES: detached at t=171-183ms, BODY through t=2505, and
   *     the correction landed — so the reader loses their place on the
   *     SUCCESSFUL path.
   *
   * The two are guarded differently, on purpose. Opening the panel is a
   * DISCLOSURE the reader asked for, so focus follows their gesture into it.
   * "Corrected" is an OUTCOME the write brought back, so it only claims focus
   * that has been DROPPED — `activeElement === document.body`, the same
   * conditional contract `ApplicationDetail`'s pane restore uses (:484-490) —
   * and never pulls a reader who has already moved to another row.
   */
  useEffect(() => {
    if (!open) return;
    // `preventScroll`, here and below: the panel is already where the reader
    // clicked, and a reveal scroll on a long scan list would move the page
    // under them for nothing.
    categoryRef.current?.focus({ preventScroll: true });
  }, [open]);

  useEffect(() => {
    if (!done) return;
    if (document.activeElement !== document.body) return;
    doneRef.current?.focus({ preventScroll: true });
  }, [done]);

  if (done) {
    return (
      // `tabIndex={-1}` so the note that REPLACED the panel can hold the focus
      // the panel took with it: programmatically focusable, never in the tab
      // order. `role="status"` is unchanged — it is still the live region that
      // announces the outcome; focusing it is what makes the announcement
      // reach a reader whose place would otherwise be `<body>`.
      <p
        id={`reclass-done-${messageId}`}
        ref={doneRef}
        role="status"
        tabIndex={-1}
        className="text-xs text-live"
      >
        corrected — your call is the verdict now
      </p>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        // Addressable for the same reason `apply` is: one of these per scan
        // row, and the focus probe cannot say WHICH trigger the reader was
        // standing on without an id. It is also the node that unmounts the
        // instant it is pressed, which is the defect it is read for.
        id={`reclass-open-${messageId}`}
        onClick={() => setOpen(true)}
        aria-label={`Reclassify “${safeText(subject)}”`}
        className="rounded border border-line px-2 py-1 text-xs font-medium text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
      >
        reclassify
      </button>
    );
  }

  return (
    // `relative` covers BOTH `sr-only` labels below — this one and the
    // company-prompt's. Tailwind's `.sr-only` is `position: absolute`, so
    // without a positioned ancestor they resolve against the initial
    // containing block, escaping every `overflow` above them; that is how the
    // board's review queue made the whole shell scroll (#149). Measured on the
    // signed-in /inbox: expanding a control put its label's `offsetParent` at
    // `body`. Harmless there *today* only because /inbox is a flow page whose
    // <main> already scrolls — geometry this component does not own and cannot
    // rely on. It is also mounted by `FiledMailList`, so the honest fix is for
    // the control to guarantee its own containing block.
    <div className="relative flex w-full flex-wrap items-center gap-2">
      <label className="sr-only" htmlFor={`reclass-${messageId}`}>
        New category for “<MailText value={subject} />”
      </label>
      <select
        id={`reclass-${messageId}`}
        ref={categoryRef}
        value={category}
        // Never the DOM's `disabled`, for the reason on `applyLocked` above
        // (#425). This control is one Shift+Tab from being the focused one
        // while the write is in flight, and `disabled` would take it out of the
        // focus order and out of the accessibility tree at the moment the
        // reader might reach for it; `aria-disabled` says "not now" and leaves
        // it where they left it.
        aria-disabled={busy}
        onChange={(e) => {
          // IGNORED, not prevented. `aria-disabled` leaves the control
          // operable, so a category CAN still be dispatched mid-write, and
          // dropping it here is what makes the lock real. `value` does not
          // move, and React restores a controlled <select>'s DOM selection
          // after a change its handler did not act on, so it snaps back.
          if (busy) return;
          setCategory(e.target.value);
          // The pick belonged to the PREVIOUS stage's question. Leaving it
          // mounted is what let a re-send fire against a question the user is
          // no longer looking at (#554).
          setAssignment(null);
        }}
        className="rounded border border-line-soft bg-surface px-1.5 py-1 text-xs text-muted outline-none transition-colors hover:border-line focus:border-line-strong aria-disabled:opacity-50"
      >
        <option value={PLACEHOLDER} disabled>
          choose a category…
        </option>
        {CATEGORY_CHOICES.map((c) => (
          <option key={c.value} value={c.value}>
            {c.label}
          </option>
        ))}
      </select>
      <button
        type="button"
        // Addressable on purpose: a scan list holds one of these per row, and
        // `document.activeElement` cannot say WHICH "apply" it is standing on
        // without an id. The focus probe in `tests/e2e/stage-focus.spec.ts`
        // reads it, and the defect this button carries is only measurable if
        // the instrument can name the node.
        id={`reclass-apply-${messageId}`}
        onClick={() => {
          if (applyLocked) return;
          void apply();
        }}
        aria-disabled={applyLocked}
        // The spinner beside the word is `aria-hidden`, so without this a
        // screen reader heard nothing at all while the write was in flight —
        // `aria-disabled` alone says "not now" without saying "wait". Same gap
        // and same repair as `ApplicationDetail`'s stage select (#425). It sits
        // on the button rather than on the select because the button is what
        // makes the request; the select is locked, not busy.
        aria-busy={busy}
        className="inline-flex items-center gap-1 rounded border border-line px-2 py-1 text-xs font-medium text-foreground transition-colors hover:border-line-strong hover:text-strong aria-disabled:opacity-50"
      >
        {busy ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
        apply
      </button>
      <button
        type="button"
        onClick={() => {
          setOpen(false);
          setError(null);
          setEmployerPrompt(null);
          setSuggestion(null);
        }}
        disabled={busy}
        className="text-xs text-dim underline-offset-2 hover:text-strong hover:underline disabled:opacity-50"
      >
        cancel
      </button>

      {/* --- Which application is this about? ------------------------------
          `basis-full` because this control's root is a flex ROW: the question
          takes its own line under the stage select rather than being squeezed
          beside it. */}
      {showPicker ? (
        <ApplicationPicker
          className="basis-full"
          name={`reclass-assign-${messageId}`}
          candidates={candidates}
          assignment={assignment}
          onChange={setAssignment}
          disabled={busy}
        />
      ) : null}

      {/* The company named is one edit from one already on the board. Nothing
          was filed and nothing was merged — the same closeness that catches a
          typo catches two real employers, so the user answers it. */}
      {suggestion ? (
        <div className="flex basis-full flex-wrap items-center gap-2 rounded border border-review/40 bg-surface px-2.5 py-2">
          <p role="status" className="basis-full text-xs leading-relaxed text-review">
            {confirmCompanyPrompt(suggestion)}
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setSuggestion(null);
              setNamedCompany(suggestion);
              void apply({ company: suggestion });
            }}
            className="inline-flex items-center gap-1 rounded border border-review/50 px-2 py-1 text-xs font-medium text-strong transition-colors hover:border-review disabled:opacity-50"
          >
            yes — file it under {suggestion}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setSuggestion(null);
              void apply({ confirmNewCompany: true });
            }}
            className="text-xs text-dim underline-offset-2 hover:text-strong hover:underline disabled:opacity-50"
          >
            no — a different company
          </button>
        </div>
      ) : null}

      {employerPrompt && !suggestion ? (
        <div className="flex basis-full flex-wrap items-center gap-2 rounded border border-review/40 bg-surface px-2.5 py-2">
          <p role="status" className="basis-full text-xs leading-relaxed text-review">
            {employerPrompt}
          </p>
          <label className="sr-only" htmlFor={`reclass-company-${messageId}`}>
            Company this email is from
          </label>
          <input
            id={`reclass-company-${messageId}`}
            value={namedCompany}
            disabled={busy}
            onChange={(e) => setNamedCompany(e.target.value)}
            placeholder="company name"
            autoComplete="organization"
            spellCheck={false}
            className="min-w-0 flex-1 rounded border border-line-soft bg-surface-2 px-1.5 py-1 text-xs text-strong outline-none transition-colors placeholder:text-dim hover:border-line focus:border-line-strong disabled:opacity-50"
          />
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="basis-full text-xs text-reject-ink">
          {error}
        </p>
      ) : null}
    </div>
  );
}
