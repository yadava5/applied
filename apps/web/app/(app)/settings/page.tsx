import type { Metadata } from "next";
import { Suspense } from "react";

import { summarizeSignIn } from "@/components/settings/accountSecurity";
import { AccountSection } from "@/components/settings/AccountSection";
import { AppearanceSection } from "@/components/settings/AppearanceSection";
import { ClassificationSection } from "@/components/settings/ClassificationSection";
import { DataSection } from "@/components/settings/DataSection";
import { GmailConnectionCard } from "@/components/settings/GmailConnectionCard";
import { NotificationsSection } from "@/components/settings/NotificationsSection";
import { ProfileSection } from "@/components/settings/ProfileSection";
import { SettingsNav } from "@/components/settings/SettingsNav";
import { getGmailStatus } from "@/lib/gmail/server";
import { readNotificationPrefs } from "@/lib/settings/notifications";
import { deletionEnabled } from "@/lib/supabase/admin";
import { getCurrentUser } from "@/lib/supabase/auth";

export const metadata: Metadata = {
  title: "Settings",
  description: "Manage your profile, appearance, notifications, classification, data, and Gmail.",
};

/**
 * This route PARTICIPATES in the router cache `next.config.ts` turns on
 * (`experimental.staleTimes.dynamic = 30`). It used to pin itself out with
 * `unstable_dynamicStaleTime = 0`, which made Settings the one tab that could
 * never arrive warm: every dashboard→settings click re-paid the full origin
 * render — 700–1150 ms of measured server time (#203) — even ten seconds
 * after the last one. That pin is gone, deliberately, and these are the
 * invariants that replace it (every one checked against the sections as they
 * are TODAY, not as the old comment remembered them):
 *
 *   - Every metadata writer on this page publishes. `ProfileSection` and
 *     `NotificationsSection` call `router.refresh()` on a successful save
 *     (#216/#231), which bumps Next's GLOBAL segment-cache version — a stale
 *     entry of THIS route cannot survive its own save. The save→navigate→
 *     return cycle is executable e2e: `tests/e2e/settings.spec.ts`, "without
 *     waiting out the router cache".
 *   - The remaining sections write no server-rendered state at all:
 *     `ClassificationSection` is propless and writes nothing (#208),
 *     `AppearanceSection` is a device-local theme, `DataSection` only reads,
 *     `AccountSection` leaves the route on both of its actions (sign-out
 *     refreshes then replaces, delete replaces), and `ChangePasswordForm`
 *     changes a credential nothing on this page renders.
 *   - The Gmail round-trips cannot meet a cached entry: OAuth re-enters at
 *     `/settings?gmail=connected` from OUTSIDE the router (a document load —
 *     a fresh router cache by construction), and disconnect is a native form
 *     POST whose redirect is likewise a document load.
 *   - The case the pin stood guard for — the NEXT section added writing
 *     metadata without publishing — is guarded by a gate that can actually
 *     fail instead of a standing per-navigation tax:
 *     `tests/unit/settings-publish-contract.test.mjs` rejects any
 *     `components/settings` source that calls `saveMetadata` without also
 *     calling `router.refresh`.
 */

/**
 * The real product Settings surface: Profile, Appearance, the Gmail
 * connection, Notifications, Classification, Data, and Account — each actually
 * wired. Profile/Notifications/Classification persist to the Supabase user's
 * metadata; Appearance is a device-local theme; Data exports through the
 * server-side proxy; Account signs out or deletes via the admin route. The
 * `(app)` layout guarantees an authenticated user before this renders.
 *
 * Layout: a sticky section rail beside the sections at desktop, so seven
 * cards stop being one blind scroll — the rail is the page's table of
 * contents, and the shell's scroll pane honours the anchor jumps. The copy
 * across the sections is cut to one working line per control; the long-form
 * reference material (Gmail safeguards, the restricted-scope scale story)
 * survives in disclosures on the Gmail card.
 *
 * No visible in-page title (#199): the rail and the TopBar's location label
 * already both say "Settings", so a third copy plus a subtitle restating the
 * section list was noise. Same resolution as the board route — one place owns
 * the visible name — but here TopBar is that place, so the page keeps only an
 * sr-only h1 for the document outline.
 *
 * These same sections render publicly on `/demo/settings` over the simulated
 * settings transport — that twin is where their e2e coverage executes,
 * because this route needs a session CI does not have.
 */

