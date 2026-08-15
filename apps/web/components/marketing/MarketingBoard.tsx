"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { todayISO } from "@/lib/dashboard/age";
import { buildSubtitle } from "@/lib/dashboard/boardPrefs";
import { isApplicationStatus } from "@/lib/dashboard/status";
import { summarize, type Application } from "@/lib/dashboard/summary";
import type { BoardTransport } from "@/lib/dashboard/transport";
import { demoDetailBody } from "@/lib/demo/demoDetail";
import { VERDICT_EMAIL } from "./verdictEmailData";
import { showcaseApplications, showcasePendingVerdict, VERDICT_SIGNAL } from "./showcase";

/**
 * How long after a visitor's own gesture a card load still belongs to that
 * gesture. The pane's load is scheduled inside the commit the click produced
 * and runs on the next macrotask, so this only has to span click → passive
 * flush → `setTimeout(0)` → the transport's own await — far less than this,
 * even on a first paint under load. It is also far short of the earliest the
 * page can seed (beat 1's 750ms breath has to elapse before the row reads
 * `rejected`), so a gesture that opened nothing — a drag, the stage lens —
 * has expired long before the seed's load arrives.
 */
const OPEN_GESTURE_MS = 400;

/** The keys that open or traverse a card: Enter and Space activate a row's
 *  opener, ↑/↓ load the next card while a pane is up. Anything else the board
 *  answers (typing in a field, Escape) opens nothing and is not the wheel. */
const OPENING_KEYS = new Set(["Enter", " ", "ArrowUp", "ArrowDown"]);

/**
 * The board as a marketing hero: the OUTCOME surface, not the toolbar.
 *
 * The first cut of the candidates mounted `DemoDashboard`, and the critique
 * was right on both counts: the toolbar row (Sync, `+`, `⋯`, search, the
 * "No earlier visit." session pill) is the tool's controls leaking onto a
 * sales page, and a marketing hero should show what the product DID. So this
 * mount is the board itself — the real `PipelineBoard`: rows, stage spine,
 * pulse band, drag, the detail sheet — over the showcase fixture, with one
 * line of header: the product's own summary sentence and the honesty pill.
 * The one control kept is the board's own stage lens; it filters what the
 * product produced, which is outcome, not operation.
 *
 * The transport is the same in-memory shape `DemoDashboard` uses (drag moves
 * a row, the sheet reads a synthetic trail) minus the sync machinery this
 * mount no longer shows. It never touches the network — the unit gate
 * (`landing-variants.test.mjs`) walks the import graph and holds that line.
 */
