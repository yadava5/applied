"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AddApplicationForm } from "@/components/applications/AddApplicationForm";
import { EmptyBoardBody } from "@/components/dashboard/EmptyBoardBody";
import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { ReviewQueue } from "@/components/dashboard/ReviewQueue";
import { SinceLastLook } from "@/components/dashboard/SinceLastLook";
import { SyncBar, type SyncGmailState } from "@/components/dashboard/SyncBar";
import { LOCKED_PAGE_CLASS } from "@/components/shell/geometry";
import { DemoFixturePill } from "@/components/shell/SessionControls";
import type { NotificationPrefs } from "@/components/settings/NotificationsSection";
import { todayISO } from "@/lib/dashboard/age";
import {
  buildSubtitle,
  emptySubtitle,
  reviewSlotFor,
  type ReviewSlot,
} from "@/lib/dashboard/boardPrefs";
import {
  LAST_LOOK_DEMO_KEY,
  LAST_LOOK_DEMO_SCOPE,
} from "@/lib/dashboard/lastLook";
import {
  noteUserStageChange,
  toChangeRow,
} from "@/lib/dashboard/lastLookStore";
import { isApplicationStatus } from "@/lib/dashboard/status";
import { summarize, type Application } from "@/lib/dashboard/summary";
import type { BoardTransport, SyncTransport } from "@/lib/dashboard/transport";
import { useLocalToday } from "@/lib/dashboard/useLocalToday";
import { publishAmbientPulse } from "@/lib/shell/ambient-bus";
import {
  demoApplicationsAsApi,
  demoEarlySearchAsApi,
  demoUnsyncedAsApi,
} from "@/lib/demo/asApplications";
import { demoDetailBody } from "@/lib/demo/demoDetail";
import { datedById, redate } from "@/lib/demo/redate";
import { demoReviewQueueAsApi } from "@/lib/demo/reviewQueue";

/**
 * The demo dashboard: the REAL components — SyncBar, PipelineBoard, the cards,
 * the detail sheet — running their real state machines over an in-memory
 * fixture store instead of the network. Drag a card and it moves; open a card
 * and its (synthetic) mail trail renders; press Sync and the two not-yet-synced
 * fixture rows are filed onto the board; scan a window and every row on the
 * board is re-read; choose `Remove them` and the stale row goes, named on the
 * receipt and restorable from it. Nothing here is a mock of the UI — only the
 * transport is simulated, which is exactly what the "demo is the real thing"
 * contract asks for, and what lets the e2e suite execute the session-gated
 * surfaces.
 *
 * Simulation semantics mirror the product's promises:
 *   - the THREE runs are distinguishable, because on the live backend they are
 *     three different scans: a cursored Sync reads a little and estimates
 *     nothing, a keep-scan reads the whole window and removes nothing, a
 *     rebuild reads the whole window and purges what it did not find. A
 *     simulation that collapsed the first two would make the #474 control
 *     untestable — see the transport's first branch;
 *   - a rebuild removes only the stale AUTO row (Fernworks) and only while the
 *     visitor has not corrected it by hand — "rows you corrected are kept";
 *   - every receipt count is derived from what the store actually did, never
 *     invented after the fact;
 *   - restore puts the removed row back on the board, not just off the list,
 *     and counts as one of those corrections — a later pass keeps it.
 *
 * The store lives in a ref (single owner, mutated only from event handlers)
 * mirrored into state for rendering, so the transports can stay referentially
 * stable — a fresh transport each render would re-trigger the detail sheet's
 * load effect on every board change.
 */

interface DemoBoard {
  /** What the board shows. */
  apps: Application[];
  /** Fixture mail the account has not synced yet — an additive Sync files it. */
  pool: Application[];
  /** Rows the visitor corrected by hand — a rebuild must not remove these. */
  touched: number[];
}

/** The stale row a rebuild detects and removes (its mail no longer matches). */
const STALE_COMPANY = "Fernworks";

