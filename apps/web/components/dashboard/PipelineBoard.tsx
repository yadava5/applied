"use client";

import { Search } from "lucide-react";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { ApplicationRow, NO_ROLE_LABEL } from "@/components/dashboard/ApplicationRow";
import { ApplicationDetail } from "@/components/dashboard/ApplicationDetail";
import { DeadlineTag, FiledStamp, SameCompanyChip } from "@/components/dashboard/CardMeta";
import { CompanyBand } from "@/components/dashboard/CompanyBand";
import { EmployerSetRow } from "@/components/dashboard/EmployerSetRow";
import { PipelinePulse } from "@/components/dashboard/PipelinePulse";
import { useShellSlots } from "@/components/shell/shell-slots";
import { useLocalToday } from "@/lib/dashboard/useLocalToday";
import { boardColumns, cardQualifier, type BoardColumn } from "@/lib/dashboard/board";
import { filedAt } from "@/lib/dashboard/dates";
import { elsewhereLabel, groupByEmployer } from "@/lib/dashboard/employerGroups";
import { cn } from "@/lib/utils";
import { type Application, STAGES, stageOf, type StageKey } from "@/lib/dashboard/summary";
import { liveBoardTransport, type BoardTransport } from "@/lib/dashboard/transport";

/**
 * The pipeline worklist — the answer to "is a four-column kanban the right
 * primary view?", and the answer is no.
 *
 * A kanban's geometry encodes stage, and it earns that only when items are
 * distributed across stages. A personal job search is not distributed: it is
 * one heavy resting state (applied, waiting) with a thin stream of
 * transitions — the measured production account is 29 live rows, ALL of them
 * in one column. Four columns rendered that reality as one starved strip and
 * three tall boxes asserting emptiness. So stage is now a LENS, not geometry:
 *
 *   - the **stage lens** draws the pipeline as an instrument — every stage,
 *     its count, and a proportional meter. It is the filter (press a stage
 *     to see only it), the drop target (drag a row onto a stage to move it),
 *     and the one place emptiness is stated — as a zero and an empty meter,
 *     which costs a line, not a quarter of the screen. At 29-0-0-0 it reads
 *     as a young pipeline; at a healthy spread it reads as a funnel. WHERE
 *     it draws depends on what is around the board: inside the app shell the
 *     interactive board portals it (plus search) into the sidebar's middle
 *     run — filters are route-local navigation, the rail's middle was a
 *     measured void, and the worklist gains the whole column the in-board
 *     spine used to hold. Outside the shell it stays an in-board spine at
 *     `lg`+. Below the vertical lens's breakpoint (`md` in the shell, `lg`
 *     outside) it compresses into a chip strip.
 *   - the **pulse band** (`pulse` prop): the four derived signals
 *     (`PipelinePulse`) as one full-width band above the worklist —
 *     dashboard content, in the dashboard's content area. This is the
 *     pre-#136 home restored at band-density (~56px, not the old ~200px
 *     strip); the spine and the shell rail are both measured, rejected homes
 *     for it (see PipelinePulse's header).
 *   - the **worklist** renders every application as one full-width
 *     row with a fixed skeleton, grouped by stage in flow order. Rows are
 *     even by construction: company and the role slot share one line, and a
 *     missing role prints an honest placeholder instead of a shorter card
 *     (8 of the 29 real rows have no role — that raggedness was half the
 *     complaint; column starvation was the other half, and rows have no
 *     columns to starve).
 *
 * Two geometries, one component:
 *   - `variant="locked"` (the signed-in dashboard): the board fills the
 *     shell's viewport-locked pane; the LIST is the only thing that scrolls,
 *     with sticky group headers. Below `lg` the lock releases and the page
 *     flows — pinning a phone's only content pane behind a nested scroller
 *     helps nobody.
 *   - `variant="flow"` (the /demo twin, the empty-state preview): natural
 *     height, no nested scroller — the page is the scroll context, exactly
 *     as before.
 *
 * A row is an APPLICATION, not a company: one employer can hold several rows
 * (four Amazon roles in one evening is the proven case), and the role is the
 * discriminator. But four rows all HEADED "Amazon" read as duplication, so the
 * unfiltered list folds same-employer rows *within a stage group* into one
 * employer card that opens inline (`EmployerSetRow`, membership from
 * `lib/dashboard/employerGroups.ts`). Display only — each member keeps its own
 * id, status, mail and controls; the stage headings and the spine keep
 * counting applications, never cards; and the grouping is per stage on
 * purpose, so an employer split across stages appears once under each — a
 * cross-stage summary row would have to pick one stage to live in, which is
 * the furthest-stage-wins display the old merge bug drew.
 *
 * The remaining company-level affordance is the cross-stage chip
 * ("+1 in interviewing") on a set header or a singleton whose employer holds
 * rows in other stages. It opens the set VIEW: the list filters to the
 * employer — dispersed back into flat rows, one per application, each under
 * its own stage heading — and a `CompanyBand` states that filter: just the
 * name and a clear, since the cards themselves already say how many there are
 * and what stage each one is in. While that filter is active the chip is
 * suppressed — "+3 at Amazon" inside Amazon's own set view was a bug, not
 * information. A search also disperses the sets: a match hidden inside a
 * collapsed card would make search worse than no grouping at all.
 *
 * Motion (the `motion` library): every row cell is a `motion.li` with a
 * shared `layoutId`, so search/filter changes glide survivors into place, a
 * row dropped (or selected) into another stage visibly travels there, and
 * clearing a filter gathers the list back. Entrances only run for rows that
 * appear AFTER hydration (`entering` below) — server HTML is never hidden
 * behind an animation — exits are instant (a filter must feel like a filter,
 * not a curtain call), and `useReducedMotion` collapses the whole layer to
 * static rendering.
 *
 * Stage changes have three working paths: drag a row onto a stage (spine or
 * group heading — pointer), the per-row select (keyboard + the accessible
 * path), and the same select in the detail sheet. Drops are optimistic — the
 * row moves immediately, a failure rolls it back visibly and says why.
 *
 * `accepted` folds into the offered group, and the resolved group carries
 * `rejected`/`withdrawn`/`ghosted`, so it is headed `closed` and every row in
 * it states its own status (see `lib/dashboard/board.ts`).
 *
 * `interactive={false}` is the INERT board: the sample preview inside the
 * dashboard's empty state, which sits under `pointer-events-none`. It renders
 * read-only rows (mutations there would 401 without a session) and no search
 * field — a search input a user cannot focus is chrome that invites typing and
 * eats nothing. `/demo` is NOT that board: it renders this component fully
 * interactive over fixtures, and only the transport is simulated, which is
 * what gives the session-gated surfaces their executing e2e coverage.
 *
 * Scope honesty: the signed-in board is ONE bounded page of a possibly larger
 * account, so it takes the account's true `total` and says which slice it is
 * showing when the two differ. The SPINE is exempt because it does not derive
 * from the rows at all — it reads the account's own per-stage counts off the
 * summary endpoint (`stageTotals`), so its numbers are the account's however
 * few rows loaded and however the list chooses to group them. Everything that
 * genuinely is derived from the loaded rows (the "+N at" chip, the company
 * band's `partial` caveat, the "N of M shown" line) says so rather than
 * passing itself off as the whole.
 */

