import type { CSSProperties } from "react";

import type { RailPipelineData } from "@/lib/shell/rail";

/**
 * The head of the sidebar's instrument column: the tracked total and a slim
 * stage-distribution bar (the same stage fold + accent hues as the board's
 * spine). The pulse's four derived signals stack directly beneath it
 * (`PipelinePulse layout="rail"`, mounted by `Sidebar`), so this component
 * deliberately says only what the pulse does not: how many, and how they sit
 * across the stages.
 *
 * What it USED to carry, and where that went:
 *   - the per-stage legend rows — dropped. On /dashboard they duplicated the
 *     board's spine a column away, and on the production shape (every row in
 *     one stage) they were three zeros asserting emptiness; the bar's segment
 *     tooltips keep the exact counts for a hover.
 *   - the bordered card — dropped. One card was chrome when the snapshot stood
 *     alone; around a full instrument column it was a box in a box. The column
 *     reads on the rail's own surface, separated by hairlines.
 *   - the needs-review nudge — moved into the pulse's classifier signal, which
 *     already owned that number's deep link. One number, one place.
 *
 * Honest states, no fake numbers:
 *   - `pipeline === null`  → backend unreachable / rejected → quiet note.
 *   - `total === 0`        → "nothing filed yet" (the dashboard owns onboarding).
 *
 * Motion: bar segments grow in once, staggered (`.rail-seg`, globals.css) and
 * collapse to static under `prefers-reduced-motion`.
 */

const seg = (i: number): CSSProperties => ({ ["--i" as string]: i });

export function RailPipeline({ pipeline }: { pipeline: RailPipelineData | null }) {
  // Backend down / session rejected → say so quietly, never invent numbers.
  if (!pipeline) {
    return (
      <section aria-label="Pipeline snapshot">
        <h2 className="label-caps">pipeline</h2>
        <p className="mt-2 text-xs text-dim">backend unreachable</p>
      </section>
    );
  }

  const { summary } = pipeline;
  const { total, thisWeek, stages } = summary;

  return (
    <section aria-label="Pipeline snapshot">
      <h2 className="label-caps">pipeline</h2>
      <p className="tabular mt-2 font-mono text-2xl font-semibold leading-none text-strong">
        {total}
      </p>
      <p className="mt-1 text-xs text-dim">
        {total === 0
          ? "nothing filed yet"
          : thisWeek > 0
            ? `applications · +${thisWeek} this wk`
            : "applications tracked"}
      </p>

      {total > 0 ? (
        // Slim distribution bar — same stage order + accents as the board's
        // spine; exact per-stage counts live in each segment's tooltip.
        <div
          role="img"
          aria-label={`Distribution: ${stages
            .map(({ stage, count }) => `${count} ${stage.label}`)
            .join(", ")}`}
          className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-surface-2"
        >
          {stages
            .filter(({ count }) => count > 0)
            .map(({ stage, count }, i) => (
              <span
                key={stage.key}
                title={`${stage.label} · ${count}`}
                className="rail-seg h-full"
                style={{
                  width: `${(count / total) * 100}%`,
                  backgroundColor: stage.color,
                  ...seg(i),
                }}
              />
            ))}
        </div>
      ) : null}
    </section>
  );
}