const FLAG_BANNERS: Record<string, { tone: "ok" | "warn" | "error"; text: string }> = {
  connected: {
    tone: "ok",
    text: "Gmail connected. Applied can now read and classify your job-search mail.",
  },
  disconnected: { tone: "ok", text: "Gmail disconnected and access revoked at Google." },
  error: { tone: "error", text: "Something went wrong reaching the mail backend. Please try again." },
  auth: {
    tone: "error",
    text: "Your session couldn't be verified for the mail backend. Sign in again and retry.",
  },
  unavailable: {
    tone: "warn",
    text: "Gmail connection isn't enabled on this deployment yet — see the note below.",
  },
};

const TONE_CLASS: Record<"ok" | "warn" | "error", string> = {
  ok: "border-live/40 text-strong",
  warn: "border-line-strong text-muted",
  error: "border-reject/50 text-strong",
};

/**
 * The page's ONE backend read, isolated behind Suspense so the rest of
 * Settings — which needs only the request-memoized Supabase user — streams to
 * the client without waiting on the FastAPI round-trip (measured at 700–1150
 * ms of the page's origin time, #203). The card fills in when the status
 * answers; until then the fallback below holds a same-shape plate so the
 * sections after it don't jump when it lands.
 */
async function LiveGmailCard() {
  const result = await getGmailStatus();
  return <GmailConnectionCard result={result} />;
}

/** Same border/surface/padding as the card it stands in for. */
function GmailCardFallback() {
  return (
    <div
      id="gmail"
      aria-busy="true"
      aria-label="Checking your Gmail connection"
      className="scroll-mt-16 rounded-xl border border-line-soft bg-surface p-5 lg:scroll-mt-4"
    >
      <div className="h-6 w-24 animate-pulse rounded bg-surface-2" />
      <div className="mt-2 h-4 w-full max-w-sm animate-pulse rounded bg-surface-2" />
      <div className="mt-4 h-4 w-40 animate-pulse rounded bg-surface-2" />
      <div className="mt-6 border-t border-line-soft pt-4">
        <div className="h-4 w-56 animate-pulse rounded bg-surface-2" />
      </div>
    </div>
  );
}

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ gmail?: string }>;
}) {
  const { gmail: flag } = await searchParams;
  const banner = flag ? FLAG_BANNERS[flag] : undefined;

  // The Gmail status is NOT awaited here — `LiveGmailCard` reads it behind
  // its Suspense boundary, so this render blocks only on the (memoized,
  // shared-with-the-layout) Supabase user read.
  const user = await getCurrentUser();
  const meta = (user?.user_metadata ?? {}) as Record<string, unknown>;
  const email = user?.email ?? "";
  const displayName = typeof meta.display_name === "string" ? meta.display_name : "";
  const memberSince = user?.created_at
    ? new Date(user.created_at).toLocaleDateString("en-US", {
        month: "long",
        day: "numeric",
        year: "numeric",
      })
    : null;

  // Measure capped for form readability, but aligned to the shell's shared
  // left edge (no `mx-auto`): every authed page starts at the same x.
  return (
    // `relative` parents the sr-only h1's absolute positioning so it can
    // never extend the document's scroll area (the standing sr-only trap).
    <section className="relative space-y-6">
      <h1 className="sr-only">Settings</h1>

      {banner ? (
        <div
          role="status"
          className={`max-w-3xl rounded-xl border bg-surface px-4 py-3 text-sm ${TONE_CLASS[banner.tone]}`}
        >
          {banner.text}
        </div>
      ) : null}

      <div className="lg:grid lg:grid-cols-[10rem_minmax(0,48rem)] lg:gap-8">
        <SettingsNav />
        <div className="max-w-3xl space-y-6 lg:max-w-none">
          <ProfileSection
            initialName={displayName}
            email={email}
            memberSince={memberSince}
            signIn={summarizeSignIn(user)}
          />
          <AppearanceSection />
          <Suspense fallback={<GmailCardFallback />}>
            <LiveGmailCard />
          </Suspense>
          <NotificationsSection initial={readNotificationPrefs(meta)} />
          <ClassificationSection />
          <DataSection />
          {/* Read server-side, not fetched: the user must learn deletion is
              unavailable on this deployment BEFORE arming the typed
              confirmation, and a client fetch would arrive after the dialog
              was already readable (#218). */}
          <AccountSection email={email} deletionEnabled={deletionEnabled()} />
        </div>
      </div>
    </section>
  );
}
