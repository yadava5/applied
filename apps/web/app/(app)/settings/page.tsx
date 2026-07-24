import type { Metadata } from "next";

import { AccountSection } from "@/components/settings/AccountSection";
import { AppearanceSection } from "@/components/settings/AppearanceSection";
import { ClassificationSection } from "@/components/settings/ClassificationSection";
import { DataSection } from "@/components/settings/DataSection";
import { GmailConnectionCard } from "@/components/settings/GmailConnectionCard";
import { NotificationsSection, type NotificationPrefs } from "@/components/settings/NotificationsSection";
import { ProfileSection } from "@/components/settings/ProfileSection";
import { DEFAULT_GATE_PREFERENCE, GATE_MAX, GATE_MIN } from "@/lib/dashboard/model";
import { getGmailStatus } from "@/lib/gmail/server";
import { getCurrentUser } from "@/lib/supabase/auth";

export const metadata: Metadata = {
  title: "Settings — Applied",
  description: "Manage your profile, appearance, notifications, classification, data, and Gmail.",
};

/**
 * The real product Settings surface: Profile, Appearance, the Gmail
 * connection, Notifications, Classification, Data, and Account — each actually
 * wired. Profile/Notifications/Classification persist to the Supabase user's
 * metadata; Appearance is a device-local theme; Data exports through the
 * server-side proxy; Account signs out or deletes via the admin route. The
 * `(app)` layout guarantees an authenticated user before this renders.
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

function readNotificationPrefs(meta: Record<string, unknown>): NotificationPrefs {
  const raw = (meta.notifications ?? {}) as Record<string, unknown>;
  return { weekly: raw.weekly === true, reviewAlerts: raw.reviewAlerts === true };
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

  return (
    <section className="mx-auto max-w-3xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-strong">Settings</h1>
        <p className="mt-1 font-mono text-xs text-dim">Your account, appearance, mail, and data.</p>
      </header>

      {banner ? (
        <div
          role="status"
          className={`rounded-xl border bg-surface px-4 py-3 text-sm ${TONE_CLASS[banner.tone]}`}
        >
          {banner.text}
        </div>
      ) : null}

      <ProfileSection initialName={displayName} email={email} memberSince={memberSince} />
      <AppearanceSection />
      <GmailConnectionCard result={gmailResult} />
      <NotificationsSection initial={readNotificationPrefs(meta)} />
      <ClassificationSection initialGate={clampGate(meta.gate_threshold)} />
      <DataSection />
      <AccountSection email={email} />
    </section>
  );
}
