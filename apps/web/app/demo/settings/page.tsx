import { cookies } from "next/headers";
import Link from "next/link";
import type { Metadata } from "next";

import { Logo } from "@/components/brand/Logo";
import { summarizeSignIn } from "@/components/settings/accountSecurity";
import { AccountSection } from "@/components/settings/AccountSection";
import { AppearanceSection } from "@/components/settings/AppearanceSection";
import { DataSection } from "@/components/settings/DataSection";
import { GmailConnectionCard } from "@/components/settings/GmailConnectionCard";
import { NotificationsSection } from "@/components/settings/NotificationsSection";
import { ProfileSection } from "@/components/settings/ProfileSection";
import { SettingsNav } from "@/components/settings/SettingsNav";
import { DEMO_AMBIENT_COOKIE, parseDemoAmbientPref } from "@/lib/demo/ambientPref";
import { DEMO_NOTIFICATIONS_COOKIE, parseDemoNotificationPrefs } from "@/lib/demo/notificationPrefs";
import type { GmailStatusResult } from "@/lib/gmail/server";

export const metadata: Metadata = {
  title: "Settings demo",
  description: "The Applied settings surface on fixture data. Nothing is saved, read, or deleted.",
};

/**
 * The Settings twin — the REAL settings sections over the simulated settings
 * transport (`lib/settings/transport.ts`), the same contract `/demo` holds
 * for the dashboard: only the transport is simulated, every control runs its
 * genuine state machine. It exists because `/settings` needs a session that
 * neither CI nor a local checkout has, so without this page the entire
 * settings surface had no executing e2e coverage and nothing reviewable.
 *
 * Theme-forced dark, like the rest of `/demo`. It used to honour the visitor's
 * saved theme so the Appearance switch below could be seen working — but the
 * demo is one journey, and `/demo` and `/` pin dark deliberately (the always-
 * dark product narrative, documented at globals.css `[data-theme="dark"]`), so
 * a light-theme visitor watched the whole page flip as they moved between the
 * board and settings. The family is one ground now, and the Appearance control
 * carries `mode="demo"`, which says plainly that the preview will not change
 * colour. The switch is still the real mechanism writing the real
 * `data-theme` — what it stops doing is pretending this page is the proof.
 *
 * Per-request rendering for the same reason as `/demo`: the fixture
 * `last_sync_at` below is relative to now, and a prerendered copy would age
 * ("last synced 34 minutes ago" is only honest if the page is rendered when
 * you ask for it).
 */
export const dynamic = "force-dynamic";

function fixtureGmail(): GmailStatusResult {
  return {
    kind: "ok",
    status: {
      configured: true,
      connected: true,
      email: "demo@applied.example",
      last_sync_at: new Date(Date.now() - 34 * 60 * 1000).toISOString(),
      has_cursor: true,
      sync_status: "idle",
      sync_error: null,
    },
  };
}

export default async function DemoSettingsPage() {
  // The toggles seed from the SAME cookie the demo board reads, so the two
  // pages can never disagree about what is switched on. They used to be
  // seeded from a `{weekly: true, reviewAlerts: true}` literal while the twin's
  // board behaved as though both were off — the twin lying about its own
  // state, in the exact place #216 is about.
  const jar = await cookies();
  const notifications = parseDemoNotificationPrefs(jar.get(DEMO_NOTIFICATIONS_COOKIE)?.value);
  // Same one-cookie honesty for the ambient switch: this page seeds from the
  // value /demo/shell will render, so the two can never disagree.
  const ambient = parseDemoAmbientPref(jar.get(DEMO_AMBIENT_COOKIE)?.value);
  return (
    <main data-theme="dark" className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto w-full max-w-6xl px-6 pb-16">
        <header className="flex min-h-14 flex-wrap items-center justify-between gap-y-2 border-b border-line-soft py-2">
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/"
              className="brand-logo-link inline-flex min-h-11 items-center text-strong"
              aria-label="Applied — go to landing"
            >
              <Logo className="h-6 w-auto" />
            </Link>
            <span className="whitespace-nowrap rounded-full border border-line px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted">
              demo · fixture account · nothing is saved
            </span>
          </div>
          <Link
            href="/demo"
            className="inline-flex min-h-11 items-center font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:text-strong"
          >
            ← dashboard demo
          </Link>
        </header>

        <section className="mt-8 space-y-6">
          {/* The twin keeps a visible h1 — there is no shell TopBar here to
              carry the location, so this is the page's one title, not the
              duplicate #199 removed from the signed-in route. */}
          <header>
            <h1 className="text-2xl font-semibold tracking-tight text-strong">Settings</h1>
          </header>

          <div className="lg:grid lg:grid-cols-[10rem_minmax(0,48rem)] lg:gap-8">
            <SettingsNav />
            <div className="max-w-3xl space-y-6 lg:max-w-none">
              <ProfileSection
                mode="demo"
                initialName="Sam Fixture"
                email="demo@applied.example"
                memberSince="March 3, 2026"
                // The email-only shape, run through the REAL derivation — the
                // measured shape of the demo account, and the case that shows
                // (and e2e-exercises) the change-password control.
                signIn={summarizeSignIn({ identities: [{ provider: "email" }] })}
                // The fixture account has no photo and no Google identity, so
                // the twin opens on the state worth exercising: the invitation.
                // Uploading here runs the REAL crop and re-encode in the browser
                // and shows the actual result in the tile — only the storing is
                // simulated — so upload, replace and remove are all reviewable
                // and e2e-drivable without a session.
                //
                // WHAT THIS TWIN CANNOT SHOW, said plainly rather than left to
                // be assumed: with no Google photo to fall back to, removing an
                // upload here reverts to the initial. The revert-to-GOOGLE
                // branch needs an account that has both, so it is verified in
                // the signed-in app or not at all. Giving the fixture a Google
                // photo would trade one uncovered branch for another (the
                // invitation state is the one every new account starts in).
                avatarSource="none"
                avatarSrc={null}
                googleAvatarSrc={null}
              />
              {/* Appearance is device-local by design, so the demo IS the
                  product here — but this page is pinned dark with the rest of
                  the demo, and `mode="demo"` is what says so on the control
                  instead of leaving it looking inert. */}
              <AppearanceSection mode="demo" initialAmbient={ambient} />
              <GmailConnectionCard result={fixtureGmail()} demo />
              {/* #216: the twin's toggles and its board now read ONE cookie.
                  They used to disagree — this page seeded `{weekly: true,
                  reviewAlerts: true}` while the board twin behaved as though
                  both were off, so a test driving either proved nothing about
                  the other. */}
              <NotificationsSection mode="demo" initial={notifications} />
              {/* A Classification section used to render here and on the
                  signed-in page. It was pure prose after #208 took the inert
                  gate slider out, so it is gone from both — removing it from
                  one only would have re-created the drift that having the twin
                  render the identical sections exists to prevent. */}
              <DataSection mode="demo" />
              <AccountSection mode="demo" email="demo@applied.example" />
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