/** Below this many rows, search would be chrome without a job. */
const SEARCH_AFTER = 5;

/** The spine's filter vocabulary: every stage, or all of them. */
type StageFilter = StageKey | "all";

/**
 * Read-only row for the public demo previews + sample boards: no correction
 * controls (they would 401 without a session). Still honours the real received
 * date and the application-first anatomy (company anchors, role discriminates,
 * an absent role prints the honest placeholder) — and keeps the same-company
 * affordance, because filtering is not a mutation and the demo's contract is
 * to be the real thing.
 */
function StaticApplicationRow({
  app,
  columnLabel,
  today,
  inSet = false,
  sameCompanyCount = 0,
  sameCompanyLabel,
  onFilterCompany,
}: {
  app: Application;
  columnLabel: string;
  today: string;
  inSet?: boolean;
  sameCompanyCount?: number;
  sameCompanyLabel?: string | null;
  onFilterCompany?: (company: string) => void;
}) {
  const qualifier = cardQualifier(app.status, columnLabel);
  const stage = STAGES.find((s) => s.key === stageOf(app.status))!;
  const filed = filedAt(app);
  const role = app.position.trim();
  const showChip = sameCompanyCount > 0 && onFilterCompany !== undefined;
  return (
    // Same responsive skeleton as the interactive row: an explicit stack below
    // `sm` (stamp on the company line, meta left-anchored), one line above it.
    <div
      className="flex flex-col gap-y-1.5 rounded-lg border border-line-soft bg-surface-2 py-2 pl-3 pr-2 transition-colors hover:border-line-strong sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-3"
      style={{
        borderLeft: `2px solid color-mix(in oklab, ${stage.color} 55%, transparent)`,
      }}
    >
      <div className="flex min-w-0 flex-col gap-y-0.5 sm:flex-1 sm:basis-56 sm:flex-row sm:items-baseline sm:gap-x-2.5">
        {inSet ? (
          // Set member: role leads, employer stays on the header (see
          // ApplicationRow — same rule, same reason).
          <span className="flex min-w-0 flex-1 items-baseline gap-2">
            {role ? (
              <span
                title={role}
                className="line-clamp-2 min-w-0 break-words text-sm leading-snug text-foreground"
              >
                {role}
              </span>
            ) : (
              <span className="text-sm leading-snug text-dim">{NO_ROLE_LABEL}</span>
            )}
            {qualifier && (
              <span className="shrink-0 rounded-full border border-line px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-muted">
                {qualifier}
              </span>
            )}
            <span className="ml-auto shrink-0 sm:hidden">
              <FiledStamp filed={filed} status={app.status} today={today} />
            </span>
          </span>
        ) : (
          <>
            <span className="flex min-w-0 items-baseline gap-2 text-sm font-medium text-strong sm:max-w-[16rem] sm:shrink-0">
              <span className="min-w-0 truncate">{app.company}</span>
              {qualifier && (
                <span className="shrink-0 rounded-full border border-line px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-muted">
                  {qualifier}
                </span>
              )}
              <span className="ml-auto shrink-0 font-normal sm:hidden">
                <FiledStamp filed={filed} status={app.status} today={today} />
              </span>
            </span>
            {role ? (
              <span
                title={role}
                className="line-clamp-2 min-w-0 break-words text-[13px] leading-snug text-foreground"
              >
                {role}
              </span>
            ) : (
              <span className="text-[13px] leading-snug text-dim">{NO_ROLE_LABEL}</span>
            )}
          </>
        )}
      </div>
      {/* This row has no controls, so at phone width the meta line only exists
          when it has something to say — an empty flex child would still spend
          the stack's gap. */}
      <div
        className={cn(
          showChip || app.due_at != null ? "flex" : "hidden sm:flex",
          "flex-wrap items-center gap-x-2 gap-y-1 sm:ml-auto sm:max-w-full sm:justify-end",
        )}
      >
        {showChip ? (
          <SameCompanyChip
            company={app.company}
            count={sameCompanyCount}
            label={sameCompanyLabel ?? undefined}
            onFilter={onFilterCompany}
          />
        ) : null}
        {/* Same rule as the interactive row: nothing unless the row has a due_at. */}
        <DeadlineTag dueAt={app.due_at} today={today} />
        <span className="hidden sm:inline">
          <FiledStamp filed={filed} status={app.status} today={today} />
        </span>
      </div>
    </div>
  );
}

