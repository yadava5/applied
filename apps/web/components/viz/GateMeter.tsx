import { cn } from "@/lib/utils";

/**
 * The classifier's confidence drawn against the 0.85 auto-file gate — the
 * landing DecisionTrace's meter, miniaturised for dense rows (inbox verdicts,
 * the detail sheet's mail trail, the review queue). One component so every
 * surface renders the gate identically: green fill when the verdict cleared
 * it, amber when a human presides, a hairline tick where the gate sits.
 *
 * `aria-hidden` by design: the meter always sits beside the numeric
 * percentage, which is the accessible rendering of the same fact.
 */

/** The auto-file threshold — mirrors the backend's gate (see DecisionTrace). */
export const AUTO_FILE_GATE = 0.85;

export function GateMeter({
  confidence,
  gate = AUTO_FILE_GATE,
  className,
}: {
  /** 0–1. Values outside the range are clamped, never invented. */
  confidence: number;
  gate?: number;
  className?: string;
}) {
  const pct = Math.min(100, Math.max(0, confidence * 100));
  const cleared = confidence >= gate;
  return (
    <span
      data-testid="gate-meter"
      aria-hidden="true"
      className={cn(
        "relative inline-block h-1 w-14 shrink-0 rounded-full bg-line align-middle",
        className,
      )}
    >
      <span
        className="absolute inset-y-0 left-0 rounded-full"
        style={{ width: `${pct}%`, background: cleared ? "var(--green)" : "var(--amber)" }}
      />
      <span className="absolute -inset-y-[3px] w-px bg-line-strong" style={{ left: `${gate * 100}%` }} />
    </span>
  );
}
