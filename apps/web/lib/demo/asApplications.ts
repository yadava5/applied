/**
 * Adapts the synthetic demo fixtures to the backend's `Application` shape so
 * the exact same pipeline board renders on the public `/demo` twin and inside
 * the signed-in dashboard's sample preview. One component tree, two data
 * sources — verifying the public demo therefore verifies the real dashboard's
 * building blocks.
 */
import type { Application } from "@/lib/dashboard/summary";
import { DEMO_APPLICATIONS } from "@/lib/demo/demoData";

/** The demo applications, projected onto the API `Application` type. */
export const DEMO_APPLICATIONS_AS_API: Application[] = DEMO_APPLICATIONS.map((app, index) => ({
  id: index + 1,
  user_id: "demo",
  company: app.company,
  position: app.position,
  status: app.status,
  // The most recent classified signal reads naturally as the card's note.
  notes: app.lastSignal,
  created_at: `${app.appliedAt}T12:00:00.000Z`,
}));
