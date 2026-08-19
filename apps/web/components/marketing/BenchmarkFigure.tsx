import { DECISION } from "./copy";

/**
 * The decision, drawn: two bars, one shipped. The scale starts at 0.90 —
 * stated on the figure — because the whole story lives in the last decimal
 * places; from zero the two bars would be indistinguishable and the figure
 * would say nothing.
 *
 * The WIDTHS are still static CSS: the figure is server-rendered, and every
 * consumer that does nothing else gets exactly what it always got. What is new
 * is that the bars are drawn from their left edge by `scaleX(var(--bench))`,
 * which DEFAULTS TO 1 — so "no one is driving" is the composed figure, not an
 * empty one. A caller that wants the ladder to draw itself under the reader's
 * scroll writes `--bench` on any ancestor (`ClaimsDescent` does); a caller
 * that does not, and a visitor with reduced motion or no JS, sees the finished
 * bars and never learns there was a variable.
 *
 * Both bars are on ONE clock on purpose. Staging them so the shipped bar
 * visibly overtakes the other would be a better story and a false frame: these
 * are lengths on an F1 axis, and any instant at which the cascade's bar is
 * longer than the rules' states the opposite of the measurement. On one clock
 * the ratio between them is correct in every frame, and the rules bar is ahead
 * in all of them — which is the story anyway.
 */
const FLOOR = 0.9;

function width(value: string): string {
  return `${((Number(value) - FLOOR) / (1 - FLOOR)) * 100}%`;
}

function Bar({
  label,
  value,
  shipped,
}: {
  label: string;
  value: string;
  shipped?: boolean;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-4">
        <p className={`text-sm ${shipped ? "font-medium text-strong" : "text-muted"}`}>{label}</p>
        <p className={`tabular font-mono text-sm ${shipped ? "font-semibold text-strong" : "text-muted"}`}>
          {value}
        </p>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-2">
        <div
          className={`h-full origin-left rounded-full ${shipped ? "bg-viz-rules" : "bg-line-strong"}`}
          style={{ width: width(value), transform: "scaleX(var(--bench, 1))" }}
        />
      </div>
    </div>
  );
}

export function BenchmarkFigure({ className }: { className?: string }) {
  return (
    <figure className={`rounded-xl border border-line-soft bg-surface p-5 sm:p-6 ${className ?? ""}`}>
      <div className="flex flex-col gap-4">
        <Bar label={DECISION.rulesLabel} value={DECISION.rulesF1} shipped />
        <Bar label={DECISION.cascadeLabel} value={DECISION.cascadeF1} />
      </div>
      <figcaption className="mt-4 font-mono text-[11px] text-dim">
        {DECISION.window} · scale starts at 0.90
      </figcaption>
    </figure>
  );
}