/**
 * The simulated mailbox's shape, kept coherent across runs: roughly
 * {@link ESTIMATE} job-related matches in total; an incremental sync reads
 * {@link ADDITIVE_SCAN}; a full rebuild reads {@link REBUILD_SCAN}; a shallow
 * depth-100 rebuild hits its message limit at {@link PARTIAL_SCAN} — which is
 * how the demo exercises the stopped-early truth-telling: choose the 100
 * message depth and the scan reports `stopped_by: "target"` instead of
 * claiming the mailbox was covered.
 */
const ADDITIVE_SCAN = 24;
const REBUILD_SCAN = 140;
const PARTIAL_SCAN = 100;
const ESTIMATE = 240;

const DEMO_GMAIL: SyncGmailState = {
  connected: true,
  lastSyncAt: null,
  hasCursor: true,
  syncStatus: null,
  syncError: null,
};

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Which fixture projection the twin renders — see `asApplications.ts`. */
export type DemoPipeline = "seed" | "early";

/**
 * Which of `PipelineBoard`'s two slots the fixture review queue lands in.
 * Named for the SLOT rather than for the Settings toggle that picks it on the
 * live page ("Needs review alerts"), because the harness that drives this is
 * measuring geometry: a test asking for `after` should not have to know that
 * the pref is off. The pref → slot mapping is `reviewSlotFor`, shared with
 * the signed-in dashboard page.
 */
export type DemoReviewSlot = ReviewSlot;

/** The twin's default prefs — the live default for a never-set flag
 *  (`readNotificationPrefs`), so an organic visitor sees exactly what a new
 *  account sees: the queue under the rows, no this-week fold. */
const DEFAULT_PREFS: NotificationPrefs = { weekly: false, reviewAlerts: false };

/** The whole fixture store, dated against one day — board and pool alike. */
function buildStore(today: string, pipeline: DemoPipeline): DemoBoard {
  return {
    apps:
      pipeline === "early"
        ? demoEarlySearchAsApi(today)
        : demoApplicationsAsApi(today),
    pool: demoUnsyncedAsApi(today),
    touched: [],
  };
}

