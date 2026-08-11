"use client";

import { Search } from "lucide-react";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ApplicationCard } from "@/components/dashboard/ApplicationCard";
import { ApplicationDetail } from "@/components/dashboard/ApplicationDetail";
import { FiledStamp, SameCompanyChip } from "@/components/dashboard/CardMeta";
import { CompanyBand } from "@/components/dashboard/CompanyBand";
import { todayISO } from "@/lib/dashboard/age";
import { boardColumns, cardQualifier } from "@/lib/dashboard/board";
import { filedAt } from "@/lib/dashboard/dates";
import { type Application, STAGES, stageOf, type StageKey } from "@/lib/dashboard/summary";
import { liveBoardTransport, type BoardTransport } from "@/lib/dashboard/transport";

/**
 * Read-only card for the public demo + sample previews: no correction controls
 * (they would 401 without a session). Still honours the real received date and
 * the application-first anatomy (role under company) — and keeps the
 * same-company affordance, because filtering is not a mutation and the demo's
 * contract is to be the real thing.
 */
function StaticApplicationCard({
  app,
  columnLabel,
  today,
  sameCompanyCount = 0,
  onFilterCompany,
}: {
  app: Application;
  columnLabel: string;
  today: string;
  sameCompanyCount?: number;
  onFilterCompany?: (company: string) => void;
}) {
  const qualifier = cardQualifier(app.status, columnLabel);
  const stage = STAGES.find((s) => s.key === stageOf(app.status))!;
  const filed = filedAt(app);
  const role = app.position.trim();
  return (
    <div
      className="rounded-lg border border-line-soft bg-surface-2 p-3 transition-colors hover:border-line-strong"
      style={{ borderLeft: `2px solid color-mix(in oklab, ${stage.color} 55%, transparent)` }}
    >
      <p className="flex items-center gap-2 text-sm font-medium text-strong">
        <span className="truncate">{app.company}</span>
        {qualifier && (
          <span className="shrink-0 rounded-full border border-line px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-muted">
            {qualifier}
          </span>
        )}
      </p>
      {/* Wraps, never ellipsizes — the role's tail is the discriminator (see
          ApplicationCard). */}
      {role ? (
        <p title={role} className="line-clamp-2 break-words text-[13px] leading-snug text-foreground">
          {role}
        </p>
      ) : null}
      {sameCompanyCount > 0 && onFilterCompany ? (
        <SameCompanyChip company={app.company} count={sameCompanyCount} onFilter={onFilterCompany} />
      ) : null}
      {app.notes && <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-dim">{app.notes}</p>}
      <p className="mt-2">
        <FiledStamp filed={filed} status={app.status} today={today} />
      </p>
    </div>
  );
}

/**
 * Status-grouped pipeline board, designed for 200 applications rather than 15.
 *
 * A card is an APPLICATION, not a company: one employer can hold several cards
 * (four Amazon roles in one evening is the proven case), they can sit in
 * different columns simultaneously, and the role line is the discriminator.
 * Company stays an attribute — the company-level affordances are the "+N at
 * Amazon" chip on a card and the set view it opens: the board filters to the
 * employer and a `CompanyBand` names the set (count, stage spread, filing
 * span). While that filter is active the chip is suppressed — "3 more at
 * Amazon" inside Amazon's own set view was a bug, not information.
 *
 * Motion (the `motion` library): every card cell is a `motion.li` with a
 * shared `layoutId`, so search/filter changes glide survivors into place, a
 * card dropped (or selected) into another column visibly travels there, and
 * clearing a filter gathers the board back. Entrances only run for cards that
 * appear AFTER hydration (`entering` below) — server HTML is never hidden
 * behind an animation — exits are instant (a filter must feel like a filter,
 * not a curtain call), and `useReducedMotion` collapses the whole layer to
 * static rendering.
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

/**
 * One board cell: the layout-animated `li` around a card. `layoutId` is what
 * lets a card travel between columns as one continuous element; `entering`
 * gates the fade-in to post-hydration appearances only.
 */
function BoardCell({
  id,
  entering,
  children,
}: {
  id: number;
  entering: boolean;
  children: ReactNode;
}) {
  const reduceMotion = useReducedMotion();
  // ONE element type in every case, and the same one the server rendered.
  //
  // Returning a plain `<li>` under reduced motion looked equivalent and was not:
  // `useReducedMotion` cannot read a media query during SSR, so the server always
  // took the `motion.li` branch while a reduced-motion client took the other one.
  // The differing tree shape shifts every descendant `useId`, and production
  // React does not repair a server-rendered `id` attribute — so
  // `RowActionsMenu`'s `aria-labelledby` pointed at an id that no longer existed
  // on every card, for exactly the people reduced motion exists to serve.
  //
  // Reduced motion is now expressed by neutralising the animation PROPS, which
  // changes nothing about the tree. `layout={false}` disables the shared-layout
  // glide; the zero duration makes the remaining opacity settle instant.
  return (
    <motion.li
      layout={!reduceMotion}
      layoutId={`app-${id}`}
      initial={entering && !reduceMotion ? { opacity: 0, y: 6 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={
        reduceMotion ? { duration: 0 } : { duration: 0.22, ease: [0.22, 1, 0.36, 1] }
      }
    >
      {children}
    </motion.li>
  );
}

export function PipelineBoard({
  applications,
  interactive = true,
  transport = liveBoardTransport,
}: {
  applications: Application[];
  interactive?: boolean;
  /** How mutations reach data — the live proxy by default, fixtures on /demo. */
  transport?: BoardTransport;
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
  /** False for the server-rendered pass — entrance animations start only after
   *  hydration, so no card is ever server-rendered invisible. Deferred off the
   *  effect body (house rule — no synchronous setState in an effect). */
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    const id = window.setTimeout(() => setHydrated(true), 0);
    return () => window.clearTimeout(id);
  }, []);

  /** One clock read per render — every card's age tag derives from it. */
  const today = todayISO();

  // Server data caught up with an optimistic move → drop the overlay entry and
  // let the row's own status speak. Render-adjustment (guarded, so it settles
  // in one extra render), the same pattern ApplicationCard uses for its own
  // optimistic stage.
  const settled = applications.filter(
    (app) => pendingMoves[app.id] !== undefined && app.status === pendingMoves[app.id],
  );
  if (settled.length > 0) {
    const next = { ...pendingMoves };
    for (const app of settled) delete next[app.id];
    setPendingMoves(next);
  }

  /** How many OTHER cards share each company — drives the "+N at" chip. */
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

  /** The active employer's FULL set — what the band describes. */
  const companySet =
    companyFilter !== null
      ? applications.filter((app) => app.company === companyFilter)
      : null;

  /**
   * The chip is suppressed for the company the board is already filtered to —
   * "N more at Amazon" while looking at exactly Amazon's set was the bug this
   * argument exists to keep fixed.
   */
  const sameCompanyCount = (app: Application) =>
    companyFilter === app.company ? 0 : (companyCounts.get(app.company) ?? 1) - 1;

  async function moveTo(appId: number, stageKey: StageKey) {
    const app = applications.find((a) => a.id === appId);
    if (!app || stageOf(shownStatus(app)) === stageKey) return;
    // The stage keys are themselves canonical statuses the PATCH accepts; a
    // drop into `closed` files as `rejected`, and the select is where the
    // finer words (withdrawn, ghosted) live.
    const target: string = stageKey;
    setMoveError(null);
    setPendingMoves((m) => ({ ...m, [appId]: target }));
    const result = await transport.changeStatus(appId, target);
    if (!result.ok) {
      setPendingMoves((m) => {
        const next = { ...m };
        delete next[appId];
        return next;
      });
      setMoveError(
        `Couldn't move ${app.company} to “${target}” — it is still “${app.status}”.${
          result.detail ? ` ${result.detail}` : ""
        }`,
      );
      return;
    }
    router.refresh();
  }

  const showSearch = applications.length > SEARCH_AFTER;

  // --- Column widths: space follows content --------------------------------
  // A real search's board is one heavy column and three near-empty ones, and
  // an even four-way split hands three quarters of the width to "none yet"
  // while the column holding every card is the narrowest it can be — which is
  // how four real Amazon roles ended up ellipsized into identical text.
  // Populated columns take 3fr, empty ones compress to a readable floor
  // (desktop only — `.board-grid` in globals.css; narrower widths keep the
  // stacked/two-up flow). The weight is binary (has cards / hasn't) and reads
  // the UNFILTERED counts, so typing a search or dragging between two
  // populated columns never reflows the widths; only genuinely emptying or
  // populating a column does.
  const boardCols = boardColumns(STAGES)
    .map((column) =>
      applications.some((app) => stageOf(shownStatus(app)) === column.key)
        ? "minmax(0, 3fr)"
        : "minmax(8rem, 1fr)",
    )
    .join(" ");

  return (
    <div className="space-y-3">
      {/* --- Board filters ------------------------------------------------- */}
      {showSearch || filterActive ? (
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
          {filterActive ? (
            <span className="tabular text-xs text-dim" role="status">
              {filtered.length} of {applications.length} shown
            </span>
          ) : null}
        </div>
      ) : null}

      {/* --- The employer's set, named ------------------------------------- */}
      {companyFilter !== null && companySet !== null ? (
        <CompanyBand
          company={companyFilter}
          apps={companySet}
          statusOf={shownStatus}
          onClear={() => setCompanyFilter(null)}
        />
      ) : null}

      {moveError ? (
        <p role="alert" className="text-xs text-reject">
          {moveError}
        </p>
      ) : null}

      {/* --- Columns -------------------------------------------------------- */}
      <LayoutGroup>
        <div
          className="board-grid grid items-start gap-3 sm:grid-cols-2"
          style={{ ["--board-cols" as string]: boardCols }}
        >
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
                  <span className="label-caps inline-flex items-center gap-1.5 text-muted">
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
                    <li className="rounded-lg border border-dashed border-line-soft p-3 text-center text-xs text-dim">
                      {filterActive ? "none match" : "none yet"}
                    </li>
                  ) : (
                    visible.map((app) => (
                      <BoardCell key={app.id} id={app.id} entering={hydrated}>
                        {interactive ? (
                          <ApplicationCard
                            app={app}
                            columnLabel={column.label}
                            today={today}
                            transport={transport}
                            onOpenDetail={setDetailApp}
                            sameCompanyCount={sameCompanyCount(app)}
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
                          <StaticApplicationCard
                            app={app}
                            columnLabel={column.label}
                            today={today}
                            sameCompanyCount={sameCompanyCount(app)}
                            onFilterCompany={setCompanyFilter}
                          />
                        )}
                      </BoardCell>
                    ))
                  )}
                </ul>
                {hidden > 0 || isExpanded ? (
                  <button
                    type="button"
                    onClick={() =>
                      setExpanded((e) => ({ ...e, [column.key]: !isExpanded }))
                    }
                    className="mt-2 rounded-lg border border-dashed border-line px-2 py-1.5 text-xs font-medium text-muted transition-colors hover:border-line-strong hover:text-strong"
                  >
                    {isExpanded ? "show fewer" : `show all ${items.length}`}
                  </button>
                ) : null}
              </section>
            );
          })}
        </div>
      </LayoutGroup>

      {interactive ? (
        <ApplicationDetail app={detailApp} onClose={() => setDetailApp(null)} transport={transport} />
      ) : null}
    </div>
  );
}
