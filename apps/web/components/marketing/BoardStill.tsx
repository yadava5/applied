import { NEW_TAB } from "./chrome";
import { BOARD } from "./copy";

/**
 * The board below `lg` — a still, and it says so.
 *
 * At 375px a live `PipelineBoard` is not a demo, it is a struggle: drag needs
 * a pointer, the spine collapses to chips, and the detail sheet takes the
 * screen. So under `lg` the embed renders this deliberate capture instead —
 * five rows from the same fixture family the live board mounts
 * (`lib/demo/demoData.ts`), no dates (a static still must not claim a
 * relative age), the product's own type system. Server-renderable by
 * construction: nothing here reads a clock, so there is no hydration risk and
 * no CLS.
 */
const ROWS: { company: string; role: string; stage: string; signal: string; tone?: "reject" }[] = [
  {
    company: "Kestrel Dynamics",
    role: "Software Engineer, Simulation",
    stage: "interviewing",
    signal: "Next step: online assessment (90 min)",
  },
  {
    company: "Northstar Systems",
    role: "ML Engineer",
    stage: "interviewing",
    signal: "Interview availability — technical round",
  },
  {
    company: "Copperline",
    role: "Backend Engineer, Payments",
    stage: "applied",
    signal: "We received your application",
  },
  {
    company: "Quarry Data",
    role: "Data Engineer",
    stage: "applied",
    signal: "Thanks for applying",
  },
  {
    company: "Atlas Freight",
    role: "Software Engineer II",
    stage: "rejected",
    signal: "Moving forward with other candidates",
    tone: "reject",
  },
];

export function BoardStill() {
  return (
    <figure className="overflow-hidden rounded-xl border border-line-soft bg-surface">
      <ul className="divide-y divide-line-soft">
        {ROWS.map((row) => (
          <li key={row.company + row.role} className="flex items-start justify-between gap-3 px-4 py-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-strong">{row.company}</p>
              <p className="truncate text-[0.8125rem] text-muted">{row.role}</p>
              <p className="mt-1 truncate text-xs text-dim">{row.signal}</p>
            </div>
            <span
              className={`label-caps mt-0.5 shrink-0 ${row.tone === "reject" ? "text-reject-ink" : ""}`}
            >
              {row.stage}
            </span>
          </li>
        ))}
      </ul>
      <figcaption className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-3">
        <span className="text-xs text-dim">{BOARD.still}</span>
        <a href="/demo" {...NEW_TAB} className="text-xs text-muted underline-offset-4 hover:text-strong hover:underline">
          {BOARD.open} →
        </a>
      </figcaption>
    </figure>
  );
}
