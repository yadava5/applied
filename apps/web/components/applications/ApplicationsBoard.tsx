import type { components } from "@/lib/api/schema";

type Application = components["schemas"]["Application"];

/**
 * Status-grouped pipeline board. Server-renderable and presentational —
 * the same silhouette as the public /demo board, driven by real rows.
 * `accepted` renders inside the offered column and `withdrawn` inside
 * rejected, each with a qualifier tag, so no application is invisible.
 */
const COLUMNS: { key: string; label: string; statuses: string[] }[] = [
  { key: "applied", label: "applied", statuses: ["applied"] },
  { key: "interviewing", label: "interviewing", statuses: ["interviewing"] },
  { key: "offered", label: "offered", statuses: ["offered", "accepted"] },
  { key: "rejected", label: "rejected", statuses: ["rejected", "withdrawn"] },
];

export function ApplicationsBoard({ applications }: { applications: Application[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {COLUMNS.map((col) => {
        const items = applications.filter((a) => col.statuses.includes(a.status));
        return (
          <div key={col.key} className="rounded-xl border border-line-soft bg-surface p-3">
            <div className="mb-2 flex items-baseline justify-between px-1">
              <span className="label-mono">{col.label}</span>
              <span className="tabular font-mono text-xs text-muted">{items.length}</span>
            </div>
            <ul className="space-y-2">
              {items.length === 0 && (
                <li className="rounded-lg border border-dashed border-line-soft p-3 text-center font-mono text-[11px] text-dim">
                  none yet
                </li>
              )}
              {items.map((a) => (
                <li
                  key={a.id}
                  className="rounded-lg border border-line-soft bg-surface-2 p-3 transition-colors hover:border-line-strong"
                >
                  <p className="flex items-center gap-2 text-sm font-medium text-strong">
                    {a.company}
                    {(a.status === "accepted" || a.status === "withdrawn") && (
                      <span className="rounded-full border border-line px-1.5 py-px font-mono text-[9px] uppercase tracking-wide text-muted">
                        {a.status}
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-muted">{a.position}</p>
                  {a.notes && (
                    <p className="mt-1.5 line-clamp-2 text-[11px] text-dim">{a.notes}</p>
                  )}
                  <p className="mt-2 font-mono text-[10px] text-dim">
                    filed {new Date(a.created_at).toLocaleDateString()}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
