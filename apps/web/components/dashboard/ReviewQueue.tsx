"use client";

import { ExternalLink, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

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

function shortDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function ReviewRow({ item }: { item: ReviewItem }) {
  const router = useRouter();
  const [category, setCategory] = useState("applied");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function classify() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/applications/review/${encodeURIComponent(item.message_id)}/classify`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category }),
        },
      );
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
        setError(typeof body.detail === "string" ? body.detail : "Couldn't classify this item.");
        setBusy(false);
        return;
      }
      router.refresh();
    } catch {
      setError("Couldn't classify this item.");
      setBusy(false);
    }
  }

  const sender = item.sender_name || item.sender_email || "unknown sender";

  return (
    <li className="rounded-lg border border-line-soft bg-surface-2 p-3">
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 text-sm font-medium text-strong">
          <span className="truncate">{item.subject || "(no subject)"}</span>
        </p>
        <span className="tabular shrink-0 font-mono text-[10px] text-dim">{shortDate(item.received_at)}</span>
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
 */
export function ReviewQueue({ items }: { items: ReviewItem[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-label="Needs classification" className="rounded-2xl border border-line-soft bg-surface p-4 sm:p-5">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold tracking-tight text-strong">Needs classification</h2>
        <span className="font-mono text-[11px] text-dim">
          {items.length} uncertain · classifying trains the model
        </span>
      </div>
      <ul className="space-y-2">
        {items.map((item) => (
          <ReviewRow key={item.message_id} item={item} />
        ))}
      </ul>
    </section>
  );
}
