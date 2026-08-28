"use client";

import { ExternalLink, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { GateMeter } from "@/components/viz/GateMeter";
import { shortDate } from "@/lib/dashboard/dates";
import { AUTO_FILE_GATE } from "@/lib/dashboard/model";
import {
  CLASSIFY_FAILED,
  canNameCompany,
  canSubmitReview,
  classifyRequestBody,
  confirmCompanyPrompt,
  employerPromptFor,
  holdReasonSentence,
  readClassifyOutcome,
  reviewCandidates,
  rowStaysInQueue,
  type CandidateApplication,
  type ReviewAssignment,
} from "@/lib/dashboard/review";
import type { Application } from "@/lib/dashboard/summary";

/** One uncertain verdict awaiting a human decision (from GET /applications/review). */
export interface ReviewItem {
  message_id: string;
  subject?: string | null;
  sender_name?: string | null;
  sender_email?: string | null;
  received_at?: string | null;
  snippet?: string | null;
  confidence?: number | null;
  gmail_link?: string | null;
  /** Why this is held — one of `HOLD_REASONS`. Absent on an older backend, in
   *  which case the row says nothing rather than guessing (#507). */
  hold_reason?: string | null;
  suggested_employer?: string | null;
  /**
   * Which application this entry is about, when the mail names one.
   *
   * An applicant tracking system sends every acknowledgement for an employer
   * under one subject from one no-reply address, so several entries here can
   * carry a byte-identical subject and sender and still be four different
   * applications. This is the only field that tells them apart.
   */
  role?: string | null;
}

/**
 * Category choices → backend EmailCategory values. "other" dismisses + trains.
 * The list starts with a disabled placeholder: the queue exists because the
 * classifier was NOT sure, so the control must not answer for the user — a
 * preselected `applied` meant every absent-minded "classify" click silently
 * filed the row as applied and fed that back as a training example.
 */
const CATEGORY_CHOICES: { value: string; label: string }[] = [
  { value: "applied", label: "applied" },
  { value: "interview", label: "interviewing" },
  { value: "assessment", label: "assessment" },
  { value: "offer", label: "offer" },
  { value: "rejection", label: "rejection" },
  { value: "other", label: "not job related" },
];

const PLACEHOLDER = "";

/** Categories that answer an EXISTING application rather than opening one. */
const LIFECYCLE_ANSWERS = new Set(["interview", "assessment", "offer", "rejection"]);

function truncate(value: string, max = 60): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function ReviewRow({
  item,
  candidates,
}: {
  item: ReviewItem;
  /** Applications this message could belong to (same employer, several roles). */
  candidates: CandidateApplication[];
}) {
  const router = useRouter();
  const [category, setCategory] = useState(PLACEHOLDER);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Set when the backend filed nothing because it couldn't name the employer. */
  const [employerPrompt, setEmployerPrompt] = useState<string | null>(null);
  const [company, setCompany] = useState("");
  /**
   * The spelling already on the board that the typed company looks like. Set
   * when the backend asked rather than filing — it never merges on the
   * resemblance itself, so this is a question with two buttons, not a notice.
   */
  const [suggestion, setSuggestion] = useState<string | null>(null);
  /**
   * The application this verdict answers, when one employer holds several.
   *
   * `null` is UNANSWERED and nothing is checked. It used to be both "unanswered"
   * and "not one of these", with "not one of these" pre-selected — so the option
   * that discards the question was the default, and a user who read the subject,
   * chose a stage and clicked classify had answered it without choosing it
   * (#554). Measured over 2,701 replayed answers, requiring the pick took
   * applications destroyed from 19 to 0 and applications scattered from 58 to 1
   * — a one-off probe over the corpus harness, not a CI gate; its provenance is
   * written out in `backend/tests/test_none_of_these_opens_a_row.py`.
   *
   * This is the rule `CATEGORY_CHOICES` above already states for the stage
   * select — "the control must not answer for the user" — applied to the control
   * where being wrong costs a record rather than a label.
   *
   * THE INITIAL VALUE HERE IS NOT WHAT PINS THAT, and no test can make it be.
   * The picker renders only once a lifecycle stage is chosen, and choosing one
   * runs the reset below — so whatever this `useState` holds is overwritten
   * before the radios ever appear. The load-bearing line is
   * `setAssignment(null)` in the select's `onChange`; changing it to `"none"`
   * reproduces the shipped defect exactly, and `tests/e2e/review-picker.spec.ts`
   * goes red on it. `null` here is agreement with that line, not a second
   * guard, and weakening the reset on the grounds that "the default is safe
   * anyway" would put the bug straight back.
   */
  const [assignment, setAssignment] = useState<ReviewAssignment>(null);

  // The picker is a question, and one candidate is not a question: it renders
  // only when the message matches SEVERAL applications and the chosen category
  // answers an existing one (a rejection belongs to one of the four Amazon
  // rows; "applied" opens a new row and "not job related" opens nothing).
  const showPicker = candidates.length >= 2 && LIFECYCLE_ANSWERS.has(category);

  /**
   * Send the decision. A 2xx is NOT success on its own: `needs_employer: true`
   * means nothing was filed and the row is still in the queue, so we keep it on
   * screen, say so, and ask for the company instead of refreshing the row away.
   *
   * `answer` carries what the user just clicked, because the two confirmation
   * buttons both re-send immediately and React state has not settled by then —
   * reading `company` here would send the previous attempt's value.
   */
  async function classify(answer?: { company?: string; confirmNewCompany?: boolean }) {
    // ENFORCED HERE, NOT ON THE BUTTON. Three other controls re-send this same
    // decision — both confirmation buttons and the needs-employer form — and
    // none of them reads the submit button's `disabled`. Gating only there left
    // a live side door: a `needs_employer` round trip leaves the stage select
    // enabled, changing the stage clears the pick, and the still-mounted prompt
    // then files with no answer at all. Every caller inherits the rule from
    // here, and the `disabled` attributes below are courtesy on top of it.
    if (!canSubmitReview(category, showPicker, assignment)) return;
    setBusy(true);
    setError(null);
    const named = (answer?.company ?? company).trim();
    try {
      const res = await fetch(
        `/api/applications/review/${encodeURIComponent(item.message_id)}/classify`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            classifyRequestBody(
              category,
              named,
              showPicker ? assignment : null,
              null,
              answer?.confirmNewCompany,
            ),
          ),
        },
      );
      const outcome = readClassifyOutcome(res.ok, await res.json().catch(() => ({})));

      if (rowStaysInQueue(outcome)) {
        // Nothing changed server-side, so there is nothing to re-fetch — say
        // what is missing and let the user answer it here. Never leave the
        // button spinning: that is what made the 2xx-that-filed-nothing look
        // like the click had simply done nothing.
        if (outcome.kind === "needs-confirmation") {
          setCompany(named); // keep the typed spelling for the "no" answer
          setSuggestion(outcome.suggestedCompany);
        } else if (outcome.kind === "needs-employer") {
          setSuggestion(null);
          setEmployerPrompt(employerPromptFor(named));
        } else setError(outcome.detail);
        setBusy(false);
        return;
      }
      // Resolved: the item has left the queue on the server. Stay busy through
      // the refresh that unmounts this row.
      router.refresh();
    } catch {
      setError(CLASSIFY_FAILED);
      setBusy(false);
    }
  }

  const sender = item.sender_name || item.sender_email || "unknown sender";
  const canFile = canNameCompany(company);
  const canSend = canSubmitReview(category, showPicker, assignment);

  return (
    <li className="rounded-lg border border-line-soft bg-surface-2 p-3">
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 text-sm font-medium text-strong">
          <span className="truncate">{item.subject || "(no subject)"}</span>
        </p>
        {/* No receipt time at all → render nothing (not the "—" placeholder),
            which is what this row has always shown for a dateless item. */}
        <span className="tabular shrink-0 font-mono text-[10px] text-dim">
          {item.received_at ? shortDate(item.received_at) : ""}
        </span>
      </div>
      <p className="truncate text-xs text-muted">
        {sender}
        {item.role ? <span className="text-dim"> · {item.role}</span> : null}
      </p>
      {/* WHY this email is here: its confidence drawn against the auto-file
          gate, then the hold reason THE BACKEND REPORTED — not one inferred
          from the score. This line used to read the confidence twice, once for
          the meter and once to guess the reason, and told every confident row
          that its employer could not be named. See `holdReasonSentence`, and
          note it returns null rather than a fallback sentence: a row whose
          reason this build does not recognise says nothing at all. */}
      {typeof item.confidence === "number" ? (
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-dim">
          <GateMeter confidence={item.confidence} className="w-12" />
          <span
            className="tabular font-mono"
            style={{
              color: item.confidence >= AUTO_FILE_GATE ? "var(--green)" : "var(--amber)",
            }}
          >
            {Math.round(item.confidence * 100)}%
          </span>
          {holdReasonSentence(item.hold_reason, AUTO_FILE_GATE, item.suggested_employer)}
        </p>
      ) : null}
      {item.snippet ? (
        <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-dim">{item.snippet}</p>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {/* Unique per row: three selects all announcing "Classify this email"
            were indistinguishable to a screen reader.
            The ROLE is part of that name and not decoration. Since the queue
            began keying on (conversation, application) rather than on the
            conversation alone, one ATS thread produces several rows whose
            subject AND sender are byte-identical — four "Thank you for applying
            to Verkada" from one no-reply address — and without the role the
            accessible names collide again. */}
        <label className="sr-only" htmlFor={`cat-${item.message_id}`}>
          Classify &ldquo;{truncate(item.subject || "(no subject)")}&rdquo; from {sender}
          {item.role ? `, ${item.role}` : ""}
        </label>
        <select
          id={`cat-${item.message_id}`}
          value={category}
          disabled={busy}
          onChange={(e) => {
            setCategory(e.target.value);
            // The pick belonged to the previous stage's question, and so did
            // any prompt on screen: `employerPrompt` and `suggestion` are both
            // answers ABOUT the last submission. Leaving them mounted is what
            // let a re-send fire against a cleared pick.
            setAssignment(null);
            setEmployerPrompt(null);
            setSuggestion(null);
          }}
          className="rounded border border-line-soft bg-surface px-1.5 py-1 text-xs text-muted outline-none transition-colors hover:border-line focus:border-line-strong disabled:opacity-50"
        >
          <option value={PLACEHOLDER} disabled>
            choose a stage…
          </option>
          {CATEGORY_CHOICES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          // Wrapped, not passed by reference: `classify` now takes the answer to
          // the did-you-mean question, and a bare handler would hand it the
          // click event as that answer.
          onClick={() => void classify()}
          disabled={busy || !canSend}
          className="inline-flex items-center gap-1 rounded border border-line px-2 py-1 text-xs font-medium text-foreground transition-colors hover:border-line-strong hover:text-strong disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
          classify
        </button>
        {item.gmail_link ? (
          <a
            href={item.gmail_link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-dim underline-offset-2 hover:text-strong hover:underline"
          >
            <ExternalLink className="h-3 w-3" aria-hidden />
            open in gmail
          </a>
        ) : null}
      </div>

      {/* --- Which application is this about? ------------------------------
          One employer can hold several applications, so a rejection from that
          employer is ambiguous until the user says which role it answers. */}
      {showPicker ? (
        <fieldset className="mt-2 rounded border border-line px-2.5 py-2">
          <legend className="px-1 text-[11px] text-muted">
            which application is this about?
          </legend>
          <div className="space-y-1">
            {candidates.map((candidate) => (
              <label
                key={candidate.id}
                className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-muted hover:text-strong"
              >
                <input
                  type="radio"
                  name={`assign-${item.message_id}`}
                  // The answer is readable from the DOM, which is what lets a
                  // browser test assert that the id the user picked is the id
                  // the request carried. Without it the radio's identity lives
                  // only in a closure and the wire between the two is untestable
                  // — the gap this control shipped through.
                  value={candidate.id}
                  checked={assignment === candidate.id}
                  onChange={() => setAssignment(candidate.id)}
                  disabled={busy}
                  className="h-3 w-3 accent-[var(--text-strong)]"
                />
                <span className="min-w-0 truncate">
                  {candidate.position.trim() || "role not captured"}
                  <span className="text-dim"> · {candidate.status}</span>
                </span>
              </label>
            ))}
            <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-muted hover:text-strong">
              <input
                type="radio"
                name={`assign-${item.message_id}`}
                value="none"
                checked={assignment === "none"}
                onChange={() => setAssignment("none")}
                disabled={busy}
                className="h-3 w-3 accent-[var(--text-strong)]"
              />
              {/* The label says what the product will DO, because what it used
                  to do was file against the oldest row at this employer — the
                  opposite of what "not one of these" promises. Choosing it now
                  opens a row, which is what a lifecycle message about an
                  application the board does not hold actually means. */}
              <span>none of these — track it as a new application</span>
            </label>
          </div>
        </fieldset>
      ) : null}

      {/* --- Did you mean the one already on your board? --------------------
          The typed company is one edit from a stored employer. Nothing has been
          filed and nothing has been merged: a resemblance close enough to catch
          "Verkeda"/"Verkada" also catches two real companies, so the answer is
          the user's. Both buttons re-send the decision; neither is preselected.
          Shown INSTEAD of the company input — one question at a time — and the
          typed spelling is still there behind it if they answer "no". */}
      {suggestion ? (
        <div className="mt-2 rounded border border-review/40 bg-surface px-2.5 py-2">
          <p role="status" className="text-xs leading-relaxed text-review">
            {confirmCompanyPrompt(suggestion)}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setSuggestion(null);
                setCompany(suggestion);
                void classify({ company: suggestion });
              }}
              className="inline-flex items-center gap-1 rounded border border-review/50 px-2 py-1 text-xs font-medium text-strong transition-colors hover:border-review disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
              yes — file it under {suggestion}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setSuggestion(null);
                void classify({ confirmNewCompany: true });
              }}
              className="text-xs text-dim underline-offset-2 hover:text-strong hover:underline disabled:opacity-50"
            >
              no — {company.trim() || "this company"} is a different company
            </button>
          </div>
        </div>
      ) : null}

      {/* The correction affordance for a decision the backend accepted but
          could not file: amber (the needs-review hue), not red — nothing broke,
          the message simply doesn't name its employer. */}
      {employerPrompt && !suggestion ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy && canFile && canSend) void classify();
          }}
          className="mt-2 rounded border border-review/40 bg-surface px-2.5 py-2"
        >
          <p role="status" className="text-xs leading-relaxed text-review">
            {employerPrompt}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor={`company-${item.message_id}`}>
              Company this email is from
            </label>
            <input
              id={`company-${item.message_id}`}
              value={company}
              disabled={busy}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="company name"
              autoComplete="organization"
              spellCheck={false}
              className="min-w-0 flex-1 rounded border border-line-soft bg-surface-2 px-1.5 py-1 text-xs text-strong outline-none transition-colors placeholder:text-dim hover:border-line focus:border-line-strong disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={busy || !canFile}
              className="inline-flex shrink-0 items-center gap-1 rounded border border-review/50 px-2 py-1 text-xs font-medium text-strong transition-colors hover:border-review disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
              file it
            </button>
          </div>
        </form>
      ) : null}

      {error ? (
        <p role="alert" className="mt-1.5 text-xs text-reject-ink">
          {error}
        </p>
      ) : null}
    </li>
  );
}

