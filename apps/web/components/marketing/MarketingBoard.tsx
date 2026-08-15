"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { todayISO } from "@/lib/dashboard/age";
import { buildSubtitle } from "@/lib/dashboard/boardPrefs";
import { isApplicationStatus } from "@/lib/dashboard/status";
import { summarize, type Application } from "@/lib/dashboard/summary";
import type { BoardTransport } from "@/lib/dashboard/transport";
import { demoDetailBody } from "@/lib/demo/demoDetail";
import { showcaseApplications } from "./showcase";

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
export function MarketingBoard() {
  // One clock read per mount, resolved in render (never module load) — the
  // same hydration rule every fixture family follows. This component only
  // ever mounts client-side (see LandingBoard), so the day is the visitor's.
  const [apps, setApps] = useState<Application[]>(() => showcaseApplications(todayISO()));
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
      />
    </div>
  );
}
