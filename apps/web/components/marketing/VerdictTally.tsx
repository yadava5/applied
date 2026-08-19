import type { CSSProperties } from "react";

import { Reveal } from "@/components/landing/Reveal";
import { classifyWithRules } from "@/lib/demo/rulesLayer";
import { cn } from "@/lib/utils";

import { CLAIMS } from "./copy";
import { PREVIEW_CHARS, VERDICT_EMAIL } from "./verdictEmailData";

/**
 * The arithmetic behind the two verdict chips: the engine's per-category
 * tallies for both runs, side by side.
 *
 * It exists to fill the one screen of the descent that had nothing on its
 * claim side — micro-beat two, where a single short paragraph floated in an
 * empty column while the chips beside it announced the disagreement. What
 * belongs there is the mechanism: `classifyWithRules` returns its raw
 * per-category scores, so this renders the same two calls the chips print,
 * one level deeper. Nothing is typed — categories, scores and both winners
 * are read from the engine, and if `rules.json` changes this figure changes
 * with it, exactly like `VerdictEmail`.
 *
 * Pure and date-free (prerender-safe, same as the rest of the exhibit
 * family). The bars are `.bar-grow` under a `Reveal`, so they draw once on
 * arrival and rest at full width under reduced motion or without JS-driven
 * observation.
 */

/** Categories worth a row: scored above zero by either run, best first. The
 *  cap keeps the figure a glance — every category past it scored nothing. */
const MAX_ROWS = 4;

export function VerdictTally({ className }: { className?: string }) {
  const { senderEmail, subject, body } = VERDICT_EMAIL;
  const runs = [
    {
      name: CLAIMS.verdict.tallyPreview,
      verdict: classifyWithRules(subject, body.slice(0, PREVIEW_CHARS), senderEmail),
      fired: false,
    },
    {
      name: CLAIMS.verdict.tallyBody,
      verdict: classifyWithRules(subject, body, senderEmail),
      fired: true,
    },
  ];

  const categories = [
    ...new Set(runs.flatMap((run) => Object.keys(run.verdict.scores))),
  ]
    .filter((cat) => runs.some((run) => (run.verdict.scores[cat] ?? 0) > 0))
    .sort(
      (a, b) =>
        Math.max(...runs.map((r) => r.verdict.scores[b] ?? 0)) -
        Math.max(...runs.map((r) => r.verdict.scores[a] ?? 0)),
    )
    .slice(0, MAX_ROWS);
  const top = Math.max(
    1,
    ...categories.flatMap((cat) => runs.map((r) => r.verdict.scores[cat] ?? 0)),
  );

  return (
    <Reveal className={className}>
      <p className="label-caps mb-2">{CLAIMS.verdict.tallyLabel}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {runs.map((run) => (
          <div
            key={run.name}
            className={cn(
              "rounded-lg border px-3 py-2.5",
              run.fired ? "border-viz-rules/50 bg-surface" : "border-line-soft bg-surface",
            )}
          >
            <p className="label-caps flex items-center gap-2">
              {run.fired && <span className="h-1.5 w-1.5 rounded-full bg-viz-rules" aria-hidden />}
              {run.name}
            </p>
            <dl className="mt-2.5 space-y-2">
              {categories.map((cat, i) => {
                const score = run.verdict.scores[cat] ?? 0;
                const winner = cat === run.verdict.category;
                return (
                  <div
                    key={cat}
                    className="grid grid-cols-[5.5rem_minmax(0,1fr)_3ch] items-center gap-2"
                  >
                    <dt
                      className={cn(
                        "truncate text-xs",
                        winner ? "font-medium text-strong" : "text-dim",
                      )}
                    >
                      {cat}
                    </dt>
                    <dd className="h-1.5 overflow-hidden rounded-full bg-surface-2">
                      <div
                        className={cn(
                          "bar-grow h-full rounded-full",
                          winner && run.fired ? "bg-viz-rules" : "bg-line-strong",
                        )}
                        style={
                          {
                            "--bar-w": `${(Math.max(0, score) / top) * 100}%`,
                            "--i": i,
                          } as CSSProperties
                        }
                      />
                    </dd>
                    <dd
                      className={cn(
                        "tabular text-right font-mono text-xs",
                        winner ? "text-strong" : "text-dim",
                      )}
                    >
                      {score}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs leading-relaxed text-dim">{CLAIMS.verdict.tallyNote}</p>
    </Reveal>
  );
}
