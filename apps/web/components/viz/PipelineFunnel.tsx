import { DEMO_APPLICATIONS, type DemoStatus } from "@/lib/demo/demoData";

const STAGES: { status: DemoStatus; label: string; color: string }[] = [
  { status: "applied", label: "applied", color: "var(--text-muted)" },
  { status: "interviewing", label: "interviewing", color: "var(--viz-embeddings)" },
  { status: "offered", label: "offered", color: "var(--green)" },
  { status: "rejected", label: "rejected", color: "var(--red)" },
];

/**
 * The application pipeline as a proportional funnel: each stage's bar width
 * encodes its share of the 10 tracked applications, so the board reads as
 * data — with an "advanced past applied" conversion callout.
 */
export function PipelineFunnel() {
  const total = DEMO_APPLICATIONS.length;
  const counts = STAGES.map((s) => ({
    ...s,
    n: DEMO_APPLICATIONS.filter((a) => a.status === s.status).length,
  }));
  const max = Math.max(...counts.map((c) => c.n), 1);
  const advanced = counts
    .filter((c) => c.status === "interviewing" || c.status === "offered")
    .reduce((sum, c) => sum + c.n, 0);
  const advancedPct = Math.round((advanced / total) * 100);

  return (
    <div className="rounded-xl border border-line-soft bg-surface p-5">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <span className="label-mono">pipeline distribution · {total} applications</span>
        <span className="font-mono text-[11px] text-live">
          {advancedPct}% advanced past applied
        </span>
      </div>
      <div className="space-y-2.5">
        {counts.map((c) => (
          <div key={c.status} className="flex items-center gap-3">
            <span className="w-24 shrink-0 font-mono text-[11px] text-muted">{c.label}</span>
            <div className="relative h-6 flex-1 overflow-hidden rounded-md bg-surface-2">
              <div
                className="flex h-full items-center rounded-md px-2 transition-all"
                style={{
                  width: `${Math.max((c.n / max) * 100, c.n ? 12 : 0)}%`,
                  background: `color-mix(in oklab, ${c.color} 22%, transparent)`,
                  borderLeft: `2px solid ${c.color}`,
                }}
              >
                <span className="tabular font-mono text-xs font-semibold" style={{ color: c.color }}>
                  {c.n}
                </span>
              </div>
            </div>
            <span className="tabular w-10 shrink-0 text-right font-mono text-[11px] text-dim">
              {Math.round((c.n / total) * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
