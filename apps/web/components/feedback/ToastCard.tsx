"use client";

import { X } from "lucide-react";

import type { FeedbackKind } from "@/lib/feedback/coalesce";

/**
 * The face of one toast — rendered through sonner's `toast.custom`, so sonner
 * contributes stacking, swipe and the polite live region while every visible
 * pixel is this app's: surface + hairline tokens (both themes resolve through
 * the CSS variables), Atkinson prose inherited from `body`, and mono reserved
 * for the one machine value on the card — the merged-occurrence count.
 *
 * The kind dot reuses the semantic ink exactly as the rest of the app does:
 * green = it worked, red = it failed, amber = time-bound attention (an undo
 * window closing). Errors add `role="alert"` so they announce assertively;
 * successes ride the toaster's polite region and interrupt nothing.
 */
export function ToastCard({
  kind,
  text,
  countBadge,
  actionLabel,
  onAction,
  onDismiss,
}: {
  kind: FeedbackKind;
  text: string;
  /** `×N` when occurrences merged without a countMessage — a machine value,
   *  so it is the one mono glyph run on the card. */
  countBadge: string | null;
  actionLabel?: string;
  onAction?: () => void;
  onDismiss: () => void;
}) {
  const dot = kind === "error" ? "bg-reject" : kind === "undo" ? "bg-review" : "bg-live";

  return (
    <div
      role={kind === "error" ? "alert" : undefined}
      className="pointer-events-auto flex w-full items-center gap-3 rounded-xl border border-line-strong bg-surface py-3 pl-4 pr-3 shadow-[0_16px_48px_-16px_rgba(0,0,0,0.65)]"
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
      <p className="min-w-0 flex-1 text-sm leading-snug text-foreground">{text}</p>
      {countBadge ? (
        <span className="shrink-0 rounded border border-line px-1.5 py-0.5 font-mono text-[11px] text-muted tabular">
          {countBadge}
        </span>
      ) : null}
      {actionLabel && onAction ? (
        // A real focusable <button> — reachable by keyboard, and the toaster
        // pauses this card's countdown while it holds focus, so the window
        // cannot close under the user mid-Tab.
        <button
          type="button"
          onClick={onAction}
          className="shrink-0 rounded border border-line px-2 py-1 text-xs text-strong transition-colors hover:border-line-strong hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
        >
          {actionLabel}
        </button>
      ) : null}
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted transition-colors hover:bg-surface-2 hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}
