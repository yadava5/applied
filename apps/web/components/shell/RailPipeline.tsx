import type { CSSProperties } from "react";
import Link from "next/link";

import type { RailPipelineData } from "@/lib/shell/rail";

/**
 * The sidebar's pipeline snapshot — a dashboard-in-the-rail.
 *
 * Turns the nav's former dead space into glanceable signal: the tracked total,
 * a slim stage-distribution bar (the same stage fold + accent hues as the
 * dashboard funnel), a per-stage legend, and — when the classifier is holding
 * mail — an amber "N need review" nudge that deep-links straight to the
 * dashboard's needs-classification queue.
 *
 * Honest states, no fake numbers:
 *   - `pipeline === null`  → backend unreachable / rejected → quiet mono note.
 *   - `total === 0`        → "nothing filed yet" (the dashboard owns onboarding).
 *   - review nudge renders independently of the total — zero *filed*
 *     applications can still mean held mail waiting on the user.
 *
 * Motion: bar segments grow in once, staggered (`.rail-seg`, globals.css) and
 * the nudge arrow slides on hover — both collapse to static under
 * `prefers-reduced-motion`.
 */

const seg = (i: number): CSSProperties => ({ ["--i" as string]: i });

/** Amber deep-link into the dashboard's needs-classification queue. */
function ReviewNudge({ count }: { count: number }) {
  return (
    <Link
      href="/dashboard#needs-classification"
      className="group mt-3 flex items-center gap-1.5 rounded-lg border border-review/40 px-2.5 py-1.5 font-mono text-[11px] text-review transition-colors hover:border-review focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-viz-rules"
    >
      <span className="tabular">{count}</span>
      <span>need{count === 1 ? "s" : ""} review</span>
      <span
        aria-hidden="true"
        className="ml-auto transition-transform motion-safe:group-hover:translate-x-0.5"
      >
        →
      </span>
    </Link>
  );
}

export function RailPipeline({ pipeline }: { pipeline: RailPipelineData | null }) {
  // Backend down / session rejected → say so quietly, never invent numbers.
  if (!pipeline) {
    return (
      <section
        aria-label="Pipeline snapshot"
        className="rounded-xl border border-line-soft p-3"
      >
        <h2 className="label-mono">pipeline</h2>
        <p className="mt-2 font-mono text-[11px] text-dim">backend unreachable</p>
      </section>
    );
  }

  const { summary, needsReview } = pipeline;
  const { total, thisWeek, stages } = summary;

  return (
    <section
      aria-label="Pipeline snapshot"
      className="rounded-xl border border-line-soft p-3 transition-colors hover:border-line"
    >
      <h2 className="label-mono">pipeline</h2>
      <p className="tabular mt-2 font-mono text-2xl font-semibold leading-none text-strong">
        {total}
      </p>
      <p className="mt-1 font-mono text-[11px] text-dim">
        {total === 0
          ? "nothing filed yet"
          : thisWeek > 0
            ? `applications · +${thisWeek} this wk`
            : "applications tracked"}
      </p>

      {total > 0 ? (
        <>
          {/* Slim distribution bar — same stage order + accents as the funnel. */}
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

          <ul className="mt-3 space-y-1.5">
            {stages.map(({ stage, count }) => (
              <li key={stage.key} className="flex items-center gap-2 font-mono text-[11px]">
                <span
                  aria-hidden="true"
                  className="h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: stage.color }}
                />
                <span className="text-muted">{stage.label}</span>
                <span className="tabular ml-auto text-strong">{count}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {needsReview > 0 ? <ReviewNudge count={needsReview} /> : null}
    </section>
  );
}