export function DemoDashboard({
  pipeline = "seed",
  empty = false,
  variant = "flow",
  needsReview = 0,
  notifications = DEFAULT_PREFS,
  reviewSlot,
  sessionEdge = false,
}: {
  pipeline?: DemoPipeline;
  /** `locked` — what /demo and /demo/shell both mount (via `DemoShell`): the
   *  signed-in dashboard's exact geometry (`LOCKED_PAGE_CLASS` root,
   *  `variant="locked"` board), which is what makes the viewport-lock e2e
   *  assertions executable without a session. `flow` — natural height, the
   *  page scrolls; no route mounts it since /demo consolidated onto the
   *  shell, but it remains the honest default for a bare mount with no shell
   *  around it. Both mount the pulse where the real page does: the board's
   *  full-width band. */
  variant?: "flow" | "locked";
  /** Held verdicts: the pulse band's count AND the length of the fixture
   *  review queue mounted in the board's slot. 0 for every organic visitor —
   *  see the mount comment below — so no queue renders. /demo/shell's
   *  `?review=N` harness knob is the one caller that sets it. */
  needsReview?: number;
  /** The twin's notification preferences — the demo's stand-in for the
   *  Supabase user metadata the signed-in page reads, carried in a session
   *  cookie the Settings twin writes (`lib/demo/notificationPrefs.ts`). Both
   *  flags reach the board through the SAME two functions the live page uses,
   *  `buildSubtitle` and `reviewSlotFor`, which is what makes the twin's e2e
   *  a gate on the real wiring instead of a test of a parallel copy (#216). */
  notifications?: NotificationPrefs;
  /** A HARNESS OVERRIDE for the slot, and only that: /demo/shell's
   *  `?queue=before|after` needs to measure a placement without owning a
   *  preference. Unset — every organic visitor, and /demo — the slot comes
   *  from `notifications` above, whose default is `after`: the position a
   *  live account actually renders (the pref is off until turned on) and the
   *  one that produced the escaped-`sr-only` document scroll #149 fixed. */
  reviewSlot?: DemoReviewSlot;
  /** Mounts the SIGNED-IN session edge on the header row instead of the demo
   *  pill — `signedIn` on, `trailing` unset, exactly what
   *  `app/(app)/(protected)/dashboard/page.tsx` passes. Off for every organic visitor;
   *  /demo/shell's `?session=1` harness knob is the one caller that sets it,
   *  and it is the whole reason that knob exists: the pill is what the twin
   *  renders where the real page renders its session edge, so the one control
   *  #172 moved rendered on NO surface a test could reach. The item's
   *  behaviour is still fixture-mode, and the row's recency slot drops the
   *  simulated frame for the live `LastSynced` over this same fixture state
   *  (69px narrower, and the difference wraps the row) — both in `SyncBar`,
   *  both keyed off `signedIn`, neither reachable without the knob. */
  sessionEdge?: boolean;
  /**
   * Renders the EMPTY board — the real `EmptyBoardBody`, not a copy of it — in
   * place of the worklist, over the "mail not connected" state.
   *
   * FOURTH HARNESS KNOB, and the same argument as the three above: this is the
   * first screen of every new account and of every account whose Gmail is not
   * linked, and until now it rendered on no surface any executing test could
   * reach. The signed-in dashboard needs a session CI does not have (#188), and
   * this twin could only ever mount the POPULATED board — so when #495 locked
   * the populated branch's geometry, the empty branch quietly kept the flow
   * geometry, and nobody could see it. It scrolled chrome and all, which is
   * what got reported.
   *
   * It mounts the component the signed-in page mounts. That is the point: a
   * twin that RE-CREATED this subtree could drift from it, and this repo has
   * the scar — three rounds of "the dashboard is fixed" were measured on a
   * /demo whose composition had silently stopped matching. There is one
   * `EmptyBoardBody`, so there is nothing left to diverge.
   *
   * `/demo/shell?empty=1` is the one caller. Nothing links to it, the route is
   * `robots: noindex`, and the parse is exact-match. Its form writes on the
   * fixture transport (`mode="demo"`), like every other control here.
   */
  empty?: boolean;
}) {
  const locked = variant === "locked";
  // The day this demo is rendered against. UTC on the server and through
  // hydration, the visitor's own day once mounted — the same read the board,
  // the cards and the pulse make for themselves (`useLocalToday`).
  const today = useLocalToday();

  // ONE clock read per dating of the store: the fixture dates are relative, so
  // every row here — board and unsynced pool alike — is aged against the same
  // day the board renders with. Resolving them during render rather than at
  // module load is what keeps a long-lived server's HTML and the browser's
  // hydration agreeing on what "16 days ago" means.
  const [datedFor, setDatedFor] = useState(todayISO);
  const [snapshot, setSnapshot] = useState<DemoBoard>(() =>
    buildStore(datedFor, pipeline),
  );
  /** The pristine fixtures, kept for `restore` — the rows this board began
   *  with, before any drag, dismissal or rebuild touched them. */
  const original = useRef<Application[]>([...snapshot.apps, ...snapshot.pool]);
  const store = useRef(snapshot);
  const commit = useCallback((next: DemoBoard) => {
    store.current = next;
    setSnapshot(next);
  }, []);

  // The store is dated with the UTC day so the server's HTML and the first
  // client render agree; once the visitor's real day is known and it differs,
  // the fixtures are re-dated against it. They MUST be: the seeds are offsets
  // ("due in 9d", "overdue 2d") and the board now buckets them against the
  // local day, so leaving the store on the UTC day would shift every phrase on
  // /demo by one for the width of the visitor's UTC offset — and Kestrel's
  // "due in 2d" would fall out of the pulse's ≤2d cell for every reader
  // west of UTC.
  //
  // It re-dates what is THERE (`lib/demo/redate.ts`, which owns the rules and
  // is unit-tested) instead of installing fresh fixtures. The old version
  // committed `buildStore(today)`, which discarded whatever the visitor had
  // already done; no guard fixes that, because the transports await 300ms
  // before committing, so "has anything been touched yet" is false at exactly
  // the instant it needs to be true. Mapping has no such window: the swap can
  // land on either side of any commit and only dates move.
  //
  // `original` — the pristine rows a rebuild's Restore recovers from — is
  // rebuilt outright, which is correct: by definition it holds no edits, and
  // its rows must come back dated against the day the board is now showing.
  //
  // Not once-only, deliberately: a visitor whose own midnight passes while the
  // page is open gets a second, equally harmless re-dating. Deferred off the
  // effect body (the house rule, the same shape the detail sheet's reset uses)
  // so it lands in a macrotask rather than as a synchronous setState.
  useEffect(() => {
    if (datedFor === today) return;
    const id = window.setTimeout(() => {
      const pristine = buildStore(today, pipeline);
      const dated = datedById([...pristine.apps, ...pristine.pool]);
      const s = store.current;
      original.current = [...pristine.apps, ...pristine.pool];
      setDatedFor(today);
      commit({
        ...s,
        apps: redate(s.apps, dated),
        pool: redate(s.pool, dated),
      });
    }, 0);
    return () => window.clearTimeout(id);
  }, [today, datedFor, pipeline, commit]);

  const boardTransport = useMemo<BoardTransport>(
    () => ({
      async changeStatus(id, status) {
        await delay(300);
        // The wire contract is an ENUM (`ApplicationStatus`), not a free
        // string — `BoardTransport` still says `string`, so without this the
        // demo would happily write a value the live backend answers with a
        // 422 into a row typed as the backend's own response. The controls
        // only ever offer canonical statuses, so this never fires from the
        // UI; it fires if one of them ever drifts, which is the point.
        if (!isApplicationStatus(status)) {
          return {
            ok: false,
            detail: `“${status}” is not a status the API accepts`,
          };
        }
        const s = store.current;
        // The visitor moved this card themselves — fold it into the change
        // ledger's baseline so it is never reported back to them as news.
        // Same call, same reason, as the live transport.
        noteUserStageChange(LAST_LOOK_DEMO_KEY, id, status);
        // And, same as the live transport: a stage that moved surges the
        // rail's ambient field (only /demo/shell mounts a rail to hear it).
        publishAmbientPulse(1);
        commit({
          ...s,
          apps: s.apps.map((app) => (app.id === id ? { ...app, status } : app)),
          touched: s.touched.includes(id) ? s.touched : [...s.touched, id],
        });
        return { ok: true, status };
      },
      async setDeadline(id, dueAt) {
        await delay(300);
        const s = store.current;
        commit({
          ...s,
          apps: s.apps.map((app) =>
            app.id === id
              ? // The live backend's exact semantics: any write through the
                // deadline endpoint is the user's word (`due_source: "user"`),
                // and null clears both fields together.
                {
                  ...app,
                  due_at: dueAt,
                  due_source: dueAt === null ? null : ("user" as const),
                }
              : app,
          ),
          // A hand-set deadline is a correction — a rebuild keeps the row.
          touched: s.touched.includes(id) ? s.touched : [...s.touched, id],
        });
        return { ok: true };
      },
      async setRole(id, role) {
        await delay(300);
        const s = store.current;
        commit({
          ...s,
          apps: s.apps.map((app) =>
            app.id === id
              ? // The live backend's exact semantics (issue #72): the endpoint
                // normalises, so a blank draft clears both the title and the
                // claim on it, and anything else is the user's word —
                // `position_source: "user"`, which no sync overwrites.
                {
                  ...app,
                  position: role ?? "",
                  position_source: role === null ? null : ("user" as const),
                }
              : app,
          ),
          // Naming a role is a correction — a rebuild keeps the row.
          touched: s.touched.includes(id) ? s.touched : [...s.touched, id],
        });
        return { ok: true };
      },
      async dismiss(id) {
        await delay(300);
        const s = store.current;
        commit({ ...s, apps: s.apps.filter((app) => app.id !== id) });
        return { ok: true };
      },
      async deleteRow(id) {
        await delay(300);
        const s = store.current;
        commit({ ...s, apps: s.apps.filter((app) => app.id !== id) });
        return { ok: true };
      },
      async detail(id) {
        await delay(250);
        const app = store.current.apps.find((a) => a.id === id);
        return app
          ? { ok: true, body: demoDetailBody(app) }
          : { ok: false, body: {} };
      },
    }),
    [commit],
  );

  const syncTransport = useMemo<SyncTransport>(
    () => ({
      mode: "simulated",
      async sync(body) {
        // WINDOWEDNESS, not mode, is the first branch — and it has to be.
        // Since #474 the dialog can send `mode: "additive"` WITH a `count`,
        // which is the safe heal: a full re-read of the window that keeps rows
        // it doesn't find. Branching on `mode === "rebuild"` alone dropped that
        // request into the incremental path, so the new control behaved
        // exactly like pressing Sync here and any e2e written against it would
        // have asserted nothing at all. `count` is what the live backend reads
        // to drop its history cursor (`_history_cursor_for`), so it is the
        // right discriminator on both sides.
        const windowed = typeof body.count === "number";
        const rebuild = body.mode === "rebuild";
        // Long enough that the running state — and the windowed run's count-up
        // clock — actually renders and can be asserted; short enough that a
        // visitor never waits meaningfully.
        await delay(windowed ? 2400 : 1200);
        const s = store.current;
        const filed = s.pool;

        if (windowed && !rebuild) {
          // The keep-scan. It reads the same window a rebuild does — the deep
          // count, Gmail's estimate — and re-judges every row it finds, but
          // removes nothing: the stale row STAYS on the board and is reported
          // as updated. That is the whole difference the disposition makes,
          // and it is the one thing a visitor (or a spec) can see that tells
          // this apart from both a plain Sync and a rebuild.
          const nextApps = [...filed, ...s.apps];
          commit({ ...s, apps: nextApps, pool: [] });
          const partial = body.count === 100;
          return {
            ok: true,
            status: 200,
            body: {
              created: filed.length,
              // Every row already on the board was re-read and re-judged.
              updated: s.apps.length,
              scanned: partial ? PARTIAL_SCAN : REBUILD_SCAN,
              purged: 0,
              removed: [],
              applications: nextApps.length,
              needs_review: 0,
              stopped_by: partial ? "target" : "complete",
              result_size_estimate: ESTIMATE,
            },
          };
        }

        if (rebuild) {
          // "Rows you corrected by hand are kept" — the stale row is removed
          // only while untouched, exactly the promise the live rebuild makes.
          const stale = s.apps.find(
            (app) =>
              app.company === STALE_COMPANY && !s.touched.includes(app.id),
          );
          const removed = stale
            ? [{ id: stale.id, company: stale.company }]
            : [];
          const nextApps = [
            ...filed,
            ...s.apps.filter((app) => app.id !== stale?.id),
          ];
          commit({ ...s, apps: nextApps, pool: [] });
          const changed = filed.length > 0 || removed.length > 0;
          // A shallow scan that still had work to do stops at its message
          // limit — the second pass (via "continue the scan") finds nothing
          // left and is the one allowed to report completion.
          const partial = body.count === 100 && changed;
          return {
            ok: true,
            status: 200,
            body: {
              created: filed.length,
              updated: changed ? s.apps.length - removed.length : 0,
              scanned: partial ? PARTIAL_SCAN : REBUILD_SCAN,
              purged: removed.length,
              removed,
              applications: nextApps.length,
              needs_review: 0,
              stopped_by: partial ? "target" : "complete",
              result_size_estimate: ESTIMATE,
            },
          };
        }

        // Additive AND cursored — the plain `Sync` button. File the unsynced
        // pool at the top of the board (newest first, like the live list) and
        // never remove anything. Incremental scans never carry a size
        // estimate, matching the live backend.
        commit({ ...s, apps: [...filed, ...s.apps], pool: [] });
        return {
          ok: true,
          status: 200,
          body: {
            created: filed.length,
            updated: filed.length > 0 ? 3 : 0,
            scanned: ADDITIVE_SCAN,
            applications: s.apps.length + filed.length,
            stopped_by: "complete",
            result_size_estimate: null,
          },
        };
      },
      async restore(id) {
        await delay(300);
        const s = store.current;
        // The removed row is not in `apps` anymore; recover it from the
        // fixtures this mount started with (its edits died with the removal,
        // as a real dismissal's board row does — restore brings back the row,
        // not the session).
        const row = original.current.find((app) => app.id === id);
        if (!row) return false;
        // A restore is a CORRECTION — the visitor has said "keep this one" —
        // so the row joins `touched` and the next pass leaves it alone, the
        // same promise the rebuild dialog makes. Without that it was removed
        // again on every pass, and because re-removing it made the pass
        // "change" something, a shallow scan re-reported the same stopped-early
        // stop at PARTIAL_SCAN: the receipt never resolved, the scanned count
        // never moved past 100, and the visitor could continue forever.
        // Continuing after a restore now reads exactly like continuing
        // without one.
        commit({
          ...s,
          apps: [...s.apps, row],
          touched: s.touched.includes(id) ? s.touched : [...s.touched, id],
        });
        return true;
      },
    }),
    [commit],
  );

  const summary = summarize(snapshot.apps);
  /** The board as the change ledger reads it. `total` is deliberately not
   *  passed below: on this twin the store IS the whole account, so there is no
   *  slice to disclose. */
  const ledgerRows = useMemo(
    () => snapshot.apps.map(toChangeRow),
    [snapshot.apps],
  );
  // The signed-in page's own builder, not a copy of its format string — the
  // twin used to hand-roll this line WITHOUT the `weekly` fold, so the one
  // pref that is visible on a quiet board rendered on no testable surface.
  // The EMPTY board says something different, and the twin has to say it the
  // same way. Calling `buildSubtitle` here regardless of `empty` is what made
  // `?empty=1` render "17 filed · 14 open · 0 offers" above "nothing filed
  // yet" — the fixture zeroes the BODY and never zeroed the header, in the one
  // harness state whose whole purpose is to model an empty board (and which
  // the viewport-lock specs measure).
  //
  // `disconnected` matches `EMPTY_RAIL`'s `connected: false` in `DemoShell`,
  // so the header, the rail and the body all describe one account rather than
  // three.
  const subtitle = empty
    ? emptySubtitle({
        gmailState: "disconnected",
        scanCompleted: false,
        needsReview,
      })
    : buildSubtitle(summary, notifications.weekly);
  /** The harness knob wins where it is set; otherwise the preference does. */
  const slot = reviewSlot ?? reviewSlotFor(notifications);

  /** The held verdicts, dated against the SAME day the store is (`datedFor`,
   *  not a fresh clock read) — the queue prints `received_at` through
   *  `shortDate`, and a fixture resolved outside this render is the hydration
   *  mismatch `redate` exists to prevent. */
  const reviewItems = useMemo(
    () => (needsReview > 0 ? demoReviewQueueAsApi(needsReview, datedFor) : []),
    [needsReview, datedFor],
  );
  // Built exactly as the signed-in page builds it: the REAL `ReviewQueue`, the
  // board's own rows behind its assign-to-application picker, and null when
  // there is nothing held. Only the transport is absent — the row's classify
  // POST has no injection seam, so on this auth-free route it answers with the
  // API's error rather than filing anything. That is a knob-only surface
  // (`robots: noindex`, nothing links to it) and the geometry is the point.
  const queue =
    reviewItems.length > 0 ? (
      <ReviewQueue items={reviewItems} applications={snapshot.apps} />
    ) : null;

  return (
    <section className={locked ? LOCKED_PAGE_CLASS : "flex flex-col gap-6"}>
      {/* Exactly the signed-in composition: the sync surface is the page's
          top line — with the real change ledger as its chip, over the fixture
          store and under its own marker key, so a signed-in owner who visits
          /demo never has these rows folded into their own board's record. On
          the LOCKED twin (inside the shell) it also carries the title and the
          demo pill, because the shell's TopBar yields to it at `lg`+ exactly
          as it does for the signed-in page. One shared shape, which is what
          keeps this twin honest evidence for the real page.

          The pulse is the board's full-width band here exactly as it is on
          the signed-in dashboard. `needsReview` defaults to 0 deliberately,
          not as a stub: with nothing held there is no queue to point at, and
          the signal's non-zero branch deep-links to
          /dashboard#needs-classification — an auth-gated route that would
          dead-end an anonymous visitor. /demo/shell's `?review=N` harness
          knob is the one caller that overrides it, so that branch — a
          user-facing control that otherwise renders on NO testable surface —
          stays measurable, and it now also mounts the queue those N verdicts
          are counting (`lib/demo/reviewQueue.ts`), which is the subtree this
          twin was missing. The classifier's whole output, held and auto-filed
          alike, is a different fixture (DEMO_REVIEW_QUEUE) shown by the
          DecisionTrace on the landing. Below `lg` the band yields to
          the cards' own tags — the phone answer the old full-width strip
          needed a `max-sm:order-last` workaround to approximate. */}
      <SyncBar
        subtitle={subtitle}
        gmail={DEMO_GMAIL}
        transport={syncTransport}
        title={locked ? "Applications" : undefined}
        // The session edge, and only one of them: the pill is the twin's
        // honest default (no session to end), `sessionEdge` swaps in the
        // signed-in page's own arrangement — nothing row-level, `Sign out`
        // folded into the `⋯` menu — so the row that #172 is about can be
        // measured at all. Never both: two session edges in one row would
        // measure a shape no surface renders.
        trailing={locked && !sessionEdge ? <DemoFixturePill /> : undefined}
        signedIn={sessionEdge}
        since={
          <SinceLastLook
            rows={ledgerRows}
            scope={LAST_LOOK_DEMO_SCOPE}
            storageKey={LAST_LOOK_DEMO_KEY}
          />
        }
      >
        <AddApplicationForm mode="demo" compact />
      </SyncBar>
      {/* The queue reaches the board through the same two slots the signed-in
          page uses, and the same either/or shape: on the live dashboard the
          "Needs review alerts" pref decides whether held mail interrupts the
          rows or waits under them, and both placements live INSIDE the
          worklist's scroll context so a long queue can never starve it. */}
      {empty ? (
        // The signed-in page's own empty body, mounted rather than restated:
        // `gmailState="disconnected"` is the state a brand-new account is in,
        // and it is the one the rail agrees with under this knob (see
        // `DemoShell`) — an empty board under a rail claiming a live mailbox
        // would be a shape no real account can be in, and measuring geometry
        // on an impossible state is how a twin starts lying. The held queue
        // rides in the same slot the live page gives it, so `?empty=1&review=N`
        // measures the tall case too.
        <EmptyBoardBody gmailState="disconnected" review={queue} mode="demo" />
      ) : (
        <PipelineBoard
          variant={locked ? "locked" : "flow"}
          applications={snapshot.apps}
          pulse={{ needsReview }}
          transport={boardTransport}
          beforeList={slot === "before" ? queue : null}
          afterList={slot === "after" ? queue : null}
        />
      )}
    </section>
  );
}
