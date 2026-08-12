import { ExternalLink } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The two things that let a reader check a verdict instead of taking it on
 * trust: what the message said, and a way to open it.
 *
 * Extracted from the filed ledger's row, which is where both were first
 * written, so the live scan can SHARE them rather than grow a second copy.
 * This repo's signature defect is exactly that second copy — the status
 * vocabulary reached three of them and shipped a production 422 — and a
 * preview that is clamped to one line in one view and two in another is the
 * same bug in a quieter register.
 *
 * Both render `null` for absent data rather than an empty shell. That is the
 * whole contract: a message Gmail returned no snippet for must draw no line,
 * and one with no resolvable link must offer no control, because a dead
 * control is worse than a missing one.
 */

/** Gmail's preview of the message. One line — this is a list people triage. */
export function MailSnippet({
  snippet,
  className,
}: {
  snippet: string | null | undefined;
  className?: string;
}) {
  if (!snippet) return null;
  return (
    <p className={cn("mt-0.5 line-clamp-1 text-[11px] leading-snug text-dim", className)}>
      {snippet}
    </p>
  );
}

/**
 * Open this message in Gmail. External, new tab, and named for the message it
 * opens — a row of identical "open" links is unusable with a screen reader,
 * and the subject is the only thing that tells them apart.
 */
export function OpenInGmail({
  href,
  subject,
  className,
}: {
  href: string | null | undefined;
  subject: string;
  className?: string;
}) {
  if (!href) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`Open “${subject}” in Gmail`}
      title="open in gmail"
      className={cn(
        "grid h-6 w-6 shrink-0 place-items-center rounded text-dim transition-colors hover:bg-surface-2 hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong",
        className,
      )}
    >
      <ExternalLink className="h-3.5 w-3.5" aria-hidden />
    </a>
  );
}
