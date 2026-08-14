import {
  DemoDashboard,
  type DemoPipeline,
  type DemoReviewSlot,
} from "@/components/demo/DemoDashboard";
import type { NotificationPrefs } from "@/components/settings/NotificationsSection";
import { AppShellFrame } from "@/components/shell/AppShellFrame";
import type { RailData } from "@/lib/shell/rail";

/**
 * The demo, whole: the REAL `AppShellFrame` — the same component the
 * protected layout renders — around the dashboard twin in its LOCKED variant,
 * over the in-memory fixture store. This is ONE component so that `/demo`
 * (the public front door) and `/demo/shell` (the spec harness) render the
 * same tree by construction rather than by discipline: the front door and the
 * harness diverging is precisely the defect class this family exists to
 * prevent — three rounds of "the dashboard is fixed" were once measured on a
 * /demo that had quietly stopped being the thing it stood in for.
 *
 * The two routes differ only in what they pass here: /demo passes the organic
 * defaults (plus `?pipeline`, a reviewable projection, and the Settings
 * twin's cookie), /demo/shell adds the harness knobs its executing geometry
 * specs drive (`?review`, `?queue`, `?session` — each documented in that
 * route's own header with the defect it was added for).
 */

/** The rail's Gmail state, fixture: connected, never synced, no address of its
 *  own (`email: null` — the footer then asserts, by omission, that the
 *  connected mailbox IS the signed-in one, exactly as it does for very nearly
 *  every real account). */
const DEMO_RAIL: RailData = {
  gmail: {
    connected: true,
    email: null,
    lastSyncAt: null,
    hasCursor: true,
    syncStatus: null,
    syncError: null,
  },
};

export function DemoShell({
  pipeline = "seed",
  needsReview = 0,
  notifications,
  reviewSlot,
  sessionEdge = false,
  ambient = true,
}: {
  pipeline?: DemoPipeline;
  needsReview?: number;
  notifications?: NotificationPrefs;
  reviewSlot?: DemoReviewSlot;
  sessionEdge?: boolean;
  /** The rail's ambient-mail pref — the demo Settings toggle's cookie, passed
   *  through to `AppShellFrame` exactly as the (app) layout passes the real
   *  account's saved answer. */
  ambient?: boolean;
}) {
  return (
    // The fixture gets a NAME as well as an email — the real rail shows the
    // display name now, and a twin that still printed the address would drift
    // from the surface it stands in for. Same persona as /demo/settings'
    // profile: one fixture identity, and the one the rail's conversion block
    // ("Sam isn't real…") is talking about.
    <AppShellFrame
      rail={DEMO_RAIL}
      userEmail="demo@applied.example"
      userName="Sam Fixture"
      ambient={ambient}
      demo
    >
      <DemoDashboard
        variant="locked"
        pipeline={pipeline}
        needsReview={needsReview}
        notifications={notifications}
        reviewSlot={reviewSlot}
        sessionEdge={sessionEdge}
      />
    </AppShellFrame>
  );
}
