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
    // Every fixture row is "from Gmail" in the simulation, so the rebuild's
    // stale-row semantics apply to them the way they would on a real board.
    source: "gmail",
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
