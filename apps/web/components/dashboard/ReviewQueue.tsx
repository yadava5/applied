"use client";

import { ExternalLink, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { shortDate } from "@/lib/dashboard/dates";
import {
  CLASSIFY_FAILED,
  canNameCompany,
  classifyRequestBody,
  employerPromptFor,
  readClassifyOutcome,
  rowStaysInQueue,
} from "@/lib/dashboard/review";

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
}

/** Category choices → backend EmailCategory values. "other" dismisses + trains. */
const CATEGORY_CHOICES: { value: string; label: string }[] = [
  { value: "applied", label: "applied" },
  { value: "interview", label: "interviewing" },
  { value: "assessment", label: "assessment" },
  { value: "offer", label: "offer" },
  { value: "rejection", label: "rejection" },
  { value: "other", label: "not job-related" },
];

function ReviewRow({ item }: { item: ReviewItem }) {
  const router = useRouter();
  const [category, setCategory] = useState("applied");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Set when the backend filed nothing because it couldn't name the employer. */
  const [employerPrompt, setEmployerPrompt] = useState<string | null>(null);
  const [company, setCompany] = useState("");

  /**
   * Send the decision. A 2xx is NOT success on its own: `needs_employer: true`
   * means nothing was filed and the row is still in the queue, so we keep it on
   * screen, say so, and ask for the company instead of refreshing the row away.
   */
  async function classify() {
    setBusy(true);
    setError(null);
    const named = company.trim();
    try {
      const res = await fetch(
        `/api/applications/review/${encodeURIComponent(item.message_id)}/classify`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(classifyRequestBody(category, named)),
        },
      );
      const outcome = readClassifyOutcome(res.ok, await res.json().catch(() => ({})));

      if (rowStaysInQueue(outcome)) {
        // Nothing changed server-side, so there is nothing to re-fetch — say
        // what is missing and let the user answer it here. Never leave the
        // button spinning: that is what made the 2xx-that-filed-nothing look
        // like the click had simply done nothing.
        if (outcome.kind === "needs-employer") setEmployerPrompt(employerPromptFor(named));
        else setError(outcome.detail);
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
      <p className="truncate text-xs text-muted">{sender}</p>
      {item.snippet ? (
        <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-dim">{item.snippet}</p>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor={`cat-${item.message_id}`}>
          Classify this email
        </label>
        <select
          id={`cat-${item.message_id}`}
          value={category}
          disabled={busy}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded border border-line-soft bg-surface px-1.5 py-1 font-mono text-[11px] text-muted outline-none transition-colors hover:border-line focus:border-line-strong disabled:opacity-50"
        >
          {CATEGORY_CHOICES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={classify}
          disabled={busy}
          className="inline-flex items-center gap-1 rounded border border-line px-2 py-1 font-mono text-[11px] text-foreground transition-colors hover:border-line-strong hover:text-strong disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : null}
          classify
        </button>
        {item.gmail_link ? (
          <a
            href={item.gmail_link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-mono text-[10px] text-dim underline-offset-2 hover:text-strong hover:underline"
          >
            <ExternalLink className="h-3 w-3" aria-hidden />
            open in gmail
          </a>
        ) : null}
      </div>

      {/* The correction affordance for a decision the backend accepted but
          could not file: amber (the needs-review hue), not red — nothing broke,
          the message simply doesn't name its employer. */}
      {employerPrompt ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy && canFile) void classify();
          }}
          className="mt-2 rounded border border-review/40 bg-surface px-2.5 py-2"
        >
          <p role="status" className="font-mono text-[10px] leading-relaxed text-review">
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
              className="min-w-0 flex-1 rounded border border-line-soft bg-surface-2 px-1.5 py-1 font-mono text-[11px] text-strong outline-none transition-colors placeholder:text-dim hover:border-line focus:border-line-strong disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={busy || !canFile}
              className="inline-flex shrink-0 items-center gap-1 rounded border border-review/50 px-2 py-1 font-mono text-[11px] text-strong transition-colors hover:border-review disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : null}
              file it
            </button>
          </div>
        </form>
      ) : null}

      {error ? (
        <p role="alert" className="mt-1.5 font-mono text-[10px] text-reject">
          {error}
        </p>
      ) : null}
    </li>
  );
}

/**
 * The needs-classification queue — the real destination of the dashboard's
 * "N need classification" number. Each uncertain verdict (0.70–0.85 band, or a
 * confident one whose employer couldn't be named) gets a one-click category
 * decision that both persists (a lifecycle choice becomes a sticky application)
 * and trains the model. Choosing "not job-related" removes it from the queue.
 *
 * A decision the backend accepts but cannot file — `needs_employer: true`, the
 * employer isn't nameable from the message — keeps its row right here and asks
 * for the company inline, because a 2xx that filed nothing used to look
 * identical to one that worked ("Crusoe | Application Received" in production).
 */
/**
 * Past this many rows the queue overflows its fixed height and scrolls
 * internally rather than running the page down — the taller review rows fit
 * ~4 before the `max-h-[30rem]` cap engages, so the "scroll" hint + bottom
 * fade appear from the 5th on.
 */
const SCROLL_AFTER = 4;

export function ReviewQueue({ items }: { items: ReviewItem[] }) {
  if (items.length === 0) return null;
  const overflowing = items.length > SCROLL_AFTER;
  return (
    <section id="needs-classification" aria-label="Needs classification" className="scroll-mt-6 rounded-2xl border border-line-soft bg-surface p-4 sm:p-5">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold tracking-tight text-strong">Needs classification</h2>
        <span className="shrink-0 font-mono text-[11px] text-dim">
          {items.length} uncertain{overflowing ? " · scroll" : ""} · classifying trains the model
        </span>
      </div>
      {/* Capped, internally-scrolling list so a long queue never extends the
       * whole page; the wrapper anchors the bottom fade affordance. */}
      <div className="relative">
        <ul className="scroll-area max-h-[30rem] space-y-2 overflow-y-auto">
          {items.map((item) => (
            <ReviewRow key={item.message_id} item={item} />
          ))}
        </ul>
        {overflowing ? (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-surface to-transparent"
          />
        ) : null}
      </div>
    </section>
  );
}
