import { ApplicationCard } from "@/components/dashboard/ApplicationCard";
import { filedAt, shortDate } from "@/lib/dashboard/dates";
import { type Application, STAGES, qualifierOf, stageOf } from "@/lib/dashboard/summary";

/**
 * Read-only card for the public demo + sample previews: no correction controls
 * (they would 401 without a session). Still honours the real received date.
 */
function StaticApplicationCard({ app }: { app: Application }) {
  const qualifier = qualifierOf(app.status);
  const stage = STAGES.find((s) => s.key === stageOf(app.status))!;
  const filed = filedAt(app);
  return (
    <li
      className="rounded-lg border border-line-soft bg-surface-2 p-3 transition-colors hover:border-line-strong"
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
      {app.position ? <p className="truncate text-xs text-muted">{app.position}</p> : null}
      {app.notes && <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-dim">{app.notes}</p>}
      <p className="mt-2 font-mono text-[10px] text-dim">filed {shortDate(filed)}</p>
    </li>
  );
}

/**
 * Status-grouped pipeline board. `accepted` folds into the offered column and
 * `withdrawn` into rejected, each keeping a qualifier tag so no application is
 * ever invisible.
 *
 * On the real dashboard (`interactive`, the default) each row is clickable +
 * correctable (open in Gmail, change stage, dismiss/delete). The public demo
 * and sample previews pass `interactive={false}` for a read-only board so their
 * sample rows never fire real, auth-gated mutations.
 */
/**
 * Above this count a column overflows its fixed height and scrolls internally,
 * so we surface the "scroll" hint + bottom fade. Chosen to match the capped
 * height (`max-h-[30rem]` ≈ 4–5 cards), the point past which the page would
 * otherwise stretch. A pure count is deterministic (SSR-safe, no measurement)
 * and errs toward showing the affordance a touch early rather than never.
 */
const SCROLL_AFTER = 4;

export function PipelineBoard({
  applications,
  interactive = true,
}: {
  applications: Application[];
  interactive?: boolean;
}) {
  return (
    <div className="grid items-stretch gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {STAGES.map((stage) => {
        const items = applications.filter((a) => stageOf(a.status) === stage.key);
        const overflowing = items.length > SCROLL_AFTER;
        return (
          <section
            key={stage.key}
            aria-label={`${stage.label} — ${items.length}`}
            className="flex flex-col rounded-xl border border-line-soft bg-surface p-3"
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
              <span className="inline-flex items-baseline gap-1.5">
                {overflowing ? (
                  <span className="font-mono text-[9px] uppercase tracking-wide text-dim">scroll</span>
                ) : null}
                <span className="tabular font-mono text-xs text-muted">{items.length}</span>
              </span>
            </div>
            {/* Fixed, uniform scroll region: caps tall columns at ~4–5 cards and
             * keeps every column the same height so the row stays balanced no
             * matter how lopsided the counts are. The wrapper anchors the fade. */}
            <div className="relative min-h-0 flex-1">
              <ul className="scroll-area max-h-[30rem] space-y-2 overflow-y-auto">
                {items.length === 0 ? (
                  <li className="rounded-lg border border-dashed border-line-soft p-3 text-center font-mono text-[11px] text-dim">
                    none yet
                  </li>
                ) : (
                  items.map((app) =>
                    interactive ? (
                      <ApplicationCard key={app.id} app={app} />
                    ) : (
                      <StaticApplicationCard key={app.id} app={app} />
                    ),
                  )
                )}
              </ul>
              {overflowing ? (
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-surface to-transparent"
                />
              ) : null}
            </div>
          </section>
        );
      })}
    </div>
  );
}
