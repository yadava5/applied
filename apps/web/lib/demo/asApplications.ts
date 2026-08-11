/**
 * Adapts the synthetic demo fixtures to the backend's `Application` shape so
 * the exact same pipeline board renders on the public `/demo` twin and inside
 * the signed-in dashboard's sample preview. One component tree, two data
 * sources — verifying the public demo therefore verifies the real dashboard's
 * building blocks.
 */
import type { Application } from "@/lib/dashboard/summary";
import { DEMO_APPLICATIONS, DEMO_UNSYNCED, type DemoApplication } from "@/lib/demo/demoData";

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
export const DEMO_APPLICATIONS_AS_API: Application[] = DEMO_APPLICATIONS.map((app, index) =>
  toApi(app, index + 1),
);

/** The not-yet-synced fixture rows, ids continuing after the board's. */
export const DEMO_UNSYNCED_AS_API: Application[] = DEMO_UNSYNCED.map((app, index) =>
  toApi(app, DEMO_APPLICATIONS.length + index + 1),
);
