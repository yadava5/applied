import type { ReactNode } from "react";

export interface FunnelStage {
  label: string;
  count: number;
  /** CSS colour (or var reference) for the stage accent. */
  color: string;
}

/**
 * The application pipeline as a proportional funnel: each stage's bar width
 * encodes its share of the total, so the board reads as data rather than four
 * loose columns. Presentational and prop-driven — the public demo and the
 * signed-in dashboard both feed it, so there is one funnel to design and test.
 */
export function StageFunnel({
  stages,
  total,
  caption,
  highlight,
}: {
  stages: FunnelStage[];
  total: number;
  caption: ReactNode;
  highlight?: ReactNode;
}) {
  const max = Math.max(...stages.map((s) => s.count), 1);

  return (
    <div className="rounded-xl border border-line-soft bg-surface p-5">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <span className="label-mono">{caption}</span>
        {highlight ? <span className="font-mono text-[11px] text-live">{highlight}</span> : null}
      </div>
      <div className="space-y-2.5">
        {stages.map((s) => {
          const share = total > 0 ? Math.round((s.count / total) * 100) : 0;
          return (
            <div key={s.label} className="flex items-center gap-3">
              <span className="w-24 shrink-0 font-mono text-[11px] text-muted">{s.label}</span>
              <div className="relative h-6 flex-1 overflow-hidden rounded-md bg-surface-2">
                <div
                  className="flex h-full items-center rounded-md px-2 transition-[width] duration-700 ease-out"
                  style={{
                    width: `${Math.max((s.count / max) * 100, s.count ? 12 : 0)}%`,
                    background: `color-mix(in oklab, ${s.color} 22%, transparent)`,
                    borderLeft: `2px solid ${s.color}`,
                  }}
                >
                  <span
                    className="tabular font-mono text-xs font-semibold"
                    style={{ color: s.color }}
                  >
                    {s.count}
                  </span>
                </div>
              </div>
              <span className="tabular w-10 shrink-0 text-right font-mono text-[11px] text-dim">
                {share}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
