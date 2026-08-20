"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { ReviewQueue } from "@/components/dashboard/ReviewQueue";
import { SyncBar, type SyncGmailState } from "@/components/dashboard/SyncBar";
import { showcaseApplications } from "@/components/marketing/showcase";
import { todayISO } from "@/lib/dashboard/age";
import { buildSubtitle } from "@/lib/dashboard/boardPrefs";
import { isApplicationStatus } from "@/lib/dashboard/status";
import { summarize, type Application } from "@/lib/dashboard/summary";
import type { BoardTransport, SyncTransport } from "@/lib/dashboard/transport";
import { demoDetailBody } from "@/lib/demo/demoDetail";

import { cedarReviewItem } from "./heldCast";

/**
 * The sync story's stage: the REAL SyncBar + PipelineBoard + ReviewQueue,
 * wired the way the signed-in dashboard wires them, over the same showcase
 * fixture the 01 plates dive into — one cast, one board, across the lab.
 *
 * A lab-owned twin of DemoDashboard's wiring (minus the rebuild machinery)
 * because the demo's pool cannot carry this story: the take needs a sync
 * that files two fresh confirmations AND delivers one held-for-review mail
 * (Cedar's — the same mail plate 08 holds), and /demo's fixtures are e2e
 * geometry that must not move for a marketing lab. Only the transports are
 * simulated; every component and every state machine is the shipped one.
 *
 * Content rule, from production truth: a sync NEVER auto-files a rejection.
 * The real account has never had one arrive except through the human review
 * gate, so the pool here is confirmations only, and the ambiguous mail lands
 * in the queue — where a real rejection actually enters the board.
 */

const GMAIL: SyncGmailState = {
  connected: true,
  lastSyncAt: null,
  hasCursor: true,
  syncStatus: null,
  syncError: null,
};

/** What the sync files: two fresh confirmations, dated today. Never a
 *  rejection — see the header note. */
function arrivalRows(today: string, firstId: number): Application[] {
  const seeds = [
    {
      company: "Foxglove Robotics",
      position: "Software Engineer, Perception",
      note: "Thanks for applying",
    },
    {
      company: "Basalt Systems",
      position: "Backend Engineer, Platform",
      note: "We received your application",
    },
  ];
  return seeds.map((seed, index) => ({
    id: firstId + index,
    user_id: "demo",
    company: seed.company,
    position: seed.position,
    status: "applied",
    notes: seed.note,
    created_at: `${today}T12:00:00.000Z`,
    source: "gmail",
    due_at: null,
    due_source: null,
  }));
}

/** How long the simulated scan runs — long enough that the running state is
 *  watchable in a take, short enough that nobody waits meaningfully. */
const SCAN_MS = 1900;

export function LabSyncBoard() {
  // One clock read per mount, resolved in render (never module load) — the
  // fixture-family hydration rule. This component only mounts client-side
  // (the take stages load it with ssr:false), so the day is the visitor's.
  const [today] = useState(todayISO);
  const [apps, setApps] = useState<Application[]>(() => showcaseApplications(today));
  const [held, setHeld] = useState<number>(0);
  // Rows in a ref mirrored into state — DemoDashboard's pattern, same
  // reason: the transports must stay referentially stable.
  const appsRef = useRef(apps);
  const commit = useCallback((next: (rows: Application[]) => Application[]) => {
    appsRef.current = next(appsRef.current);
    setApps(appsRef.current);
  }, []);

  const boardTransport = useMemo<BoardTransport>(
    () => ({
      async changeStatus(id, status) {
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

  const syncTransport = useMemo<SyncTransport>(
    () => ({
      mode: "simulated",
      async sync() {
        await new Promise((resolve) => setTimeout(resolve, SCAN_MS));
        const fresh = arrivalRows(today, 101);
        const already = appsRef.current.some((app) => app.company === fresh[0]!.company);
        if (!already) commit((rows) => [...fresh, ...rows]);
        setHeld(1);
        const created = already ? 0 : fresh.length;
        // Every count derives from what the store actually did. Incremental
        // scans carry no size estimate, matching the live backend.
        return {
          ok: true,
          status: 200,
          body: {
            created,
            updated: created > 0 ? 1 : 0,
            scanned: 12,
            applications: appsRef.current.length,
            needs_review: 1,
            stopped_by: "complete",
            result_size_estimate: null,
          },
        };
      },
      async restore() {
        return false; // nothing here removes rows, so there is nothing to restore
      },
    }),
    [commit, today],
  );

  const queue = held > 0 ? (
    <ReviewQueue items={[cedarReviewItem(today)]} applications={apps} />
  ) : null;

  return (
    <section className="flex flex-col gap-6">
      <SyncBar
        subtitle={buildSubtitle(summarize(apps), false)}
        gmail={GMAIL}
        transport={syncTransport}
      />
      <PipelineBoard
        variant="flow"
        applications={apps}
        pulse={{ needsReview: held }}
        transport={boardTransport}
        search={false}
        afterList={queue}
      />
    </section>
  );
}
