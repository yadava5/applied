"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApplicationCard } from "@/components/dashboard/ApplicationCard";
import { ApplicationDetail } from "@/components/dashboard/ApplicationDetail";
import { boardColumns, cardQualifier } from "@/lib/dashboard/board";
import { filedAt, shortDate } from "@/lib/dashboard/dates";
import { statusChangeRequest } from "@/lib/dashboard/rowActions";
import { type Application, STAGES, stageOf, type StageKey } from "@/lib/dashboard/summary";

/**
 * Read-only card for the public demo + sample previews: no correction controls
 * (they would 401 without a session). Still honours the real received date and
 * the application-first anatomy (role under company).
 */
function StaticApplicationCard({ app, columnLabel }: { app: Application; columnLabel: string }) {
  const qualifier = cardQualifier(app.status, columnLabel);
  const stage = STAGES.find((s) => s.key === stageOf(app.status))!;
  const filed = filedAt(app);
  const role = app.position.trim();
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
      {role ? <p className="truncate text-xs text-foreground">{role}</p> : null}
      {app.notes && <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-dim">{app.notes}</p>}
      <p className="mt-2 font-mono text-[10px] text-dim">filed {shortDate(filed)}</p>
    </li>
  );
}

/**
 * Status-grouped pipeline board, designed for 200 applications rather than 15.
 *
 * A card is an APPLICATION, not a company: one employer can hold several cards
 * (four Amazon roles in one evening is the proven case), they can sit in
 * different columns simultaneously, and the role line is the discriminator.
 * Company stays an attribute — the only company-level affordance is the light
 * "N more at Amazon" link on a card, which filters the board.
 *
 * Density rules, deliberately without a nested scroller: the page is the one
 * scroll context. A tall column shows its first {@link COLLAPSED_COUNT} cards
 * and a "show all N" expander that grows the page — no inner scrollbar
 * fighting the page's, no card ever clipped behind a fade, and a specific card
 * can actually be scrolled to. Search (company or role) and the company filter
 * cut 200 rows down to the ones being asked about.
 *
 * Stage changes have three working paths: drag a card to a column (pointer),
 * the per-card select (keyboard + the accessible path), and the same select in
 * the detail sheet. Drops are optimistic — the card moves immediately, a
 * failure rolls it back visibly and says why.
 *
 * `accepted` folds into the offered column, and the resolved column carries
 * `rejected`/`withdrawn`/`ghosted`, so it is headed `closed` and every card in
 * it states its own status (see `lib/dashboard/board.ts`).
 *
 * The public demo and sample previews pass `interactive={false}` for read-only
 * cards whose mutations never fire — search and filters still work there,
 * because `/demo` renders this same component on fixtures.
 */
const COLLAPSED_COUNT = 8;

/** Below this many rows, search would be chrome without a job. */
const SEARCH_AFTER = 5;

