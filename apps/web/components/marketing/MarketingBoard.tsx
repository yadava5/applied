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
export function MarketingBoard({ beat }: {
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
    const id = window.setTimeout(() => setOpenDetailId(rowId), 0);
    return () => window.clearTimeout(id);
  }, [beat, choreographed, apps, openDetailId]);

  return (
    <div className="flex h-full flex-col gap-4">
      {/* One header line: what the board says about itself, and whose it is. */}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <p className="text-sm text-muted">{buildSubtitle(summarize(apps), false)}</p>
        <p className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-muted">
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
