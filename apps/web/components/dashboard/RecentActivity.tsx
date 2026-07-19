import { type Application, STAGES, recentApplications, stageOf } from "@/lib/dashboard/summary";

function filedOn(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/**
 * The most-recently-filed applications as a compact activity feed. It reads
 * only from the timestamped rows we actually have, so it never fabricates
 * events — the honest counterpart to a fuller email-level timeline the backend
 * could feed later.
 */
export function RecentActivity({ applications, limit = 6 }: { applications: Application[]; limit?: number }) {
  const recent = recentApplications(applications, limit);
  if (recent.length === 0) return null;

  return (
    <section aria-labelledby="recent-activity" className="rounded-xl border border-line-soft bg-surface">
      <div className="flex items-baseline justify-between border-b border-line-soft px-4 py-3">
        <h2 id="recent-activity" className="label-mono">
          recent activity
        </h2>
        <span className="font-mono text-[11px] text-dim">latest {recent.length}</span>
      </div>
      <ul>
        {recent.map((app) => {
          const stage = STAGES.find((s) => s.key === stageOf(app.status))!;
          return (
            <li
              key={app.id}
              className="flex items-center justify-between gap-4 border-b border-line-soft px-4 py-3 last:border-b-0"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span
                  className="h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ background: stage.color }}
                  aria-hidden="true"
                />
                <div className="min-w-0">
                  <p className="truncate text-sm text-strong">
                    {app.company} <span className="text-dim">·</span>{" "}
                    <span className="text-muted">{app.position}</span>
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-3 text-right">
                <span
                  className="font-mono text-[10px] uppercase tracking-wide"
                  style={{ color: stage.color }}
                >
                  {stage.label}
                </span>
                <span className="tabular w-24 font-mono text-[11px] text-dim">{filedOn(app.created_at)}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