export function MarketingBoard({ beat, onVisitorOpen }: {
  /**
   * The merged landing's window act (see WindowAct): which scene of the
   * choreography the visitor's scroll has reached. `undefined` — every other
   * caller — is the resting board, exactly as before. With a beat:
   *
   *   0  the board one verdict early: Larkspur still in `applied`, 19 days
   *      quiet (the pulse's amber share and the age tag foreshadow it);
   *   1+ the verdict lands — the row is committed to `rejected` and the
   *      board's own layout animation carries it to the closed group;
   *   2+ the detail opens on that row (the board's `openDetailId` seed —
   *      docked only, no focus theft), which is the composition the owner
   *      approved: worklist beside the open pane, trail and gate meter shown.
   *
   * Beats only ever ADVANCE state (a verdict does not un-happen when the
   * visitor scrolls back up), each fires once, and none of them touches a
   * row the visitor has meanwhile moved themselves.
   */
  beat?: number;
  /**
   * The visitor opened a card themselves (a click, Enter on a row, or ↑/↓
   * traversal once a pane is up) — as opposed to the beat-2 open the page
   * seeds. Fired on every such open, and it is how the camera learns to let
   * go (see LandingBoard): the framed window crops the board, so a pane the
   * page did not open would otherwise show none of its own chrome.
   *
   * The signal is `transport.detail(id)`, which ApplicationDetail calls for
   * every card it loads — a prop this component already owns. Which of the
   * two hands that call belongs to is decided by CAUSE, not by identity (see
   * `detail` below). Nothing here reads the board's DOM, and nothing under
   * components/dashboard changes.
   */
  onVisitorOpen?: () => void;
}) {
  const choreographed = beat !== undefined;
  // One clock read per mount, resolved in render (never module load) — the
  // same hydration rule every fixture family follows. This component only
  // ever mounts client-side (see LandingBoard), so the day is the visitor's.
  const [apps, setApps] = useState<Application[]>(() =>
    choreographed ? showcasePendingVerdict(todayISO()) : showcaseApplications(todayISO()),
  );
  // Rows in a ref, mirrored into state — DemoDashboard's pattern, for the
  // same reason: the transport must stay referentially stable, because a
  // fresh transport each render re-triggers the detail sheet's load effect
  // on every board change.
  const appsRef = useRef(apps);
  const commit = useCallback((next: (rows: Application[]) => Application[]) => {
    appsRef.current = next(appsRef.current);
    setApps(appsRef.current);
  }, []);

  // All three of these are read INSIDE `transport.detail` and must never appear
  // in the transport's dep list: a fresh transport re-triggers the detail
  // sheet's load effect on every board change (see `appsRef` above, same
  // reason).
  //
  // `pendingSeedRef` is the page's claim on ONE card load — armed when the seed
  // is handed to the board (beat 2 below), consumed by the load it causes.
  // `gestureAtRef` is when the visitor last touched the board in a way that can
  // open a card, recorded at the input event itself.
  const pendingSeedRef = useRef<number | undefined>(undefined);
  // −∞, not 0: `performance.now()` counts from navigation start, so a zero
  // here would read as "a gesture 300ms ago" on a page that has just loaded
  // and hand the camera back before the visitor has touched anything.
  const gestureAtRef = useRef(Number.NEGATIVE_INFINITY);
  const visitorOpenRef = useRef(onVisitorOpen);
  useEffect(() => {
    visitorOpenRef.current = onVisitorOpen;
  }, [onVisitorOpen]);

  /** The visitor's hand, recorded synchronously in the capture phase — before
   *  the click's own commit, and so before anything that commit schedules. */
  const noteGesture = () => {
    gestureAtRef.current = performance.now();
  };

  const transport = useMemo<BoardTransport>(
    () => ({
      async changeStatus(id, status) {
        // Same enum guard as the demo transport, same reason: the wire
        // contract is an enum, and a control that drifts should say so.
        if (!isApplicationStatus(status)) {
          return { ok: false, detail: `“${status}” is not a status the API accepts` };
        }
        commit((rows) => rows.map((app) => (app.id === id ? { ...app, status } : app)));
        return { ok: true, status };
      },
      async setDeadline(id, dueAt) {
        commit((rows) =>
          rows.map((app) =>
            app.id === id
              ? { ...app, due_at: dueAt, due_source: dueAt === null ? null : ("user" as const) }
              : app,
          ),
        );
        return { ok: true };
      },
      async setRole(id, role) {
        commit((rows) =>
          rows.map((app) =>
            app.id === id
              ? {
                  ...app,
                  position: role ?? "",
                  position_source: role === null ? null : ("user" as const),
                }
              : app,
          ),
        );
        return { ok: true };
      },
      async dismiss(id) {
        commit((rows) => rows.filter((app) => app.id !== id));
        return { ok: true };
      },
      async deleteRow(id) {
        commit((rows) => rows.filter((app) => app.id !== id));
        return { ok: true };
      },
      async detail(id) {
        // Every card the pane loads passes through here, and exactly one of
        // them is the page's. Which one is decided by CAUSE, not by identity:
        //
        //  · the page's claim is armed in the same task that hands the seed to
        //    the board and is spent on the single load that seed causes, so a
        //    SECOND open of the seeded row — Escape, then click it again — is
        //    the visitor's, where the old id comparison called it the page's
        //    for the rest of the visit;
        //  · a load that follows the visitor's own gesture is theirs whatever
        //    row it lands on. That is the belt to the ordering's braces, and it
        //    covers the one case ordering cannot: PipelineBoard stands its seed
        //    down over a pane the visitor already has open, which leaves a
        //    claim armed that no load will ever come for.
        const byGesture = performance.now() - gestureAtRef.current < OPEN_GESTURE_MS;
        gestureAtRef.current = Number.NEGATIVE_INFINITY; // one open per gesture
        if (!byGesture && pendingSeedRef.current === id) {
          pendingSeedRef.current = undefined;
        } else {
          visitorOpenRef.current?.();
        }
        const app = appsRef.current.find((row) => row.id === id);
        return app ? { ok: true, body: demoDetailBody(app) } : { ok: false, body: {} };
      },
    }),
    [commit],
  );

  // --- The window act's beats (choreographed mounts only) -------------------

  /** Beat 1: the verdict lands. Committed through the same `commit` a drag
   *  uses, so the layout animation that carries the row to the closed group
   *  is the product's own — nothing marketing-specific moves it. Fired once;
   *  skipped entirely if the visitor already moved the row themselves. The
   *  750ms breath exists so the camera's pan (LandingBoard) settles before
   *  the row travels — one event, read in sequence; reduced motion takes the
   *  state change immediately. */
  const moved = useRef(false);
  const moveTimer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (moveTimer.current !== null) window.clearTimeout(moveTimer.current);
    },
    [],
  );
  useEffect(() => {
    if (!choreographed || (beat ?? 0) < 1 || moved.current) return;
    moved.current = true;
    const row = appsRef.current.find((a) => a.company === VERDICT_EMAIL.company);
    if (!row || row.status !== "applied") return; // the visitor got there first
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const rowId = row.id;
    moveTimer.current = window.setTimeout(
      () => {
        commit((rows) =>
          rows.map((a) =>
            a.id === rowId && a.status === "applied"
              ? { ...a, status: "rejected", notes: VERDICT_SIGNAL }
              : a,
          ),
        );
      },
      reduce ? 0 : 750,
    );
  }, [beat, choreographed, commit]);

  /** Beat 2: the mail behind the row. Waits for the verdict to have actually
   *  landed (the pane must never open on the pre-move snapshot), then hands
   *  the id to the board's seeded open — docked-only, focus untouched. */
  const [openDetailId, setOpenDetailId] = useState<number | undefined>(undefined);
  useEffect(() => {
    if (!choreographed || (beat ?? 0) < 2 || openDetailId !== undefined) return;
    const row = apps.find((a) => a.company === VERDICT_EMAIL.company);
    if (!row || row.status !== "rejected") return;
    // Deferred off the effect body — the house rule every board effect follows.
    const rowId = row.id;
    const id = window.setTimeout(() => {
      // The claim is armed HERE, in the same task that hands the seed to the
      // board — not in the effect body, which is where it raced and lost.
      //
      // A visitor who clicks the moved row at beat 1 gets a pane whose load
      // timer was scheduled from that click's own commit; the focus() that
      // pane performs scrolls the viewport, which is what carries the act into
      // this zone and runs this effect at all. So the visitor's timer is always
      // scheduled first, and two 0ms timers fire in the order they were set:
      // their load runs while the claim is still unarmed, every time. Armed in
      // the effect body instead, the arm skipped the queue and beat the load
      // about four runs in ten — measured, both at 1024×768 and 1024×600, with
      // the camera left un-released and the pane's × cropped out of frame.
      //
      // It also means a seed this effect's cleanup cancels leaves no claim
      // behind for some later load to spend.
      pendingSeedRef.current = rowId;
      setOpenDetailId(rowId);
    }, 0);
    return () => window.clearTimeout(id);
  }, [beat, choreographed, apps, openDetailId]);

  return (
    <div
      className="flex h-full flex-col gap-4"
      // The wheel, watched where it is actually turned. Capture-phase
      // listeners on the wrapper this component already renders — no new
      // element, so the act's measured geometry is untouched — and they fire
      // during the browser's own dispatch, ahead of every effect, timer and
      // observer the gesture goes on to set in motion.
      onPointerDownCapture={(event) => {
        if (event.button === 0) noteGesture();
      }}
      onKeyDownCapture={(event) => {
        if (OPENING_KEYS.has(event.key)) noteGesture();
      }}
    >
      {/* One header line: what the board says about itself, and whose it is. */}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <p className="text-sm text-muted">{buildSubtitle(summarize(apps), false)}</p>
        {/* Prose, so it is set in the product's voice — mono is reserved for
            machine values (a path, a hash, a figure read out of source). */}
        <p className="label-caps inline-flex items-center gap-2 text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-live" aria-hidden />
          simulated account · nothing is read
        </p>
      </div>
      <PipelineBoard
        variant="flow"
        applications={apps}
        transport={transport}
        pulse={{ needsReview: 0 }}
        search={false}
        openDetailId={openDetailId}
      />
    </div>
  );
}
