import type { Metadata } from "next";

import { summarizeSignIn } from "@/components/settings/accountSecurity";
import { AccountSection } from "@/components/settings/AccountSection";
import { AppearanceSection } from "@/components/settings/AppearanceSection";
import { ClassificationSection } from "@/components/settings/ClassificationSection";
import { DataSection } from "@/components/settings/DataSection";
import { GmailConnectionCard } from "@/components/settings/GmailConnectionCard";
import { NotificationsSection } from "@/components/settings/NotificationsSection";
import { ProfileSection } from "@/components/settings/ProfileSection";
import { SettingsNav } from "@/components/settings/SettingsNav";
import { DEFAULT_GATE_PREFERENCE, GATE_MAX, GATE_MIN } from "@/lib/dashboard/model";
import { getGmailStatus } from "@/lib/gmail/server";
import { readNotificationPrefs } from "@/lib/settings/notifications";
import { deletionEnabled } from "@/lib/supabase/admin";
import { getCurrentUser } from "@/lib/supabase/auth";

export const metadata: Metadata = {
  title: "Settings",
  description: "Manage your profile, appearance, notifications, classification, data, and Gmail.",
};

/**
 * This route opts OUT of the router cache `next.config.ts` turns on for every
 * other page (`experimental.staleTimes.dynamic = 30`). Nothing about the
 * caching is wrong in general — it is wrong HERE, and for a reason specific
 * to this page.
 *
 * Every section below seeds its own `useState` from a prop this server
 * component read out of the Supabase user's metadata (`initialName`,
 * `initial`, `initialGate`), saves through `settingsTransport.saveMetadata`,
 * and — unlike every mutating surface on the dashboard and the inbox — does
 * NOT call `router.refresh()`. Today that is harmless, because leaving and
 * returning re-renders this page against fresh metadata. Under a 30-second
 * cache it would not be: toggle the weekly digest on, click Dashboard, click
 * Settings, and the toggle would sit there visibly switched back off until the
 * window expired. A just-saved setting reverting in front of you is a bug, not
 * a stale number.
 *
 * `0` means "never reuse", and it is a distinct value rather than a fallback —
 * Next's sentinel for "the page said nothing" is `-1`
 * (`UnknownDynamicStaleTime`), so this genuinely pins the route.
 *
 * The other half of the fix is to make those sections refresh after a save,
 * at which point this line can go. That is a change to
 * `components/settings/**`, which is not this branch's to make.
 */
export const unstable_dynamicStaleTime = 0;

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

function clampGate(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return DEFAULT_GATE_PREFERENCE;
  return Math.min(GATE_MAX, Math.max(GATE_MIN, n));
}

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ gmail?: string }>;
}) {
  const { gmail: flag } = await searchParams;
  const banner = flag ? FLAG_BANNERS[flag] : undefined;

  const [gmailResult, user] = await Promise.all([getGmailStatus(), getCurrentUser()]);
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
          <GmailConnectionCard result={gmailResult} />
          <NotificationsSection initial={readNotificationPrefs(meta)} />
          <ClassificationSection initialGate={clampGate(meta.gate_threshold)} />
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