/**
 * The needs-review queue — what needs the user, so it leads the page (or, when
 * the Settings "Needs review alerts" toggle is off, waits under the board).
 * Each uncertain verdict (the 0.70–0.85 band, or a confident one whose
 * employer couldn't be named) gets a category decision that persists — the email
 * is flagged reviewed and a later sync leaves the answer alone. It does NOT train
 * the model: the decision is written to `training_data`, but no deployed path
 * reads that table back, so nothing about the next classification changes.
 * Choosing "not job related" removes it from the queue.
 *
 * Naming: this one queue was called "needs classification", "need review" and
 * "held for your review" on one screen. It is the review family everywhere
 * now — the amber token is literally named `--color-review`. The section
 * anchor stays `needs-classification` so existing deep links keep resolving.
 *
 * Density follows the board's rule — no scroller nested inside the scrolling
 * page. A long queue shows its first {@link COLLAPSED_COUNT} rows and a
 * "show all N" expander that grows the page.
 */
const COLLAPSED_COUNT = 4;

export function ReviewQueue({
  items,
  applications = [],
}: {
  items: ReviewItem[];
  /** The board rows, for the assign-to-application picker. */
  applications?: Application[];
}) {
  const [expandedList, setExpandedList] = useState(false);

  // The picker's candidate pool — id/company/position/status is all it needs.
  const candidatePool = useMemo<CandidateApplication[]>(
    () =>
      applications.map((app) => ({
        id: app.id,
        company: app.company,
        position: app.position,
        status: app.status,
      })),
    [applications],
  );

  if (items.length === 0) return null;
  const visible = expandedList ? items : items.slice(0, COLLAPSED_COUNT);
  const hidden = items.length - visible.length;

  return (
    <section
      id="needs-classification"
      aria-label="Needs review"
      className="scroll-mt-6 rounded-2xl border border-review/40 bg-surface p-4 sm:p-5"
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-sm font-semibold tracking-tight text-strong">
          Needs review ({items.length})
        </h2>
        {/* Where the confidence gate's existence is told to the user — in
            terms of what it does for them, not as a CI metric. */}
        <span className="shrink-0 text-xs text-dim">
          held because Applied wasn&apos;t sure · your decision files them
        </span>
      </div>
      <ul className="space-y-2">
        {visible.map((item) => (
          <ReviewRow key={item.message_id} item={item} candidates={reviewCandidates(item, candidatePool)} />
        ))}
      </ul>
      {hidden > 0 || expandedList ? (
        <button
          type="button"
          onClick={() => setExpandedList((v) => !v)}
          className="mt-2 w-full rounded-lg border border-dashed border-line px-2 py-1.5 text-xs font-medium text-muted transition-colors hover:border-line-strong hover:text-strong"
        >
          {expandedList ? "show fewer" : `show all ${items.length}`}
        </button>
      ) : null}
    </section>
  );
}
