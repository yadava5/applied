import { DECISION } from "./copy";

/**
 * The decision, drawn: two bars, one shipped. The scale starts at 0.90 —
 * stated on the figure — because the whole story lives in the last decimal
 * places; from zero the two bars would be indistinguishable and the figure
 * would say nothing. Widths are static CSS so the figure is server-rendered,
 * motion-free and identical under prefers-reduced-motion.
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
          className={`h-full rounded-full ${shipped ? "bg-viz-rules" : "bg-line-strong"}`}
          style={{ width: width(value) }}
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
