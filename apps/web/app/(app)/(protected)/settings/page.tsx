import type { Metadata } from "next";
import { Suspense } from "react";

import { summarizeSignIn } from "@/components/settings/accountSecurity";
import { AccountSection } from "@/components/settings/AccountSection";
import { AppearanceSection } from "@/components/settings/AppearanceSection";
import { DataSection } from "@/components/settings/DataSection";
import { GmailConnectionCard } from "@/components/settings/GmailConnectionCard";
import { NotificationsSection } from "@/components/settings/NotificationsSection";
import { ProfileSection } from "@/components/settings/ProfileSection";
import { SettingsNav } from "@/components/settings/SettingsNav";
import { PageHeader } from "@/components/shell/PageHeader";
import { getGmailStatus } from "@/lib/gmail/server";
import { readAmbientPref } from "@/lib/settings/ambient";
import { readNotificationPrefs } from "@/lib/settings/notifications";
import { deletionEnabled } from "@/lib/supabase/admin";
import { getCurrentUser } from "@/lib/supabase/auth";

export const metadata: Metadata = {
  title: "Settings",
  description: "Manage your profile, appearance, notifications, data, and Gmail.",
};

/**
 * This route PARTICIPATES in the router cache `next.config.ts` turns on
 * (`experimental.staleTimes.dynamic = 300`). It used to pin itself out with
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
 * connection, Notifications, Data, and Account — each actually wired.
 * Profile/Notifications persist to the Supabase user's metadata; Appearance is
 * a device-local theme; Data exports through the server-side proxy; Account
 * signs out or deletes via the admin route. The `(app)` layout guarantees an
 * authenticated user before this renders.
 *
 * A Classification section used to sit between Notifications and Data. Once
 * #208 removed the gate slider it held nothing to change — a card of reference
 * prose on the one page whose whole promise is "these are the things you can
 * edit". The rule it stated is still told where it is acted on: the review
 * queue draws each verdict against the gate, and the landing cascade and the
 * System Card state the number and what clearing it does and does not license.
 *
 * Layout: a sticky section rail beside the sections at desktop, so six
 * cards stop being one blind scroll — the rail is the page's table of
 * contents, and the shell's scroll pane honours the anchor jumps. The copy
 * across the sections is cut to one working line per control; the long-form
 * reference material (Gmail safeguards, the restricted-scope scale story)
 * survives in disclosures on the Gmail card.
 *
 * No visible in-page title (#199): a copy plus a subtitle restating the section
 * list was noise. Same resolution as the board route — one place owns the
 * visible name — and above `lg` that place is now the lit rail item alone:
 * TopBar yields on this route (see `components/shell/PageHeader`), so its
 * location label is gone at the width the owner works at. Below `lg` the rail
 * is hidden and the bar's label is what names the page. Either way this file
 * keeps only an sr-only h1, for the document outline.
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
  // The beta cap (backend 409). This is the only banner that asks the reader to
  // do something outside the product, and it has to: Google caps how many
  // people this app may ever connect and that number cannot be raised on
  // request, so "try again later" would be false. The address is the whole
  // point of the message — a refusal with no way to appeal it is a dead end,
  // and importing an export needs no Google account at all.
  capacity: {
    tone: "warn",
    text: "The Gmail beta is full, so this account can't connect a mailbox yet. Email aesh.03.23@gmail.com to ask for a place. Importing a mailbox export still works.",
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

/**
 * Same border/surface/padding as the card it stands in for.
 *
 * Deliberately WITHOUT `id="gmail"` (#268): `GmailConnectionCard` declares that
 * id, and streaming SSR can have this fallback and the resolved card in the
 * document at the same moment — two elements answering to one id, so
 * `getElementById` and the rail's `a[href="#gmail"]` resolve to whichever React
 * left first. The card carries the anchor from the instant it resolves, which
 * is the only instant a jump to it can mean anything. `scroll-mt` stays: it is
 * what keeps the heading clear of the pinned strip once the card lands here.
 */
function GmailCardFallback() {
  return (
    <div
      aria-busy="true"
      aria-label="Checking your Gmail connection"
      className="scroll-mt-16 rounded-xl border border-line-soft bg-surface p-5 lg:scroll-mt-4"
    >
      {/* Hairline outlines, not pulsing plates. This box is the one pending
          surface on the route that OUTLIVES `loading.tsx` — it holds the Gmail
          slot for the whole backend round-trip after the rest of Settings has
          already swapped to content — so a filled `animate-pulse` blob here
          left one panel speaking the old texture in the middle of a page
          drawn entirely in the quiet form. Same boxes, same heights: the
          swap's geometry is unchanged. */}
      <div className="h-6 w-24 rounded border border-line-strong" />
      <div className="mt-2 h-4 w-full max-w-sm rounded border border-line" />
      <div className="mt-4 h-4 w-40 rounded border border-line" />
      <div className="mt-6 border-t border-line-soft pt-4">
        <div className="h-4 w-56 rounded border border-line" />
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

      {/* The header line at `lg`+, in the board's idiom — carrying the session
          edge and nothing else, deliberately. Settings has no state to promote
          that is not already stated once by something that is also a control:
          the section list IS `SettingsNav` (a sticky rail beside the cards at
          this width, not header material), the identity is the rail footer's,
          the Gmail connection is the card's own — and it is behind a Suspense
          boundary precisely so this render does not block on it (#203), which a
          header claim would undo. So: controls alone. It exists because TopBar
          yields here now and sign-out has to stay reachable above `lg`. */}
      <PageHeader />

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
          <AppearanceSection initialAmbient={readAmbientPref(meta)} />
          <Suspense fallback={<GmailCardFallback />}>
            <LiveGmailCard />
          </Suspense>
          <NotificationsSection initial={readNotificationPrefs(meta)} />
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