/**
 * One list cell: the layout-animated `li` around a row. `layoutId` is what
 * lets a row travel between stage groups as one continuous element —
 * `app-{id}` for an application (stable across grouping, so a member leaving
 * a set glides out of it as itself), `set-{stage}-{company}` for an employer
 * set's own cell. `entering` gates the fade-in to post-hydration appearances
 * only.
 */
function BoardCell({
  layoutKey,
  entering,
  children,
}: {
  layoutKey: string;
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
  // on every row, for exactly the people reduced motion exists to serve.
  //
  // Reduced motion is now expressed by neutralising the animation PROPS, which
  // changes nothing about the tree. `layout={false}` disables the shared-layout
  // glide; the zero duration makes the remaining opacity settle instant.
  return (
    <motion.li
      layout={!reduceMotion}
      layoutId={layoutKey}
      initial={entering && !reduceMotion ? { opacity: 0, y: 6 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={reduceMotion ? { duration: 0 } : { duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.li>
  );
}

/**
 * What the caller knows about the ACCOUNT, as opposed to the page of rows it
 * handed over. Either it knows both numbers or it knows neither — a caller
 * that can say "250 filed" but not how those 250 sit across the stages would
 * leave the spine quietly describing the loaded slice while the subtitle
 * describes the account, which is the contradiction this pairing exists to
 * make unrepresentable. Callers whose rows ARE the account (the /demo twin,
 * the inert sample preview) pass neither and the board counts what it has.
 */
type BoardScope =
  | {
      /** The account's true row count — the sum of `stageTotals`, from
       *  `GET /applications/summary`. */
      total: number;
      /** The account's true per-stage counts, computed by a `GROUP BY status`
       *  in the database (dismissed rows excluded, as they are off the board). */
      stageTotals: Record<StageKey, number>;
    }
  | { total?: undefined; stageTotals?: undefined };

export function PipelineBoard({
  applications,
  total,
  stageTotals,
  interactive = true,
  variant = "flow",
  transport = liveBoardTransport,
  pulse,
  beforeList,
  afterList,
}: {
  applications: Application[];
  interactive?: boolean;
  /** `locked` fills the shell's viewport pane and scrolls only the list;
   *  `flow` renders natural height for pages that scroll themselves. */
  variant?: "locked" | "flow";
  /** How mutations reach data — the live proxy by default, fixtures on /demo. */
  transport?: BoardTransport;
  /** Mount the pulse's derived signals as a full-width band above the
   *  worklist (`lg`-up, one instance — see the band note above). Omitted
   *  by the inert empty-state preview on purpose: four derived signals over
   *  sample rows would be onboarding noise. `needsReview` is the account's
   *  held-verdict count — the auto-filed signal's deep link. */
  pulse?: { needsReview: number };
  /** Rendered inside the list pane, above the rows (e.g. the review queue
   *  when alerts interrupt) — it scrolls with the list, so an interrupt can
   *  never starve the worklist of its viewport. */
  beforeList?: ReactNode;
  /** Rendered inside the list pane, below the rows (the quiet placement). */
  afterList?: ReactNode;
} & BoardScope) {
  const router = useRouter();
  /**
   * Where the stage lens lives. Inside the app shell the interactive board
   * portals it (with search) into the sidebar's middle run — filters are
   * route-local navigation, and the rail's void was the owner's complaint —
   * while the state stays HERE, in the one component that owns the list they
   * filter. `inShell` is a render-time constant, so the markup choice is
   * hydration-safe; `rail` is the live slot element, null until the sidebar
   * mounts (the portal appearing late cannot move the page — the rail is a
   * fixed column). The inert empty-state preview keeps its own in-board
   * spine: sample filters do not belong in the app's navigation. Outside the
   * shell (/demo's flow twin) nothing changes: spine at `lg`+, chips below.
   */
  const { inShell, rail } = useShellSlots();
  const railStages = inShell && interactive;
  const [query, setQuery] = useState("");
  const [companyFilter, setCompanyFilter] = useState<string | null>(null);
  const [stageFilter, setStageFilter] = useState<StageFilter>("all");
  const [detailApp, setDetailApp] = useState<Application | null>(null);
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dropStage, setDropStage] = useState<StageKey | null>(null);
  /** Optimistic overlay: id → the status a drop just chose, until the server confirms. */
  const [pendingMoves, setPendingMoves] = useState<Record<number, string>>({});
  const [moveError, setMoveError] = useState<string | null>(null);
  /** False for the server-rendered pass — entrance animations start only after
   *  hydration, so no row is ever server-rendered invisible. Deferred off the
   *  effect body (house rule — no synchronous setState in an effect). */
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    const id = window.setTimeout(() => setHydrated(true), 0);
    return () => window.clearTimeout(id);
  }, []);

  /** One clock read per render — every row's age tag and deadline state
   *  derives from it. UTC for the server pass, the reader's own day once
   *  mounted (see `useLocalToday`). */
  const today = useLocalToday();

  // Server data caught up with an optimistic move → drop the overlay entry and
  // let the row's own status speak. Render-adjustment (guarded, so it settles
  // in one extra render), the same pattern ApplicationRow uses for its own
  // optimistic stage.
  const settled = applications.filter(
    (app) => pendingMoves[app.id] !== undefined && app.status === pendingMoves[app.id],
  );
  if (settled.length > 0) {
    const next = { ...pendingMoves };
    for (const app of settled) delete next[app.id];
    setPendingMoves(next);
  }

  /**
   * True when these rows are one page of a bigger account. Everything the
   * board derives — the spine counts, the "+N at" chip, the company band —
   * then describes the LOADED rows only, and says so rather than passing
   * itself off as the account.
   */
  const truncated = total !== undefined && applications.length < total;
  const scopeNote = truncated ? `newest ${applications.length} of ${total}` : null;

  /** How many OTHER rows share each company ON THIS BOARD — drives the "+N
   *  at" chip. Under truncation an employer can hold rows that never loaded,
   *  so the chip is a floor, not a census; the band states the same scope. */
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

  /**
   * Employer grouping is the resting view only. A search or the company
   * filter disperses the sets back into flat rows: a match hidden inside a
   * collapsed card would defeat the search, and the set VIEW's whole point is
   * one row per application under its own stage heading.
   */
  const grouping = !filterActive;

  /** Which employer sets are open, keyed `${stage}:${company}`. Session state
   *  — a set the user opened stays open across filters and refreshes of this
   *  mount, and there is nothing worth persisting beyond it. */
  const [openSets, setOpenSets] = useState<Record<string, boolean>>({});
  const toggleSet = (key: string) => setOpenSets((s) => ({ ...s, [key]: !s[key] }));

  /**
   * The chip is suppressed for the company the board is already filtered to —
   * "N more at Amazon" while looking at exactly Amazon's set was the bug this
   * argument exists to keep fixed.
   */
  const sameCompanyCount = (app: Application) =>
    companyFilter === app.company ? 0 : (companyCounts.get(app.company) ?? 1) - 1;

  /** Each employer's loaded rows by stage — the SHOWN stage, so an optimistic
   *  move updates the cross-stage chips in the same frame as the row itself.
   *  Not memoized: it depends on `pendingMoves`, which changes exactly when a
   *  re-render happens anyway, and the board holds one bounded page. */
  const companyStages = new Map<string, Record<StageKey, number>>();
  for (const app of applications) {
    let counts = companyStages.get(app.company);
    if (!counts) {
      counts = {
        applied: 0,
        assessment: 0,
        interviewing: 0,
        offered: 0,
        rejected: 0,
      };
      companyStages.set(app.company, counts);
    }
    counts[stageOf(shownStatus(app))] += 1;
  }

  /**
   * The cross-stage affordance for a row or set in `here`: how many of the
   * employer's OTHER applications sit outside this stage, and the chip text
   * naming where ("+1 in interviewing"). Null when the employer is wholly
   * here — an employer set carrying "+0 elsewhere" would be noise.
   */
  const crossStageChip = (
    company: string,
    here: StageKey,
    columns: BoardColumn[],
  ): { count: number; label: string } | null => {
    const counts = companyStages.get(company);
    if (!counts) return null;
    const others = columns.filter((c) => c.key !== here && counts[c.key] > 0);
    const count = others.reduce((n, c) => n + counts[c.key], 0);
    const label = elsewhereLabel(
      count,
      others.map((c) => c.label),
    );
    return label === null ? null : { count, label };
  };

  async function moveTo(appId: number, stageKey: StageKey) {
    const app = applications.find((a) => a.id === appId);
    if (!app || stageOf(shownStatus(app)) === stageKey) return;
    // The stage keys are themselves canonical statuses the PATCH accepts; a
    // drop onto `closed` files as `rejected`, and the select is where the
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

  // Never on the inert preview: `interactive={false}` renders inside
  // `pointer-events-none`, where 14 fixtures cleared this threshold and put a
  // search box on a brand-new user's first dashboard that they could not type
  // into.
  const showSearch = interactive && applications.length > SEARCH_AFTER;

  const columns = boardColumns(STAGES);
  /**
   * The spine states the ACCOUNT's distribution — never the current view's,
   * and never this page's.
   *
   * Not the view's: the counts ignore the search and the company filter, so
   * typing never reflows the pipeline's stated shape. The spine is the shape,
   * the list is what you are looking at.
   *
   * Not the page's: counting the loaded rows was wrong by construction. Past
   * `BOARD_PAGE_SIZE` an account's columns would sum to the page, not the
   * account, and contradict the subtitle's own total the way the scope note
   * exists to prevent. `stageTotals` is the database's `GROUP BY status`, so
   * when the caller has it, it wins — and it stays right whatever the list
   * shows, including once several applications at one employer share a card.
   * A caller cannot supply `total` without it (see `BoardScope`).
   *
   * Optimistic moves still land immediately: a pending drop is a ±1 delta on
   * top of whichever base is in use, and settles when `router.refresh()`
   * brings the server's own count back.
   *
   * The GROUP HEADINGS below are deliberately NOT treated this way — they
   * label the rows actually listed, where "applied — 250" over 200 loaded
   * rows would be its own lie. Spine = the account; headings and `scopeNote`
   * = this page.
   */
  const spineCounts: Record<StageKey, number> = stageTotals
    ? { ...stageTotals }
    : { applied: 0, assessment: 0, interviewing: 0, offered: 0, rejected: 0 };
  if (stageTotals) {
    for (const app of applications) {
      const pending = pendingMoves[app.id];
      if (pending === undefined) continue;
      spineCounts[stageOf(app.status)] -= 1;
      spineCounts[stageOf(pending)] += 1;
    }
  } else {
    for (const app of applications) spineCounts[stageOf(shownStatus(app))] += 1;
  }
  /** "all" must equal the columns it sits above, so it is summed from the same
   *  source rather than read off `applications.length`. */
  const spineTotal = columns.reduce((n, column) => n + spineCounts[column.key], 0);
  const spineMax = Math.max(1, ...columns.map((c) => spineCounts[c.key]));

  /** Groups actually rendered in the list: the selected stage (even empty, so
   *  "none yet"/"none match" has a place to be said), or every stage that has
   *  matching rows when the lens is `all` — an empty stage's emptiness is the
   *  spine's line to speak, not a full-width box of nothing. */
  const groups = columns
    .map((column) => ({
      column,
      items: filtered.filter((a) => stageOf(shownStatus(a)) === column.key),
    }))
    .filter(({ column, items }) =>
      stageFilter === "all" ? items.length > 0 : column.key === stageFilter,
    );

  const locked = variant === "locked";

  /** One application row in its animated cell. `inSet` rows sit inside an
   *  employer set: the header owns the company-level affordance, so the
   *  member's own chip is suppressed. */
  const rowCell = (app: Application, column: BoardColumn, inSet = false) => {
    const chip = inSet || !grouping ? null : crossStageChip(app.company, column.key, columns);
    return (
      <BoardCell key={`app-${app.id}`} layoutKey={`app-${app.id}`} entering={hydrated}>
        {interactive ? (
          <ApplicationRow
            app={app}
            columnLabel={column.label}
            today={today}
            transport={transport}
            onOpenDetail={setDetailApp}
            inSet={inSet}
            sameCompanyCount={inSet ? 0 : sameCompanyCount(app)}
            sameCompanyLabel={chip?.label ?? null}
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
          <StaticApplicationRow
            app={app}
            columnLabel={column.label}
            today={today}
            inSet={inSet}
            sameCompanyCount={inSet ? 0 : sameCompanyCount(app)}
            sameCompanyLabel={chip?.label ?? null}
            onFilterCompany={setCompanyFilter}
          />
        )}
      </BoardCell>
    );
  };

  const dropHandlers = (column: BoardColumn) =>
    interactive
      ? {
          onDragOver:
            draggingId !== null
              ? (event: React.DragEvent) => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "move";
                  setDropStage(column.key);
                }
              : undefined,
          onDrop: (event: React.DragEvent) => {
            event.preventDefault();
            const id = Number(event.dataTransfer.getData("text/plain"));
            setDropStage(null);
            setDraggingId(null);
            if (Number.isInteger(id) && id > 0) void moveTo(id, column.key);
          },
        }
      : {};

  /** One stage entry — shared anatomy between the spine (vertical, metered)
   *  and the chip strip (horizontal, compact). */
  const stageButton = (column: BoardColumn, kind: "spine" | "chip") => {
    const count = spineCounts[column.key];
    const active = stageFilter === column.key;
    const common = {
      "aria-label": `${column.label} — ${count}`,
      "aria-pressed": active,
      onClick: () => setStageFilter(active ? "all" : column.key),
    } as const;
    if (kind === "chip") {
      return (
        <button
          key={column.key}
          type="button"
          {...common}
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
            active
              ? "border-line-strong bg-surface-2 text-strong"
              : "border-line-soft text-muted hover:text-strong",
          )}
        >
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: column.color }}
            aria-hidden="true"
          />
          {column.label}
          <span className="tabular font-mono text-[11px]">{count}</span>
        </button>
      );
    }
    return (
      <button
        key={column.key}
        type="button"
        {...common}
        data-drop={dropStage === column.key || undefined}
        {...dropHandlers(column)}
        className={cn(
          "spine-stage w-full rounded-lg border px-2.5 py-1 text-left transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong",
          active
            ? "border-line-strong bg-surface-2"
            : "border-transparent hover:border-line-soft hover:bg-surface-2/60",
        )}
      >
        <span className="flex items-center gap-2">
          <span
            className="h-1.5 w-1.5 shrink-0 rounded-full"
            style={{ background: column.color }}
            aria-hidden="true"
          />
          <span className={cn("text-xs font-medium", active ? "text-strong" : "text-muted")}>
            {column.label}
          </span>
          <span className="tabular ml-auto font-mono text-[11px] text-strong">{count}</span>
        </span>
        {/* The meter: this stage's share of the loaded rows. Only drawn when
            there is a share to draw — the 0 beside the label already states
            emptiness, and on the real account's shape (every row in one
            stage) an empty track under each of four zeros was five bars
            representing nothing. */}
        {count > 0 ? (
          <span
            className="mt-1 block h-1 overflow-hidden rounded-full bg-surface-2"
            aria-hidden="true"
          >
            <span
              className="block h-full rounded-full"
              style={{
                width: `${(count / spineMax) * 100}%`,
                background: column.color,
              }}
            />
          </span>
        ) : null}
      </button>
    );
  };

  /** The one search field, mounted wherever the stage lens lives (the rail
   *  at `md`+ in the shell, the command row otherwise) — searching and stage
   *  filtering are the same act on the same list, so they share a home. */
  const searchBox = showSearch ? (
    <div className="relative min-w-0">
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
  ) : null;

  /** The "all" row of the vertical stage lens (spine or rail). */
  const allStagesRow = (
    <button
      type="button"
      aria-label={`all stages — ${spineTotal}`}
      aria-pressed={stageFilter === "all"}
      onClick={() => setStageFilter("all")}
      className={cn(
        "w-full rounded-lg border px-2.5 py-1 text-left transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong",
        stageFilter === "all"
          ? "border-line-strong bg-surface-2"
          : "border-transparent hover:border-line-soft hover:bg-surface-2/60",
      )}
    >
      <span className="flex items-center gap-2">
        <span
          className={cn(
            "text-xs font-medium",
            stageFilter === "all" ? "text-strong" : "text-muted",
          )}
        >
          all
        </span>
        <span className="tabular ml-auto font-mono text-[11px] text-strong">{spineTotal}</span>
      </span>
    </button>
  );

  /**
   * The transient scope lines (an active filter's count, the bounded-page
   * note). Their own slim row above the band — present only while they have
   * something to say, so the resting board spends nothing on them.
   */
  const scopeLines =
    filterActive || scopeNote ? (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {filterActive ? (
          <span className="tabular shrink-0 text-xs text-dim" role="status">
            {filtered.length} of {applications.length} shown
          </span>
        ) : null}
        {/* The subtitle counts the whole account; this list can only count
            what loaded. Without this line "250 filed" sat above a list
            summing to 200 and neither number explained the other. */}
        {scopeNote ? (
          <span className="tabular text-xs text-dim">
            board shows the {scopeNote} · older rows aren&apos;t loaded
          </span>
        ) : null}
      </div>
    ) : null;

  return (
    <div
      data-testid="pipeline-board"
      className={cn("flex flex-col gap-3", locked && "lg:min-h-0 lg:flex-1")}
    >
      {/* --- The stage lens + search, in the shell's rail --------------------
          One instance, portaled: the DOM lands in the sidebar's middle run,
          the state stays here. Appears with hydration — the rail is a fixed
          column, so nothing on the page moves when it does, and everything
          in it is interactive-only (a filter without JS is a label). */}
      {railStages && rail
        ? createPortal(
            <div role="group" aria-label="Stages" className="flex flex-col gap-0.5">
              {searchBox ? <div className="mb-2 px-0.5">{searchBox}</div> : null}
              <p className="label-caps px-2.5 pb-1">stages</p>
              {allStagesRow}
              {columns.map((column) => stageButton(column, "spine"))}
            </div>,
            rail,
          )
        : null}

      {/* Search when there is no rail to hold it: always on the no-shell
          twins, below `md` (where the rail is hidden) in the shell. Same
          both-in-DOM, breakpoint-picked shape as the chips/spine pair below
          — one state, one visible control per width. */}
      {searchBox ? (
        <div className={cn("w-full sm:max-w-56", railStages && "md:hidden")}>{searchBox}</div>
      ) : null}

      {scopeLines}

      {/* --- The pulse band (lg-up) ------------------------------------------
          Full width, above the worklist — the dashboard's own content area,
          which is the one home the owner has accepted for it. One instance:
          below `lg` the cards carry the same ground truth (age tags,
          deadline tags, the review queue), so nothing renders. */}
      {pulse ? (
        <PipelinePulse
          applications={applications}
          total={total ?? applications.length}
          needsReview={pulse.needsReview}
        />
      ) : null}

      {/* --- The stage lens, compressed --------------------------------------
          Chips until the vertical lens takes over — the rail from `md` in the
          shell, the in-board spine from `lg` outside it. `flex-wrap`, not a
          scroller: at 375px the horizontal scroller cut "offered" to "offer"
          at the viewport edge and hid "closed" entirely, with no affordance
          that anything was scrollable — a filter you cannot see is a filter
          that does not exist. Two wrapped lines cost ~30px and keep every
          stage visible. */}
      <div
        className={cn(
          "flex flex-wrap items-center gap-1.5",
          railStages ? "md:hidden" : "lg:hidden",
        )}
      >
        <button
          type="button"
          aria-label={`all stages — ${spineTotal}`}
          aria-pressed={stageFilter === "all"}
          onClick={() => setStageFilter("all")}
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
            stageFilter === "all"
              ? "border-line-strong bg-surface-2 text-strong"
              : "border-line-soft text-muted hover:text-strong",
          )}
        >
          all
          <span className="tabular font-mono text-[11px]">{spineTotal}</span>
        </button>
        {columns.map((column) => stageButton(column, "chip"))}
      </div>

      {/* --- Body: (spine +) worklist ----------------------------------------
          In the shell the lens is in the rail, so the worklist takes the full
          measure — every row gains the column the spine used to hold. */}
      <div
        className={cn("flex flex-col gap-4 lg:flex-row lg:gap-5", locked && "lg:min-h-0 lg:flex-1")}
      >
        {!railStages ? (
          /* w-44, not the w-52 the pulse-in-spine era needed: the longest
             stage word + count fits comfortably, and every horizontal pixel
             the emptier column gives back goes to the rows. */
          <aside
            aria-label="Stages"
            className={cn(
              "hidden w-44 shrink-0 flex-col gap-0.5 lg:flex",
              locked ? "lg:min-h-0 lg:overflow-y-auto" : "lg:sticky lg:top-5 lg:self-start",
            )}
          >
            <p className="label-caps px-2.5 pb-1">stages</p>
            {allStagesRow}
            {columns.map((column) => stageButton(column, "spine"))}
          </aside>
        ) : null}

        <div className={cn("flex min-w-0 flex-1 flex-col gap-3", locked && "lg:min-h-0")}>
          {/* --- The filter state, stated once ------------------------------ */}
          {companyFilter !== null ? (
            <CompanyBand
              company={companyFilter}
              partial={truncated}
              onClear={() => setCompanyFilter(null)}
            />
          ) : null}

          {moveError ? (
            <p role="alert" className="text-xs text-reject-ink">
              {moveError}
            </p>
          ) : null}

          {/* --- The worklist ------------------------------------------------
              In the locked variant this region is the dashboard's ONE scroll
              context; sticky group headings keep the stage legible while the
              rows underneath move. In flow it is ordinary page content. */}
          <LayoutGroup>
            {/* `worklist-pane` is the geometry assertion's handle: the e2e
                lock specs (shell.spec.ts, via /demo/shell) prove this region
                overflows and scrolls while the document and <main> hold — a
                lock nothing pushes against would pass vacuously. */}
            <div
              data-testid="worklist-pane"
              className={cn(
                "space-y-4",
                locked && "lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:pr-1",
              )}
            >
              {beforeList}
              {groups.map(({ column, items }) => (
                <section
                  key={column.key}
                  aria-label={`${column.label} — ${items.length}`}
                  data-drop={dropStage === column.key || undefined}
                  {...dropHandlers(column)}
                  className="board-col rounded-xl transition-colors"
                >
                  <div
                    className={cn(
                      "mb-2 flex items-baseline gap-2 px-1",
                      locked && "lg:sticky lg:top-0 lg:z-10 lg:bg-background lg:py-1",
                    )}
                  >
                    <span className="label-caps inline-flex items-center gap-1.5 text-muted">
                      <span
                        className="h-1.5 w-1.5 rounded-full"
                        style={{ background: column.color }}
                        aria-hidden="true"
                      />
                      {column.label}
                    </span>
                    <span className="tabular font-mono text-xs text-muted">{items.length}</span>
                    <span className="h-px flex-1 bg-line-soft" aria-hidden="true" />
                  </div>
                  <ul className="space-y-1.5">
                    {items.length === 0 ? (
                      <li className="rounded-lg border border-dashed border-line-soft p-4 text-center text-xs text-dim">
                        {filterActive ? "none match" : "none yet"}
                      </li>
                    ) : grouping ? (
                      // One entry per employer within this stage: singletons
                      // (most rows) render exactly as before; a multi-row
                      // employer folds into a set that opens inline. The
                      // heading above still counts `items` — applications,
                      // never cards.
                      groupByEmployer(items).map((entry) =>
                        entry.kind === "single" ? (
                          rowCell(entry.app, column)
                        ) : (
                          <BoardCell
                            key={`set-${entry.company}`}
                            layoutKey={`set-${column.key}-${entry.company}`}
                            entering={hydrated}
                          >
                            <EmployerSetRow
                              company={entry.company}
                              items={entry.items}
                              column={column}
                              today={today}
                              open={openSets[`${column.key}:${entry.company}`] === true}
                              onToggle={() => toggleSet(`${column.key}:${entry.company}`)}
                              chip={crossStageChip(entry.company, column.key, columns)}
                              onFilterCompany={setCompanyFilter}
                            >
                              {entry.items.map((app) => rowCell(app, column, true))}
                            </EmployerSetRow>
                          </BoardCell>
                        ),
                      )
                    ) : (
                      items.map((app) => rowCell(app, column))
                    )}
                  </ul>
                </section>
              ))}
              {stageFilter === "all" && groups.length === 0 ? (
                <p className="rounded-lg border border-dashed border-line-soft p-4 text-center text-xs text-dim">
                  {filterActive ? "none match" : "none yet"}
                </p>
              ) : null}
              {afterList}
            </div>
          </LayoutGroup>
        </div>
      </div>

      {interactive ? (
        <ApplicationDetail
          app={detailApp}
          onClose={() => setDetailApp(null)}
          transport={transport}
        />
      ) : null}
    </div>
  );
}
