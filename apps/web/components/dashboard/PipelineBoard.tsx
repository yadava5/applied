"use client";

import { Search } from "lucide-react";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import { useRouter } from "next/navigation";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FocusEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { ApplicationRow, NO_ROLE_LABEL } from "@/components/dashboard/ApplicationRow";
import { ApplicationDetail } from "@/components/dashboard/ApplicationDetail";
import { DeadlineTag, FiledStamp, SameCompanyChip } from "@/components/dashboard/CardMeta";
import { CompanyBand } from "@/components/dashboard/CompanyBand";
import { EmployerSetRow } from "@/components/dashboard/EmployerSetRow";
import { PipelinePulse } from "@/components/dashboard/PipelinePulse";
import { PulseFilterBand } from "@/components/dashboard/PulseFilterBand";
import { useShellSlots } from "@/components/shell/shell-slots";
import { useLocalToday } from "@/lib/dashboard/useLocalToday";
import { boardColumns, cardQualifier, type BoardColumn } from "@/lib/dashboard/board";
import { filedAt } from "@/lib/dashboard/dates";
import { matchesPulseFilter, type PulseFilter } from "@/lib/dashboard/pulseFilter";
import { elsewhereLabel, groupByEmployer } from "@/lib/dashboard/employerGroups";
import { cn } from "@/lib/utils";
import { type Application, STAGES, stageOf, type StageKey } from "@/lib/dashboard/summary";
import {
  NEIGHBOUR_WARM_DELAY_MS,
  neighbourIdsToWarm,
} from "@/lib/dashboard/neighbourWarm";
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

/**
 * Whether the detail DOCKS beside the worklist — Tailwind's `lg`, the same
 * boundary where the shell's viewport lock and the board's side-by-side row
 * begin, so the JS gate and the CSS geometry stop straddling breakpoints.
 * #157 shipped this at `xl` on the claim that "below 1280 there is no width
 * to give" — written before the rows folded their controls, and wrong by
 * measurement once the pane narrows with the viewport (the width ramp lives
 * on the pane, see ApplicationDetail): at 1024 the shell's content run is
 * 736px (the w-60 rail and <main>'s px-6 off the viewport), and a ~307px
 * pane leaves the worklist ~409px of folded rows — a working list beside a
 * readable card, where the sheet it replaces dimmed, blurred and blocked the
 * whole board at the owner's actual 1024px window. Below `lg` the shell
 * releases the lock and the board is one flowing column: no second column
 * exists to keep in sight, so the modal sheet stays. JS rather than CSS
 * because the two geometries differ in behaviour (focus, Escape, scroll
 * lock), not just position — exactly one of them may exist at a time, and
 * rendering both would run the detail fetch twice. False until the
 * subscription lands (the server has no viewport); a card can only be opened
 * after it has.
 */
