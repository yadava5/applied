"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { todayISO } from "@/lib/dashboard/age";
import { buildSubtitle } from "@/lib/dashboard/boardPrefs";
import { isApplicationStatus } from "@/lib/dashboard/status";
import { summarize, type Application } from "@/lib/dashboard/summary";
import type { BoardTransport } from "@/lib/dashboard/transport";
import { demoDetailBody } from "@/lib/demo/demoDetail";
import { OFFER_EMAIL } from "./verdictEmailData";
import { showcaseApplications, showcasePendingVerdict, OFFER_SIGNAL } from "./showcase";
import { VERDICT_SETTLE_MS, VERDICT_TRAVEL } from "./tempo";

/**
 * How long after a visitor's own gesture a card load still belongs to that
 * gesture. The pane's load is scheduled inside the commit the click produced
 * and runs on the next macrotask, so this only has to span click → passive
 * flush → `setTimeout(0)` → the transport's own await — far less than this,
 * even on a first paint under load. It is also far short of the earliest the
 * page can seed: the reader has to scroll 0.18 of the act's runway (~512px)
 * between the row committing and the pane's mark, and the seed then waits out
 * whatever is left of the row's travel (`landedAtRef`) — so a gesture that
 * opened nothing — a drag, the stage lens — has expired long before the
 * seed's load arrives. That margin used to be `VERDICT_BREATH_MS`, a fixed
 * 1800ms; it is distance now, and the fastest plausible flick still spends
 * ~340ms crossing it.
 *
 * The margin in the first paragraph is REASONED FROM THE SCHEDULING, not
 * measured: no run has timed a click to its load on this page, at either
 * viewport or under any load. Treat 400 as a bound nobody has instrumented.
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
export function MarketingBoard({ verdict, docked, onVisitorOpen }: {
  /**
   * The merged landing's window act (see WindowAct), as two booleans the
   * reader's SCROLL POSITION defines. `undefined` — every other caller — is
   * the resting board, exactly as before.
   *
   *   `verdict`  the offer has landed: the row is committed to `offered` and
   *              the board's own layout animation carries it to the offered
   *              group, at the act's `VERDICT_TRAVEL` tempo;
   *   `docked`   the detail opens on that row (the board's `openDetailId`
   *              seed — docked only, no focus theft), which is the
   *              composition the owner approved: worklist beside the open
   *              pane, trail and gate meter shown. The seed waits for the row
   *              to have LANDED, not merely for its status to have flipped —
   *              see `landedAtRef`.
   *
   * BOTH REVERSE. They used to be an advancing beat index whose mutations
   * fired once and persisted ("a verdict does not un-happen"), which was a
   * considered call and which the owner has now rejected twice: scrolling
   * back up replayed the captions over a board that stayed settled with the
   * pane open, and the pane in particular read as stuck. State is a function
   * of position now, so the act plays in both directions and the move can be
   * replayed by anyone who missed it.
   *
   * What does NOT reverse is the visitor's own hand. A row they moved
   * themselves stands the page down permanently (`pageRow.standDown`), and a
   * card they opened themselves stands the seed down for the visit
   * (`tookOverRef`) — the same one-way rules as before, for the same reason:
   * the page is narrating, and a visitor who has started using has stopped
   * being narrated to.
   */
  verdict?: boolean;
  /** The detail pane is docked open on the moved row. See `verdict`. */
  docked?: boolean;
  /**
   * The visitor opened a card themselves (a click, Enter on a row, or ↑/↓
   * traversal once a pane is up) — as opposed to the open the page seeds.
   * Fired on every such open, and it is how the camera learns to let go (see
   * LandingBoard): the framed window crops the board, so a pane the page did
   * not open would otherwise show none of its own chrome.
   *
   * The signal is `transport.detail(id)`, which ApplicationDetail calls for
   * every card it loads — a prop this component already owns. Which of the
   * two hands that call belongs to is decided by CAUSE, not by identity (see
   * `detail` below). Clicking the row the PAGE opened is one of these opens
   * like any other — `detail` says how a re-open of that one row is made
   * visible at all. Nothing here reads the board's DOM, and nothing under
   * components/dashboard changes.
   */
  onVisitorOpen?: () => void;
}) {
  const choreographed = verdict !== undefined;
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

  // All four of these are read INSIDE `transport.detail` and must never appear
  // in the transport's dep list: a fresh transport re-triggers the detail
  // sheet's load effect on every board change (see `appsRef` above, same
  // reason).
  //
  // `pendingSeedRef` is the page's claim on ONE card load — armed when the seed
  // is handed to the board (the dock effect below), consumed by the load it
  // causes. It is armed once per ENTRY into the docked state now, not once per
  // visit, because the act reverses — and it is still armed INSIDE the seed's
  // own timer, so a scrub back across the mark cancels the timer and leaves
  // nothing armed for a later load to spend.
  // `gestureAtRef` is when the visitor last touched the board in a way that can
  // open a card, recorded at the input event itself.
  // `tookOverRef` is the one-way latch: the visitor has opened a card, so the
  // page has stopped driving and never starts again this visit.
  const pendingSeedRef = useRef<number | undefined>(undefined);
  const tookOverRef = useRef(false);
  /**
   * When the moved row will have finished TRAVELLING — commit time plus the
   * glide plus its settle — set in the same timer that commits the move,
   * before the commit itself. The dock seed waits this out: gating on the
   * status value alone docked the pane ~1.4s before the row it names entered
   * the frame (measured: −227px relative to the stage clip at +40ms after
   * the commit), which made the scene's caption false while the move it
   * narrates was still happening. Starts at 0, not ∞: a row the VISITOR
   * dragged to `offered` has no travel of the page's to wait for.
   *
   * IT WAS NEVER ACTUALLY READ. The seed effect below deferred by a flat 0ms
   * while this comment claimed the remainder of the travel, so the measured
   * defect it describes was still shipping. The wait is real now — the timer
   * takes `landedAtRef − now` — which matters more than it did: the scroll
   * marks put ~512px between the commit and the dock, and a reader crossing
   * both in one flick would otherwise dock the pane on a row still in the air.
   */
  const landedAtRef = useRef(0);
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
        //    row it lands on. That is the belt to the ordering's braces.
        //
        // The belt and the arm's position MUTUALLY MASK: with the belt in place
        // the arm could sit anywhere and a beat-1 click would still be read as
        // the visitor's; with the arm inside the seed's own timer the belt
        // never has to catch anything. So neither is observable on its own, and
        // deleting either ALONE changes no measurement — which is exactly what
        // makes them look like dead code and exactly why they are not. Only the
        // COMPOUND mutant shows it: the arm moved back into the effect body AND
        // `OPEN_GESTURE_MS` at 0, which put a beat-1 click red at roughly four
        // runs in ten. Restore the arm into the timer with the belt still at 0
        // and it is green again.
        //
        // The else branch is also where the visitor TAKES OVER, and the latch
        // it sets is one-way: AFTER TAKEOVER THERE IS NO CLAIM AND NO SEED.
        // Beat 2 stands down for the rest of the visit (below), so nothing
        // arms, nothing is handed to the board, and a visitor who opens a card
        // and then presses Escape never has a pane pushed on them at zone 2.
        // It also retires the one case the belt used to have to cover on its
        // own: PipelineBoard standing its seed down over a pane the visitor
        // already has open, which left a claim armed that no load ever came
        // for. There is no seed to stand down from now.
        //
        // That stand-down (PipelineBoard.tsx, the `detailApp !== null` bail)
        // and LandingBoard's camera latch, which never re-engages once
        // released, remain the second and third walls. They are also why this
        // latch is invisible to every assertion that predates it. Its gates
        // (the close-control pair in the landing spec, and the race workflow
        // that hammered them unretried) RETIRED with the scrubbed act: no
        // mount arms a seed any more, so the branch below is unreachable
        // until some mount passes `verdict` again — see tempo.ts for what
        // must be restored alongside it if that day comes.
        const byGesture = performance.now() - gestureAtRef.current < OPEN_GESTURE_MS;
        gestureAtRef.current = Number.NEGATIVE_INFINITY; // one open per gesture
        if (!byGesture && pendingSeedRef.current === id) {
          pendingSeedRef.current = undefined;
          // The page's open is the last hand to hold this row's OBJECT, and
          // that is what made re-opening it invisible: the board keeps the very
          // object it was handed (`setDetailApp(app)`), the row hands back the
          // same one on a click, and `useState` bails on an identical
          // reference — no commit, no pane load, no `detail` call, so the one
          // gesture that most obviously deserves the frame back was the one
          // gesture nothing could see. Escape was again the only way out of a
          // pane whose × the crop holds ~97px above the stage at beat 2.
          //
          // So the row gets a fresh object, values copied, handed over AFTER
          // the board has captured the old one. Nothing else changes: the copy
          // renders identically, the board's height is untouched (so beat 2's
          // foot hold does not move), and the next open is a real state
          // change that loads the card and arrives back here inside the
          // visitor's gesture window — classified theirs by the same rule as
          // every other open, with no new signal invented for it.
          //
          // The pane keeps rendering from the pre-copy snapshot until then.
          // That is the product's own behaviour, not something this introduces:
          // `detailApp` is only ever written on open and close, so it never
          // re-syncs with the row list here or in the app. The copy carries the
          // same values, so there is nothing to be stale about.
          //
          // Once per seeded open, and only for the seeded row: a visitor's
          // repeat click on a card they opened themselves is correctly a no-op
          // (the card is already on screen) and the camera has already let go.
          commit((rows) => rows.map((row) => (row.id === id ? { ...row } : row)));
        } else {
          // Set BEFORE the camera is told, so the two walls fall in the order
          // they are reasoned about: the page stops driving, then the frame
          // goes back.
          tookOverRef.current = true;
          visitorOpenRef.current?.();
        }
        const app = appsRef.current.find((row) => row.id === id);
        return app ? { ok: true, body: demoDetailBody(app) } : { ok: false, body: {} };
      },
    }),
    [commit],
  );

  // --- The window act, as a function of position (choreographed mounts only) -

  /**
   * The page's claim on the verdict row.
   *
   *   `held`      the page currently has the row in `offered`;
   *   `restore`   what the row looked like before, so the way back up is
   *               exact rather than a second set of literals to keep in sync
   *               with `showcasePendingVerdict`;
   *   `standDown` the row is not where the page left it, so the VISITOR moved
   *               it — one-way, and the page never touches this row again in
   *               either direction.
   *
   * Held in one ref rather than three because they are only ever read and
   * written together, inside the timer that commits.
   */
  const pageRow = useRef<{
    held: boolean;
    restore: Pick<Application, "status" | "notes"> | null;
    standDown: boolean;
  }>({ held: false, restore: null, standDown: false });

  /**
   * The offer lands — and un-lands. Committed through the same `commit` a
   * drag uses, so the layout animation that carries the row to the offered
   * group is the product's own; nothing marketing-specific moves it, and the
   * act's `travel` prop is what sets its tempo.
   *
   * There is no breath here any more. `VERDICT_BREATH_MS` was 1800ms between
   * the scene starting and the row committing, so that the receipt could
   * announce first — and it ran on its own clock, which is how the move came
   * to happen while nobody was looking. The breath is 0.10 of the runway now
   * (tempo.ts): the reader passes through it whatever their speed, and the
   * row commits exactly where they are.
   */
  useEffect(() => {
    if (verdict === undefined) return;
    const claim = pageRow.current;
    if (claim.standDown || claim.held === verdict) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Deferred off the effect body — the house rule every board effect
    // follows (react-hooks/set-state-in-effect). A macrotask, not a beat:
    // every check is re-taken inside it, so a reader scrubbing back and forth
    // across the mark cancels the pending commit rather than racing it.
    const timer = window.setTimeout(() => {
      const row = appsRef.current.find((a) => a.company === OFFER_EMAIL.company);
      if (!row) return;
      // The visitor's hand wins, permanently: the row is not where the page
      // left it, so there is nothing of the page's to move or to put back.
      if (row.status !== (claim.held ? "offered" : "applied")) {
        claim.standDown = true;
        return;
      }
      const next: Pick<Application, "status" | "notes"> = verdict
        ? { status: "offered", notes: OFFER_SIGNAL }
        : (claim.restore ?? { status: "applied", notes: row.notes });
      if (verdict) claim.restore = { status: row.status, notes: row.notes };
      claim.held = verdict;
      // Declared BEFORE the commit, so the dock effect the commit triggers
      // can never read a stale 0 and seed a pane onto a row still mid-glide.
      // Zero on the way back: the pane is already withdrawn by then, and a
      // row travelling home is not a row anything is waiting to open.
      landedAtRef.current =
        verdict && !reduce
          ? performance.now() + VERDICT_TRAVEL.duration * 1000 + VERDICT_SETTLE_MS
          : 0;
      commit((rows) => rows.map((a) => (a.id === row.id ? { ...a, ...next } : a)));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [verdict, commit]);

  /** The mail behind the row — and its withdrawal. Waits for the offer to
   *  have actually LANDED — the status committed AND the glide finished
   *  (`landedAtRef`) — because the pane must never open on the pre-move
   *  snapshot, and "the row opens on the mail that moved it" is false while
   *  the row is still travelling. Then it hands the id to the board's seeded
   *  open — docked-only, focus untouched. Skipped entirely once the visitor
   *  has taken over, the same rule the verdict follows for a row they moved
   *  themselves.
   *
   *  When `docked` goes false the seed is WITHDRAWN, which closes the pane
   *  the page opened (and only that one — see PipelineBoard's seed effect).
   *  That is the whole of "once the right pane opens with scroll it never
   *  closes". */
  const [openDetailId, setOpenDetailId] = useState<number | undefined>(undefined);
  useEffect(() => {
    if (!choreographed) return;
    if (!docked) {
      if (openDetailId === undefined) return;
      const withdraw = window.setTimeout(() => setOpenDetailId(undefined), 0);
      return () => window.clearTimeout(withdraw);
    }
    // `tookOverRef` is read, never a dep: it is a latch, not a signal, and a
    // re-render is not what should notice it. This read is the cheap one — a
    // visitor who took over earlier never even schedules a timer. The
    // authoritative read is inside the timer.
    if (openDetailId !== undefined || tookOverRef.current) return;
    const row = apps.find((a) => a.company === OFFER_EMAIL.company);
    if (!row || row.status !== "offered") return;
    // Deferred off the effect body — the house rule every board effect
    // follows — and by however long the row still has left in the air: the
    // delay is the remainder of the travel, zero once it has landed (and zero
    // for a row the visitor moved, whose landing time never left 0). The
    // cleanup cancels it like any other seed.
    const rowId = row.id;
    const id = window.setTimeout(() => {
      // The authoritative takeover read, and it has to be here rather than
      // only in the effect body: the visitor's own click at beat 1 is what
      // scrolls the act into this zone (their pane's focus() moves the
      // viewport), so the effect body can run BEFORE their load has been
      // classified. By the time this timer fires it has — the same ordering
      // that lets the claim be armed here at all guarantees the visitor's load
      // was scheduled first, so the latch is already set. Both reads are
      // wanted; neither replaces the other.
      if (tookOverRef.current) return;
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
    }, Math.max(0, landedAtRef.current - performance.now()));
    return () => window.clearTimeout(id);
  }, [docked, choreographed, apps, openDetailId]);

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
        // The act's tempo, choreographed mounts only: the one move the page
        // performs has to be watchable by a visitor who does not know which
        // row is about to travel. Resting mounts keep the product's own 220ms.
        travel={choreographed ? VERDICT_TRAVEL.duration : undefined}
        // A visitor's own open still takes focus; what it must not take is
        // the page. The pane lives inside LandingBoard's camera crop on a
        // pinned runway, and the browser's reveal-the-focused-element scroll
        // moved the document 165px (measured, 1024×768, beat-0 row click) —
        // which IS the act's clock, so the choreography moved with it. The
        // camera's release is the frame's own way of revealing the pane.
        focusScrollOnOpen={false}
      />
    </div>
  );
}
