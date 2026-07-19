import { type Application, STAGES, qualifierOf, stageOf } from "@/lib/dashboard/summary";

/** Locale-stable short date ("Jul 14") — deterministic across server/client. */
function filedOn(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function ApplicationCard({ app }: { app: Application }) {
  const qualifier = qualifierOf(app.status);
  const stage = STAGES.find((s) => s.key === stageOf(app.status))!;
  return (
    <li
      className="group rounded-lg border border-line-soft bg-surface-2 p-3 transition-colors hover:border-line-strong"
      style={{ borderLeft: `2px solid color-mix(in oklab, ${stage.color} 55%, transparent)` }}
    >
      <p className="flex items-center gap-2 text-sm font-medium text-strong">
        <span className="truncate">{app.company}</span>
        {qualifier && (
          <span className="shrink-0 rounded-full border border-line px-1.5 py-px font-mono text-[9px] uppercase tracking-wide text-muted">
            {qualifier}
          </span>
        )}
      </p>
      <p className="truncate text-xs text-muted">{app.position}</p>
      {app.notes && <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-dim">{app.notes}</p>}
      <p className="mt-2 font-mono text-[10px] text-dim">filed {filedOn(app.created_at)}</p>
    </li>
  );
}

/**
 * Status-grouped pipeline board. `accepted` folds into the offered column and
 * `withdrawn` into rejected, each keeping a qualifier tag so no application is
 * ever invisible. Presentational — the same board the public demo renders,
 * driven by real rows on the dashboard.
 */
export function PipelineBoard({ applications }: { applications: Application[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {STAGES.map((stage) => {
        const items = applications.filter((a) => stageOf(a.status) === stage.key);
        return (
          <section
            key={stage.key}
            aria-label={`${stage.label} — ${items.length}`}
            className="rounded-xl border border-line-soft bg-surface p-3"
          >
            <div className="mb-2 flex items-baseline justify-between px-1">
              <span className="label-mono inline-flex items-center gap-1.5">
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ background: stage.color }}
                  aria-hidden="true"
                />
                {stage.label}
              </span>
              <span className="tabular font-mono text-xs text-muted">{items.length}</span>
            </div>
            <ul className="space-y-2">
              {items.length === 0 ? (
                <li className="rounded-lg border border-dashed border-line-soft p-3 text-center font-mono text-[11px] text-dim">
                  none yet
                </li>
              ) : (
                items.map((app) => <ApplicationCard key={app.id} app={app} />)
              )}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
