/**
 * Adapts the synthetic demo fixtures to the backend's `Application` shape so
 * the exact same pipeline board renders on the public `/demo` twin and inside
 * the signed-in dashboard's sample preview. One component tree, two data
 * sources — verifying the public demo therefore verifies the real dashboard's
 * building blocks.
 *
 * These are functions, not constants, because the fixture dates are relative
 * (see `demoData.ts`): they must be resolved during a render, against the same
 * clock read that render ages them with, not frozen at module load.
 */
import { todayISO } from "@/lib/dashboard/age";
import type { Application } from "@/lib/dashboard/summary";
import {
  DEMO_APPLICATION_COUNT,
  demoApplications,
  demoUnsynced,
  type DemoApplication,
} from "@/lib/demo/demoData";

function toApi(app: DemoApplication, id: number): Application {
  return {
    id,
    user_id: "demo",
    company: app.company,
    position: app.position,
    status: app.status,
    // The most recent classified signal reads naturally as the card's note.
    notes: app.lastSignal,
    created_at: `${app.appliedAt}T12:00:00.000Z`,
    // THE DAY THE APPLICATION WAS FILED, carried in the field a real row
    // carries it in. `appliedAt` has always meant this; it was only ever
    // written to `created_at`, so every fixture row reached the board with a
    // null `applied_date` — a shape no row from real mail has.
    //
    // That gap was invisible while the header counted "this week" off
    // `created_at`, and became a failing e2e the moment it counted off the day
    // the user applied: the twin's week silently went to zero, because not one
    // fixture row had the field the count now reads. The twin has to model the
    // real row, or the surface the tests measure stops being the surface that
    // ships (#188's shape, in the data instead of the session).
    applied_date: app.appliedAt,
    // Every fixture row is "from Gmail" in the simulation, so the rebuild's
    // stale-row semantics apply to them the way they would on a real board.
    source: "gmail",
    // Fixture deadlines are all mail-extracted — `due_source: "user"` only
    // ever appears here after a visitor writes one through the sheet, exactly
    // as on a live board. null iff due_at is null, matching the API contract.
    due_at: app.dueAt ?? null,
    due_source: app.dueAt ? "mail" : null,
  };
}

/** The demo applications, projected onto the API `Application` type. */
export function demoApplicationsAsApi(today: string = todayISO()): Application[] {
  return demoApplications(today).map((app, index) => toApi(app, index + 1));
}

/** The not-yet-synced fixture rows, ids continuing after the board's. */
export function demoUnsyncedAsApi(today: string = todayISO()): Application[] {
  return demoUnsynced(today).map((app, index) => toApi(app, DEMO_APPLICATION_COUNT + index + 1));
}

/**
 * The early-search projection (`/demo?pipeline=early`): the SAME fixtures,
 * every row resting at `applied` — the measured shape of the one real
 * production account (29 live rows, 100% in one stage), which is the case the
 * worklist redesign exists for and the case the healthy seed board can never
 * show. Roughly the real board's share of rows also lose their role (8 of 29
 * live rows never had one named), so the fixed role slot renders at its real
 * density. Deadlines are cleared: a board this young hasn't earned any, and a
 * leftover assessment date would contradict the all-applied claim.
 */
export function demoEarlySearchAsApi(today: string = todayISO()): Application[] {
  return demoApplicationsAsApi(today).map((app, index) => ({
    ...app,
    status: "applied",
    notes: "Your application was received",
    due_at: null,
    due_source: null,
    position: index % 4 === 2 ? "" : app.position,
  }));
}
