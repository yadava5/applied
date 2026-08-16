import { classifyWithRules } from "@/lib/demo/rulesLayer";
import { cn } from "@/lib/utils";

import { OFFER_EMAIL, VERDICT_EMAIL } from "./verdictEmailData";

/**
 * The receipt for a row the classifier moved — one derivation, two forms.
 *
 * The right side of the arrow is DERIVED, not typed: `classifyWithRules` runs
 * on the given email's whole body here, at render, and the chip prints
 * whatever it returns — the same call the descent shows the visitor live.
 * Server-safe: pure inputs, no dates, no state.
 *
 *   · `ChangedRow` — the free-standing card. Variant C's hero (the descent's
 *     own email, so its "the email that did it ↓" points at the exhibit
 *     below), and the window act's below-`lg` staging, where it carries the
 *     act's offer instead and hands off with the bridge line.
 *   · `ReceiptStrip` — the same receipt as window chrome: one bar docked to
 *     the framed window's foot at beats 1–2 (`WindowAct` → `LandingBoard`).
 *     It mirrors the provenance bar at the frame's head, so the receipt
 *     belongs to the window rather than floating over the board — the
 *     floating card was measured detached in a cleared strip at every
 *     mid-scroll offset, reading as debris instead of as the move's payoff.
 *     It also ANNOUNCES: it reveals before the row travels (see tempo.ts),
 *     so the visitor knows what to watch before the move happens.
 */

type ReceiptEmail = typeof VERDICT_EMAIL | typeof OFFER_EMAIL;

/** The classifier's category vocabulary → the board's stage vocabulary. */
const STAGE_OF_CATEGORY: Record<string, string> = {
  rejection: "rejected",
  offer: "offered",
  interview: "interviewing",
  assessment: "assessment",
  applied: "applied",
};

/** The board's own stage hues (lib/dashboard/summary.ts), as chip classes.
 *  Both text tones measured on `--surface` in both themes: 10.93/5.02:1
 *  (offered green) and 7.00/5.70:1 (interviewing violet) — AA at chip size. */
const STAGE_TONE: Record<string, string> = {
  offered: "border-live/50 text-live",
  interviewing: "border-viz-embeddings/50 text-viz-embeddings",
  rejected: "border-reject/50 text-reject-ink",
};

/* The stage chip IS computed live; the MOVE on this page is the window act
 * writing the verdict through its own fixture transport (MarketingBoard). So
 * both captions claim the classifier's work, not the classifier's hand on
 * this particular row. One literal each, shared by both forms. */
const PROVENANCE = "what the classifier does — replayed on fixture data";
/** Points at the descent's exhibit — true only where that exhibit shows THIS
 *  email (variant C's hero over `VERDICT_EMAIL`). */
const POINTER = "the email that did it ↓";
/** The act's hand-off instead: its own mail says "offer" in the subject, and
 *  the descent's whole claim is the reply that does not. */
const BRIDGE = "not every reply says its verdict ↓";

function movedStage(email: ReceiptEmail): string {
  const verdict = classifyWithRules(email.subject, email.body, email.senderEmail);
  return STAGE_OF_CATEGORY[verdict.category] ?? verdict.category;
}

function StageMove({ stage }: { stage: string }) {
  return (
    <p className="flex shrink-0 items-center gap-2.5" aria-label={`stage moved: applied to ${stage}`}>
      <span className="label-caps text-dim line-through decoration-line-strong">applied</span>
      <span aria-hidden className="text-dim">
        →
      </span>
      <span
        className={cn(
          "label-caps rounded-md border px-2 py-1",
          STAGE_TONE[stage] ?? "border-line-strong text-strong",
        )}
      >
        {stage}
      </span>
    </p>
  );
}

export function ChangedRow({
  email = VERDICT_EMAIL,
  foot = "pointer",
}: {
  email?: ReceiptEmail;
  foot?: "pointer" | "bridge";
}) {
  const stage = movedStage(email);

  return (
    <figure className="overflow-hidden rounded-xl border border-line bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-5 py-4">
        <div className="min-w-0">
          <p className="truncate text-base font-medium text-strong">{email.company}</p>
          <p className="truncate text-sm text-muted">{email.role}</p>
        </div>
        <StageMove stage={stage} />
      </div>
      <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-line-soft px-5 py-2.5">
        <span className="inline-flex items-center gap-2 text-xs text-dim">
          <span className="h-1.5 w-1.5 rounded-full bg-live" aria-hidden />
          {PROVENANCE}
        </span>
        <span aria-hidden className="text-xs text-dim">
          {foot === "pointer" ? POINTER : BRIDGE}
        </span>
      </figcaption>
    </figure>
  );
}

/**
 * The receipt as the window's own foot bar. Flush edges, no radius — the
 * frame's `overflow-clip` rounds its corners — and `border-t` on `bg-surface`
 * so it reads as chrome, the mirror of the provenance bar at the frame's
 * head. The role hides below `xl` so the bar keeps one line at 1024, where
 * the caption and the bridge carry the story.
 */
export function ReceiptStrip() {
  const stage = movedStage(OFFER_EMAIL);

  return (
    <figure className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t border-line-soft bg-surface px-5 py-2.5">
      <div className="flex min-w-0 items-baseline gap-2.5">
        <p className="truncate text-sm font-medium text-strong">{OFFER_EMAIL.company}</p>
        <p className="hidden truncate text-xs text-muted xl:block">{OFFER_EMAIL.role}</p>
      </div>
      <StageMove stage={stage} />
      <figcaption className="ml-auto flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 text-xs text-dim">
        <span className="inline-flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-live" aria-hidden />
          {PROVENANCE}
        </span>
        <span aria-hidden>{BRIDGE}</span>
      </figcaption>
    </figure>
  );
}