export function PipelineBoard({
  applications,
  interactive = true,
}: {
  applications: Application[];
  interactive?: boolean;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [companyFilter, setCompanyFilter] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Partial<Record<StageKey, boolean>>>({});
  const [detailApp, setDetailApp] = useState<Application | null>(null);
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dropStage, setDropStage] = useState<StageKey | null>(null);
  /** Optimistic overlay: id → the status a drop just chose, until the server confirms. */
  const [pendingMoves, setPendingMoves] = useState<Record<number, string>>({});
  const [moveError, setMoveError] = useState<string | null>(null);

  // Server data caught up with an optimistic move → drop the overlay entry and
  // let the row's own status speak.
  useEffect(() => {
    setPendingMoves((moves) => {
      let changed = false;
      const next = { ...moves };
      for (const app of applications) {
        if (next[app.id] !== undefined && app.status === next[app.id]) {
          delete next[app.id];
          changed = true;
        }
      }
      return changed ? next : moves;
    });
  }, [applications]);

  /** How many OTHER cards share each company — drives the "N more at" link. */
  const companyCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const app of applications) {
      counts.set(app.company, (counts.get(app.company) ?? 0) + 1);
    }
    return counts;
  }, [applications]);

  const shownStatus = (app: Application) => pendingMoves[app.id] ?? app.status;

  const q = query.trim().toLowerCase();
  const filterActive = q !== "" || companyFilter !== null;
  const filtered = applications.filter((app) => {
    if (companyFilter !== null && app.company !== companyFilter) return false;
    if (q !== "" && !`${app.company} ${app.position}`.toLowerCase().includes(q)) return false;
    return true;
  });

  async function moveTo(appId: number, stageKey: StageKey) {
    const app = applications.find((a) => a.id === appId);
    if (!app || stageOf(shownStatus(app)) === stageKey) return;
    // The stage keys are themselves canonical statuses the PATCH accepts; a
    // drop into `closed` files as `rejected`, and the select is where the
    // finer words (withdrawn, ghosted) live.
    const target: string = stageKey;
    setMoveError(null);
    setPendingMoves((m) => ({ ...m, [appId]: target }));
    const req = statusChangeRequest(appId, target);
    try {
      const res = await fetch(req.path, {
        method: req.method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req.body),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
        setPendingMoves((m) => {
          const next = { ...m };
          delete next[appId];
          return next;
        });
        setMoveError(
          `Couldn't move ${app.company} to “${target}” — it is still “${app.status}”.${
            typeof body.detail === "string" ? ` ${body.detail}` : ""
          }`,
        );
        return;
      }
      router.refresh();
    } catch {
      setPendingMoves((m) => {
        const next = { ...m };
        delete next[appId];
        return next;
      });
      setMoveError(`Couldn't move ${app.company} — it is still “${app.status}”.`);
    }
  }

  const showSearch = applications.length > SEARCH_AFTER;

  return (
    <div className="space-y-3">
      {/* --- Board filters ------------------------------------------------- */}
      {showSearch || companyFilter !== null ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {showSearch ? (
            <div className="relative flex-1 basis-56">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-dim"
                aria-hidden
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="search company or role…"
                aria-label="Search the board by company or role"
                className="w-full rounded-lg border border-line bg-surface py-1.5 pl-8 pr-3 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong"
              />
            </div>
          ) : null}
          {companyFilter !== null ? (
            <button
              type="button"
              onClick={() => setCompanyFilter(null)}
              aria-label={`Stop filtering by ${companyFilter}`}
              className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-3 py-1 font-mono text-[11px] text-strong transition-colors hover:border-line"
            >
              {companyFilter}
              <span aria-hidden>×</span>
            </button>
          ) : null}
          {filterActive ? (
            <span className="font-mono text-[11px] text-dim" role="status">
              {filtered.length} of {applications.length} shown
            </span>
          ) : null}
        </div>
      ) : null}

      {moveError ? (
        <p role="alert" className="font-mono text-[11px] text-reject">
          {moveError}
        </p>
      ) : null}

      {/* --- Columns -------------------------------------------------------- */}
      <div className="grid items-start gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {boardColumns(STAGES).map((column) => {
          const items = filtered.filter((a) => stageOf(shownStatus(a)) === column.key);
          const isExpanded = expanded[column.key] === true;
          const visible = isExpanded ? items : items.slice(0, COLLAPSED_COUNT);
          const hidden = items.length - visible.length;
          return (
            <section
              key={column.key}
              aria-label={`${column.label} — ${items.length}`}
              data-drop={dropStage === column.key || undefined}
              onDragOver={
                interactive && draggingId !== null
                  ? (event) => {
                      event.preventDefault();
                      event.dataTransfer.dropEffect = "move";
                      setDropStage(column.key);
                    }
                  : undefined
              }
              onDrop={
                interactive
                  ? (event) => {
                      event.preventDefault();
                      const id = Number(event.dataTransfer.getData("text/plain"));
                      setDropStage(null);
                      setDraggingId(null);
                      if (Number.isInteger(id) && id > 0) void moveTo(id, column.key);
                    }
                  : undefined
              }
              className="board-col flex flex-col rounded-xl border border-line-soft bg-surface p-3 transition-colors"
            >
              <div className="mb-2 flex items-baseline justify-between px-1">
                <span className="label-mono inline-flex items-center gap-1.5">
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ background: column.color }}
                    aria-hidden="true"
                  />
                  {column.label}
                </span>
                <span className="tabular font-mono text-xs text-muted">{items.length}</span>
              </div>
              <ul className="space-y-2">
                {items.length === 0 ? (
                  <li className="rounded-lg border border-dashed border-line-soft p-3 text-center font-mono text-[11px] text-dim">
                    {filterActive ? "none match" : "none yet"}
                  </li>
                ) : (
                  visible.map((app) =>
                    interactive ? (
                      <ApplicationCard
                        key={app.id}
                        app={app}
                        columnLabel={column.label}
                        onOpenDetail={setDetailApp}
                        sameCompanyCount={(companyCounts.get(app.company) ?? 1) - 1}
                        onFilterCompany={setCompanyFilter}
                        dragging={draggingId === app.id}
                        onDragStart={(event) => {
                          event.dataTransfer.setData("text/plain", String(app.id));
                          event.dataTransfer.effectAllowed = "move";
                          setDraggingId(app.id);
                        }}
                        onDragEnd={() => {
                          setDraggingId(null);
                          setDropStage(null);
                        }}
                      />
                    ) : (
                      <StaticApplicationCard key={app.id} app={app} columnLabel={column.label} />
                    ),
                  )
                )}
              </ul>
              {hidden > 0 || isExpanded ? (
                <button
                  type="button"
                  onClick={() =>
                    setExpanded((e) => ({ ...e, [column.key]: !isExpanded }))
                  }
                  className="mt-2 rounded-lg border border-dashed border-line px-2 py-1.5 font-mono text-[11px] text-muted transition-colors hover:border-line-strong hover:text-strong"
                >
                  {isExpanded ? "show fewer" : `show all ${items.length}`}
                </button>
              ) : null}
            </section>
          );
        })}
      </div>

      {interactive ? <ApplicationDetail app={detailApp} onClose={() => setDetailApp(null)} /> : null}
    </div>
  );
}