function useDetailDocked(): boolean {
  const [docked, setDocked] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const sync = () => setDocked(mq.matches);
    // First read deferred off the effect body (house rule — no synchronous
    // setState in an effect), same as the board's own `hydrated`.
    const id = window.setTimeout(sync, 0);
    mq.addEventListener("change", sync);
    return () => {
      window.clearTimeout(id);
      mq.removeEventListener("change", sync);
    };
  }, []);
  return docked;
}

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
  travel,
  children,
}: {
  layoutKey: string;
  entering: boolean;
  /** Seconds for the shared-layout glide (`travel` on the board). Only the
   *  LAYOUT transition slows — the opacity settle keeps the default tempo,
   *  so entering rows never fade in slow motion. */
  travel?: number;
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
      // `travel` marks a CHOREOGRAPHED mount (the landing's window act), where
      // no row ever enters: the fixture is fixed and the only thing that moves
      // is the one row the act carries between groups. Changing group remounts
      // the cell under a different `<ul>`, so `initial` would fade that row in
      // over its first 220ms of travel — a flicker on the exact element the
      // scene exists to make visible. A row that already existed should move,
      // not arrive.
      initial={entering && !reduceMotion && travel === undefined ? { opacity: 0, y: 6 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={
        reduceMotion
          ? { duration: 0 }
          : {
              duration: 0.22,
              ease: [0.22, 1, 0.36, 1],
              layout: { duration: travel ?? 0.22, ease: [0.22, 1, 0.36, 1] },
            }
      }
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

/**
 * The application id behind a ROW's stage select, or null for anything else.
 *
 * Deliberately anchored: the detail pane's own select is `detail-status-<id>`
 * and must not match. The pane outlives a regroup, so it needs none of the
 * restore below — matching it here would remember a row whose control never
 * went anywhere.
 */
function rowSelectId(node: EventTarget | null): number | null {
  if (!(node instanceof HTMLElement)) return null;
  const match = /^status-(\d+)$/.exec(node.id);
  return match === null ? null : Number(match[1]);
}

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
  search = true,
  openDetailId,
  travel,
  focusScrollOnOpen = true,
}: {
  applications: Application[];
  interactive?: boolean;
  /** Whether the board offers its search field (over `SEARCH_AFTER` rows).
   *  Off on the marketing embeds (`components/marketing/MarketingBoard.tsx`):
   *  a sales page shows what the product did, not its query tools. Every
   *  product surface keeps the default. */
  search?: boolean;
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
  /**
   * A card to open PROGRAMMATICALLY — the marketing embeds' composition seed
   * (the merged landing opens the moved row's detail as the visitor arrives
   * at that beat). Each id is honoured once, only while the pane geometry is
   * docked (the modal sheet must never appear unbidden), and never over a
   * card the visitor opened themselves. Unlike a user's own open it does NOT
   * move focus into the pane — no gesture happened, so stealing focus (and
   * the scroll `focus()` drags with it) would be the page acting on its own.
   * Product surfaces never pass this; their detail opens by click alone.
   */
  openDetailId?: number;
  /**
   * Seconds for a row's shared-layout glide between stage groups. Product
   * surfaces omit it and keep the board's own 220ms tempo; the marketing
   * embed slows the one move it choreographs to a watchable speed
   * (`components/marketing/tempo.ts`), because a sales page's visitor has no
   * idea which row is about to travel and a 220ms cut reads as a teleport.
   */
  travel?: number;
  /**
   * Whether a user-open's focus may scroll the page to reach the pane. Off
   * only on the marketing embeds' framed window, where the pane lives inside
   * a camera crop on a pinned runway and the browser's reveal scroll would
   * move the act's own clock — see ApplicationDetail's prop of the same
   * name. Every product surface keeps the default.
   */
  focusScrollOnOpen?: boolean;
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
  const detailDocked = useDetailDocked();
  const [query, setQuery] = useState("");
  const [companyFilter, setCompanyFilter] = useState<string | null>(null);
  /** The pulse detail panel's click-through (#156/#158/#159): a day, the
   *  quiet share, or a provenance group, applied to the same list the other
   *  filters narrow. State lives here because this is the component that owns
   *  the list; the panel only ever proposes. */
  const [pulseFilter, setPulseFilter] = useState<PulseFilter | null>(null);
  const [stageFilter, setStageFilter] = useState<StageFilter>("all");
  const [detailApp, setDetailApp] = useState<Application | null>(null);
  /** Whether the open detail was the USER's act — the pane only takes focus
   *  for a real gesture (see `openDetailId` above and ApplicationDetail's
   *  `focusOnOpen`). */
  const [detailUserOpened, setDetailUserOpened] = useState(true);
  const openDetail = (app: Application) => {
    setDetailUserOpened(true);
    setDetailApp(app);
  };
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

  /** The programmatic open, honoured once per id and only while docked — so
   *  the sub-`lg` modal sheet (scroll lock, focus trap) can never fire from
   *  it — and never over a card the visitor chose themselves. */
  const consumedDetailSeed = useRef<number | null>(null);
  useEffect(() => {
    if (openDetailId === undefined) {
      // The seed is WITHDRAWN. The landing's window act is a function of
      // scroll position now, so scrolling back up un-docks the pane the page
      // docked — and only that one: a card the visitor opened themselves is
      // theirs (`detailUserOpened`), and so is a re-open of the seeded row.
      const seeded = consumedDetailSeed.current;
      consumedDetailSeed.current = null;
      if (seeded === null || detailUserOpened || detailApp?.id !== seeded) return;
      const id = window.setTimeout(() => setDetailApp(null), 0);
      return () => window.clearTimeout(id);
    }
    if (!detailDocked) return;
    if (consumedDetailSeed.current === openDetailId) return;
    consumedDetailSeed.current = openDetailId;
    if (detailApp !== null) return; // the visitor's own open wins
    const app = applications.find((a) => a.id === openDetailId);
    if (!app) return;
    // Deferred off the effect body (house rule — no synchronous setState in
    // an effect), same as the board's own `hydrated`.
    const id = window.setTimeout(() => {
      setDetailUserOpened(false);
      setDetailApp(app);
    }, 0);
    return () => window.clearTimeout(id);
    // `detailApp` is read, not reacted to on the seeding path: the consumed
    // ref means a later detail change can never replay the seed. The
    // withdrawal path above genuinely needs both it and `detailUserOpened`,
    // to know whose pane is open.
  }, [openDetailId, detailDocked, applications, detailApp, detailUserOpened]);

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
  const filterActive = q !== "" || companyFilter !== null || pulseFilter !== null;
  const filtered = applications.filter((app) => {
    if (companyFilter !== null && app.company !== companyFilter) return false;
    if (pulseFilter !== null && !matchesPulseFilter(app, pulseFilter, today)) return false;
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
    /* A MOVE MUST NOT STRAND THE CARD IT MOVED (#772). If the destination
       stage already holds rows for this employer, the arriving card folds into
       that set — and a collapsed set member has no open button, is not
       draggable and has no select, so the card loses all three ways to move
       again, at the exact moment the reader was moving it. It recovers on
       expanding the group and nothing on screen says so.

       Opening the destination set is the whole fix, and it is the same
       mechanism `traverseDetail` already uses to keep the detail pane's "you
       are here" mark off a row that is not on screen.

       Unconditional, and optimistic. Unconditional because a key for a set
       that never forms is inert — cheaper than asking "will this fold?" from
       here, which would mean re-deriving `groupByEmployer`'s answer against
       rows that have not moved yet and getting a second opinion about it.
       Optimistic because the board hops on `pendingMoves` before the write
       returns, so waiting for the response would show a folded, unreachable
       card for the width of the request. */
    setOpenSets((s) => ({ ...s, [`${stageKey}:${app.company}`]: true }));
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
  const showSearch = interactive && search && applications.length > SEARCH_AFTER;

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

  /**
   * WHERE THE READER GOES WHEN A CORRECTION TAKES THEIR ROW AWAY (#425).
   *
   * The other half of that issue, and a different defect from the `disabled`
   * blur #777 repaired on the row itself. A stage-CHANGING correction moves
   * the row to another group, which unmounts the `<li>` and everything under
   * it — measured on /demo at 1024x768 with the sampler in
   * `tests/e2e/stage-focus.spec.ts`: the select detaches at 362-467ms across
   * runs, focus is on `<body>` from there to the end of the trace (t=2505),
   * and the write landed — so this is the SUCCESSFUL path losing the reader. Nothing inside the row survives to hold a place, so the repair
   * cannot live there; this component is the nearest thing that outlives the
   * move, and `#status-<id>` is a stable anchor that exists again in the NEW
   * section the instant the board regroups.
   *
   * THREE CONDITIONS, and each one is a way for this to be wrong if dropped:
   *
   *  - the reader was standing on THAT row's select (`focusedRowId`, fed by
   *    `focusin` on the pane). Without it a mouse drag-drop — which regroups a
   *    row nobody focused — would pull focus onto a control the reader never
   *    touched and paint a ring there.
   *  - the row's stage changed in THIS commit. A filter, a re-date or a
   *    sibling's move regroups nothing about this row and must not fire.
   *  - focus is on `<body>`. The same conditional contract `ApplicationDetail`
   *    uses for its pane restore: this claims only focus that has been
   *    DROPPED, never focus the reader has since put somewhere else.
   *
   * A LAYOUT effect, not a passive one: it runs after the commit's DOM
   * mutations and before paint, so there is no frame in which the ring is
   * missing and nothing to flicker. React 19 renders `useLayoutEffect` as a
   * noop on the server (checked in react-dom 19.2.8's server build), so the
   * SSR pass costs nothing and warns about nothing.
   *
   * NOTHING TESTS THAT CHOICE, said plainly so nobody assumes otherwise: the
   * e2e sampler reads every 8ms and the restore lands inside one sample either
   * way — swapping this for `useEffect` keeps `stage-focus.spec.ts` green 3/3
   * (measured). It is a decision about paint, held by this comment.
   *
   * ONE CASE IT DELIBERATELY DOES NOT REPAIR: a row that lands inside a
   * COLLAPSED employer set has no `#status-<id>` to return to. The lookup
   * fails, nothing is focused, and the reader is where today's code leaves
   * them — no regression, and no pretending.
   */
  const focusedRowId = useRef<number | null>(null);
  const stageById = useRef<Map<number, StageKey> | null>(null);
  const noteRowFocus = (event: FocusEvent<HTMLDivElement>) => {
    const id = rowSelectId(event.target);
    if (id !== null) focusedRowId.current = id;
  };
  useLayoutEffect(() => {
    const next = new Map<number, StageKey>();
    for (const app of applications) next.set(app.id, stageOf(shownStatus(app)));
    const previous = stageById.current;
    stageById.current = next;
    // The first commit is a baseline, not a move: every row is "new" to the
    // map and nothing has changed group yet.
    if (previous === null) return;
    const id = focusedRowId.current;
    if (id === null) return;
    const before = previous.get(id);
    const after = next.get(id);
    if (before === undefined || after === undefined || before === after) return;
    if (document.activeElement !== document.body) return;
    // Consumed, so one correction restores focus once. Not cleared on
    // `focusout`: the unmount ITSELF blurs the select, and clearing there
    // would erase the one thing this needs to know at exactly the moment it
    // needs to know it.
    const control = document.getElementById(`status-${id}`);
    if (control !== null) {
      focusedRowId.current = null;
      control.focus({ preventScroll: true });
      return;
    }
    // THE ROW LANDED IN A COLLAPSED SET, which #425 recorded as not repaired
    // and left as its own line item. There is no `status-<id>` to return to
    // because the member rows of a collapsed set are not rendered at all, so
    // the reader was dropped at <body> and every subsequent Tab restarted
    // from the top of the document — the same defect the branch above fixes,
    // reached by a different route.
    //
    // The chosen place is the SET HEADER that now holds the row: it is where
    // the row went, it is one keystroke from opening it, and it is a control
    // that exists in every state this branch can be reached in. Focusing the
    // stage heading instead would be further from the row than the reader
    // was before the correction.
    const moved = applications.find((app) => app.id === id);
    if (moved === undefined) return;
    // Same key the set is rendered under — `groupByEmployer` groups on
    // `row.company` verbatim, so this needs no normalisation to agree.
    const key = `${after}:${moved.company}`;
    const header = Array.from(
      document.querySelectorAll<HTMLElement>("[data-set-toggle]"),
    ).find((element) => element.dataset.setToggle === key);
    if (header === undefined) return;
    focusedRowId.current = null;
    header.focus({ preventScroll: true });
  });

  const locked = variant === "locked";

  /**
   * The board's visible order, flattened — the detail pane's traversal list
   * (#157). Built from `groups` exactly as the list renders them (stage flow
   * order, employer sets in place, members in their set order), so "next" in
   * the pane is always the row the eye finds below. Members of COLLAPSED
   * sets are included on purpose: M is the number of applications on view,
   * the same number the stage headings sum to — traversal opens a set it
   * lands in rather than silently skipping it (see `traverseDetail`).
   */
  const orderedVisible: Application[] = [];
  /** Set membership by row id (`${stage}:${company}`), for the auto-open. */
  const memberSetKey = new Map<number, string>();
  for (const { column, items } of groups) {
    if (grouping) {
      for (const entry of groupByEmployer(items)) {
        if (entry.kind === "single") {
          orderedVisible.push(entry.app);
        } else {
          for (const member of entry.items) {
            orderedVisible.push(member);
            memberSetKey.set(member.id, `${column.key}:${entry.company}`);
          }
        }
      }
    } else {
      orderedVisible.push(...items);
    }
  }
  const detailIndex =
    detailApp === null ? -1 : orderedVisible.findIndex((a) => a.id === detailApp.id);

  /** The ids ↑ and ↓ would land on, joined into one primitive key. The effect
   *  below must depend on the IDS, not on `orderedVisible` — that array is
   *  rebuilt every render, so depending on it would re-arm the timer on every
   *  render and the warm would never fire. */
  const neighbourKey = neighbourIdsToWarm(orderedVisible, detailIndex).join(",");

  /**
   * Warm the open card's neighbours (#203 §7, the remaining half).
   *
   * The pane itself already answers the click with no network at all: company,
   * role, stage, filed date and deadline all come off the row this board is
   * already holding. The ONE thing that waits is "the mail behind this card".
   * `lib/dashboard/neighbourWarm.ts` carries the measurements and the reason
   * this is a prefetch rather than an attempt to make the request faster.
   *
   * `transport.detail` is the entire mechanism — it reads `detailCache` first
   * and writes it on success — so a warmed row costs the reader zero requests
   * and is never fetched twice. Every invalidation path already covers what
   * lands here: row mutations drop the row, a sync/rebuild clears the cache
   * whole, and the 30 s TTL bounds the rest. Nothing can go stale here that
   * could not already go stale on a reopen.
   *
   * `interactive` gates it so the landing embeds and the locked board never
   * speculate; `/demo` passes a fixture transport, whose `detail` is in-memory
   * and touches no network, so this is inert there by construction.
   */
  useEffect(() => {
    if (!interactive || neighbourKey === "") return;
    const ids = neighbourKey.split(",").map(Number);
    const timer = window.setTimeout(() => {
      for (const id of ids) void transport.detail(id);
    }, NEIGHBOUR_WARM_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [interactive, neighbourKey, transport]);

  /** ↑/↓ from the detail: move to the neighbouring visible card, clamped at
   *  the ends. Landing on a member of a collapsed employer set opens the set
   *  first — the "you are here" mark must never sit on a row that is not on
   *  screen, which is where a naive pane breaks on the grouped board. */
  const traverseDetail = (delta: -1 | 1) => {
    if (detailIndex === -1) return;
    const next = orderedVisible[detailIndex + delta];
    if (!next) return;
    const setKey = memberSetKey.get(next.id);
    if (setKey !== undefined && openSets[setKey] !== true) {
      setOpenSets((s) => ({ ...s, [setKey]: true }));
    }
    openDetail(next);
  };

  /** The docked pane is open: rows fold their stage select + Gmail slot to
   *  pay for its width — but only where the worklist is actually too narrow
   *  to hold both (#173). The fold is a container query against the
   *  worklist's own measure (< 32rem folds; see ApplicationRow), not a
   *  viewport rule, because the same board runs in runs of different width:
   *  beside the open pane the shell measures 588/748px at 1280/1440 (rows
   *  keep their controls), 409px at the 1024 dock floor (they fold, and the
   *  pane's own select + ↑/↓ and drag-to-stage are the stage paths), and
   *  /demo's max-w-6xl run 504px at every desktop width (folds). Never true
   *  below `lg`. */
  const detailPaneOpen = interactive && detailDocked && detailApp !== null;

  /** One application row in its animated cell. `inSet` rows sit inside an
   *  employer set: the header owns the company-level affordance, so the
   *  member's own chip is suppressed. */
  const rowCell = (app: Application, column: BoardColumn, inSet = false) => {
    const chip = inSet || !grouping ? null : crossStageChip(app.company, column.key, columns);
    return (
      <BoardCell key={`app-${app.id}`} layoutKey={`app-${app.id}`} entering={hydrated} travel={travel}>
        {interactive ? (
          <ApplicationRow
            app={app}
            columnLabel={column.label}
            today={today}
            transport={transport}
            onOpenDetail={openDetail}
            folded={detailPaneOpen}
            detailOpen={detailApp !== null && detailApp.id === app.id}
            revealOnOpen={detailUserOpened}
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
          /* THE HIGHLIGHT HAD NO WAY TO CLEAR (#772). `onDragOver` set it and
             nothing unset it until a drop, so a stage the pointer had already
             left stayed lit — during a drag the visible affordance and the
             actual drop target disagreed, which is the one moment a board must
             not lie about where a card will land.

             TWO GUARDS, and each is a bug without the other:

             `contains(relatedTarget)` — `dragleave` also fires when the
             pointer crosses into a CHILD of this target, and a section full of
             cards is nothing but children. Clearing there strobes the
             highlight off and on for every row the pointer passes over.
             `relatedTarget` is null when the pointer leaves the window
             entirely, which is a real leave and must clear.

             The functional `setDropStage` — `dragenter` on the NEXT stage
             fires before `dragleave` on this one, so a bare `setDropStage(null)`
             would erase a highlight its successor had already set and leave the
             board dark over a valid target. Clearing only when the stage is
             still ours makes the order irrelevant. */
          onDragLeave:
            draggingId !== null
              ? (event: React.DragEvent) => {
                  const next = event.relatedTarget;
                  if (next instanceof Node && event.currentTarget.contains(next)) return;
                  setDropStage((current) => (current === column.key ? null : current));
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
          /* THE ONLY DROP TARGET AN EMPTY STAGE HAS BELOW THE SPINE (#772).
             `groups` drops empty columns, so an empty stage renders no
             `<section>` to drop onto and the spine — which does carry these —
             is `hidden` until `lg` (or `md` in the shell). Measured: five
             stages accepted a drop at 900px and an empty stage accepted none
             at 700px or 390px. That is a narrow desktop window, which is
             exactly where board drag is plausible; the phone width is not the
             case this is for. Same handlers as the spine button, deliberately:
             two drop surfaces built from one definition cannot disagree about
             what a drop does. */
          data-drop={dropStage === column.key || undefined}
          {...dropHandlers(column)}
          className={cn(
            // `stage-chip` earns the same `[data-drop]` wash the spine and the
            // list columns already have. Without it this target would accept a
            // drop and show nothing — a drop point with no affordance, which is
            // the same lie as an affordance with no drop point.
            "stage-chip inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
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
        {/* The meter: this stage's share of the TOTAL (`count / spineTotal`).

            It used to be a share of the BIGGEST stage (`count / spineMax`), so
            the largest stage always drew a full bar by construction. On the
            owner's real board — 40 applications, 34 of them at "applied" — that
            painted "applied" full and he read it, correctly, as a lie: "if we
            have 40 in total, and 35 applied, why the hell is the applied row
            full!". A bar that is full when the thing is not complete has no
            honest reading, whatever the comment above it says, and the previous
            comment said the quiet part out loud while keeping the behaviour.

            Share-of-total has one reading, and the track states its own scale:
            the track is full width and means the total, the fill is this
            stage's share of it, and the unfilled remainder is the rest of the
            applications. So full means "all of them" and 34/40 lands at 85%.
            (The "all" row deliberately carries no bar — see `allStagesRow`
            for the 3px that cost.) The label beside each bar still prints
            a raw count and never a percentage — applied#78 was a percentage
            label disagreeing with the geometry beside it, and one number stated
            once is what keeps them from drifting again.

            Only drawn when the count is non-zero — the 0 beside the label
            already states emptiness, and on the real account's shape an empty
            track under each of three zeros was bars representing nothing. */}
        {count > 0 ? (
          <span
            className="mt-1 block h-1 overflow-hidden rounded-full bg-surface-2"
            aria-hidden="true"
          >
            <span
              className="block h-full rounded-full"
              style={{
                width: `${(count / spineTotal) * 100}%`,
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
      {/* Deliberately NO meter on this row, and the reason is worth keeping.
          A first pass gave it a full-width reference track so "full" would
          have something to mean. That was 8px (mt-1 + h-1) added to a column
          whose slack was 5px, and demo.spec.ts's "#122's shape" assertion went
          red: the rail's middle run scrolled by 3px and a lens row fell below
          the fold — the exact defect that test exists for.

          It was also redundant. Once the meters below are shares of the TOTAL,
          every stage's own empty track already IS the reference: the track is
          full width, the fill is that stage's share, and the unfilled
          remainder is the rest of the applications. The scale is stated on
          every row that has a bar; a fourth copy of it here bought nothing and
          cost the row that gets pushed off screen. */}
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
          onFilter={setPulseFilter}
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
          {pulseFilter !== null ? (
            <PulseFilterBand filter={pulseFilter} onClear={() => setPulseFilter(null)} />
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
                lock nothing pushes against would pass vacuously.

                `relative` is load-bearing and deliberately UNPREFIXED: a scroll
                container has to be the containing block for its descendants'
                absolutes, or they resolve against the initial containing block
                and plant a box at document scale — which no `overflow` on any
                ancestor clips, so the VIEWPORT becomes the scroll container and
                the whole shell scrolls away. `beforeList`/`afterList` are
                page-owned subtrees this component cannot audit, so the pane
                must guarantee the containing block rather than trust what is
                handed to it. Not hypothetical: `ReviewQueue` (the dashboard's
                held-mail queue, passed as one of those slots) positions nothing
                of its own, so its `sr-only` labels escaped exactly this way.
                Unprefixed because the escape is width-independent — below `lg`
                the pane has no `overflow`, but it still has to be the
                containing block.

                `@container` sizes the row-control fold (#173): a row keeps
                its stage select + Gmail slot beside the open detail pane iff
                THIS pane — the width the row actually has, not the viewport —
                measures 32rem+. Same idiom as SinceLastLook's chip: the room
                depends on the row-mates, and the pane is the row-mate. */}
            <div
              data-testid="worklist-pane"
              // React's `onFocus` IS `focusin` (React 17+), so it hears the
              // rows' selects from up here — one listener for the whole list
              // instead of a prop threaded through `ApplicationRow`, whose
              // `onChange` referential stability is the memo contract
              // `StageSelect` depends on.
              onFocus={noteRowFocus}
              className={cn(
                "space-y-4 @container",
                locked && "relative lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:pr-1",
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
                            travel={travel}
                          >
                            <EmployerSetRow
                              company={entry.company}
                              items={entry.items}
                              column={column}
                              today={today}
                              open={openSets[`${column.key}:${entry.company}`] === true}
                              onToggle={() => toggleSet(`${column.key}:${entry.company}`)}
                              setKey={`${column.key}:${entry.company}`}
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

        {/* --- The detail (#157) -------------------------------------------
            Mounted INSIDE the body row: at `lg+` it docks here, a pane
            beside the worklist — the board stays readable and usable while a
            card is open, which is the whole decision (the modal overlay's
            exclusivity contract was the complaint). Below `lg` the same
            component renders the fixed-position sheet, which ignores this
            flex row entirely. In the locked variant the pane inherits the
            row's height and scrolls itself; in flow it rides sticky like the
            spine. Floors are height-based, so a pane that only spends width
            cannot threaten them. */}
        {interactive ? (
          <ApplicationDetail
            app={detailApp}
            onClose={() => setDetailApp(null)}
            docked={detailDocked ? variant : false}
            position={
              detailIndex === -1
                ? null
                : { index: detailIndex, count: orderedVisible.length }
            }
            onTraverse={traverseDetail}
            transport={transport}
            focusOnOpen={detailUserOpened}
            focusScrollOnOpen={focusScrollOnOpen}
          />
        ) : null}
      </div>
    </div>
  );
}
