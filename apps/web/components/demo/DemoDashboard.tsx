"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import { AddApplicationForm } from "@/components/applications/AddApplicationForm";
import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { PipelinePulse } from "@/components/dashboard/PipelinePulse";
import { SyncBar, type SyncGmailState } from "@/components/dashboard/SyncBar";
import { todayISO } from "@/lib/dashboard/age";
import { summarize, type Application } from "@/lib/dashboard/summary";
import type { BoardTransport, SyncTransport } from "@/lib/dashboard/transport";
import { demoApplicationsAsApi, demoUnsyncedAsApi } from "@/lib/demo/asApplications";
import { demoDetailBody } from "@/lib/demo/demoDetail";

/**
 * The demo dashboard: the REAL components — SyncBar, PipelineBoard, the cards,
 * the detail sheet — running their real state machines over an in-memory
 * fixture store instead of the network. Drag a card and it moves; open a card
 * and its (synthetic) mail trail renders; press Sync and the two not-yet-synced
 * fixture rows are filed onto the board; run a Rebuild and a stale row is
 * removed, named on the receipt, and restorable from it. Nothing here is a
 * mock of the UI — only the transport is simulated, which is exactly what the
 * "demo is the real thing" contract asks for, and what lets the e2e suite
 * execute the session-gated surfaces.
 *
 * Simulation semantics mirror the product's promises:
 *   - a rebuild removes only the stale AUTO row (Fernworks) and only while the
 *     visitor has not corrected it by hand — "rows you corrected are kept";
 *   - every receipt count is derived from what the store actually did, never
 *     invented after the fact;
 *   - restore puts the removed row back on the board, not just off the list.
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

export function DemoDashboard() {
  // ONE clock read for the whole mount: the fixture dates are relative, so
  // every row in this store — board and unsynced pool alike — is aged against
  // the same "today" the board renders with. Resolving them here rather than
  // at module load is what keeps a long-lived server's HTML and the browser's
  // hydration agreeing on what "16 days ago" means.
  const [snapshot, setSnapshot] = useState<DemoBoard>(() => {
    const today = todayISO();
    return { apps: demoApplicationsAsApi(today), pool: demoUnsyncedAsApi(today), touched: [] };
  });
  /** The pristine fixtures, kept for `restore` — the rows this board began
   *  with, before any drag, dismissal or rebuild touched them. */
  const original = useRef<Application[]>([...snapshot.apps, ...snapshot.pool]);
  const store = useRef(snapshot);
  const commit = useCallback((next: DemoBoard) => {
    store.current = next;
    setSnapshot(next);
  }, []);

  const boardTransport = useMemo<BoardTransport>(
    () => ({
      async changeStatus(id, status) {
        await delay(300);
        const s = store.current;
        commit({
          ...s,
          apps: s.apps.map((app) => (app.id === id ? { ...app, status } : app)),
          touched: s.touched.includes(id) ? s.touched : [...s.touched, id],
        });
        return { ok: true, status };
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
        return app ? { ok: true, body: demoDetailBody(app) } : { ok: false, body: {} };
      },
    }),
    [commit],
  );

  const syncTransport = useMemo<SyncTransport>(
    () => ({
      mode: "simulated",
      async sync(body) {
        const rebuild = body.mode === "rebuild";
        // Long enough that the running state — and the rebuild's count-up
        // clock — actually renders and can be asserted; short enough that a
        // visitor never waits meaningfully.
        await delay(rebuild ? 2400 : 1200);
        const s = store.current;
        const filed = s.pool;

        if (rebuild) {
          // "Rows you corrected by hand are kept" — the stale row is removed
          // only while untouched, exactly the promise the live rebuild makes.
          const stale = s.apps.find(
            (app) => app.company === STALE_COMPANY && !s.touched.includes(app.id),
          );
          const removed = stale ? [{ id: stale.id, company: stale.company }] : [];
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

        // Additive: file the unsynced pool at the top of the board (newest
        // first, like the live list) and never remove anything. Incremental
        // scans never carry a size estimate, matching the live backend.
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
        commit({ ...s, apps: [...s.apps, row] });
        return true;
      },
    }),
    [commit],
  );

  const summary = summarize(snapshot.apps);
  const subtitle = `${summary.total} filed · ${summary.inMotion} in motion · ${summary.offers} offer${
    summary.offers === 1 ? "" : "s"
  }`;

  return (
    <section className="space-y-6">
      <SyncBar subtitle={subtitle} gmail={DEMO_GMAIL} transport={syncTransport}>
        <AddApplicationForm mode="demo" />
      </SyncBar>
      {/* Same strip as the signed-in dashboard, over the fixture store.
          `total` is the store's own length because on this board it IS the
          whole account — the strip's scope note ("newest N of M") therefore
          never fires here by construction, not by omission; the live
          dashboard is where a bounded page makes it real.
          `needsReview` is 0 deliberately, not a stub: /demo mounts no review
          queue for a held verdict to point at, and the cell's non-zero branch
          deep-links to /dashboard#needs-classification — an auth-gated route
          that would dead-end an anonymous visitor. The fixture queue
          (DEMO_REVIEW_QUEUE) does hold one sub-gate message; the DecisionTrace
          lower down this page is where it is shown and explained. */}
      <PipelinePulse applications={snapshot.apps} total={snapshot.apps.length} needsReview={0} />
      <PipelineBoard applications={snapshot.apps} transport={boardTransport} />
    </section>
  );
}
