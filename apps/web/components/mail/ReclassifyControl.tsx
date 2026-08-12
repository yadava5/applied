"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  CLASSIFY_FAILED,
  canNameCompany,
  classifyRequestBody,
  employerPromptFor,
  readClassifyOutcome,
  rowStaysInQueue,
} from "@/lib/dashboard/review";
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

export function ReclassifyControl({
  messageId,
  subject,
  company,
  message,
  onCorrected,
  classify = liveClassify,
}: {
  messageId: string;
  /** For the control's accessible name — three bare "reclassify" buttons in a
   *  list are indistinguishable to a screen reader. */
  subject: string;
  /** The row's resolved employer token, if any — prefills the employer ask. */
  company: string | null;
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

  async function apply() {
    setBusy(true);
    setError(null);
    const named = namedCompany.trim();
    try {
      const res = await classify(
        messageId,
        // Only send the company once the backend has asked for it — sending
        // it up front would override an employer the mail itself names.
        classifyRequestBody(category, employerPrompt ? named : null, null, message),
      );
      const outcome = readClassifyOutcome(res.ok, res.body);
      if (rowStaysInQueue(outcome)) {
        if (outcome.kind === "needs-employer") {
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

  if (done) {
    return (
      <p role="status" className="text-xs text-live">
        corrected — your call is the verdict now
      </p>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Reclassify “${subject}”`}
        className="rounded border border-line px-2 py-1 text-xs font-medium text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
      >
        reclassify
      </button>
    );
  }

  return (
    <div className="flex w-full flex-wrap items-center gap-2">
      <label className="sr-only" htmlFor={`reclass-${messageId}`}>
        New category for “{subject}”
      </label>
      <select
        id={`reclass-${messageId}`}
        value={category}
        disabled={busy}
        onChange={(e) => setCategory(e.target.value)}
        className="rounded border border-line-soft bg-surface px-1.5 py-1 text-xs text-muted outline-none transition-colors hover:border-line focus:border-line-strong disabled:opacity-50"
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
        onClick={() => void apply()}
        disabled={busy || category === PLACEHOLDER || (employerPrompt !== null && !canNameCompany(namedCompany))}
        className="inline-flex items-center gap-1 rounded border border-line px-2 py-1 text-xs font-medium text-foreground transition-colors hover:border-line-strong hover:text-strong disabled:opacity-50"
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
        }}
        disabled={busy}
        className="text-xs text-dim underline-offset-2 hover:text-strong hover:underline disabled:opacity-50"
      >
        cancel
      </button>

      {employerPrompt ? (
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
