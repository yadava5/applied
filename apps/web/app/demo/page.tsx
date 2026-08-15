import { cookies } from "next/headers";
import type { Metadata } from "next";

import { DemoShell } from "@/components/demo/DemoShell";
import { DEMO_AMBIENT_COOKIE, parseDemoAmbientPref } from "@/lib/demo/ambientPref";
import { DEMO_NOTIFICATIONS_COOKIE, parseDemoNotificationPrefs } from "@/lib/demo/notificationPrefs";

export const metadata: Metadata = {
  title: "Live demo",
  description:
    "The signed-in Applied shell — rail, board, worklist — on fixture data. No inbox is read.",
};

/**
 * Rendered per request, because the fixtures are dated RELATIVE to today.
 *
 * As a static route this page is prerendered once and the build day's dates are
 * baked into the HTML on disk, while the client resolves "today" at view time —
 * so the filed stamps disagree and React throws a hydration error (#418) on
 * every day after the build. Measured: clean at +0d, mismatching at +3d, +30d
 * and +180d, and clean again at +365d, where the stamp string happens to
 * repeat. That last one is the proof it is the date and nothing else.
 *
 * Resolving the date on the server and passing it down does NOT fix this on a
 * static route — there, "server render time" IS build time, so the demo would
 * simply resume ageing, which is the defect the relative dates removed. Only
 * per-request rendering collapses the window to the UTC-midnight boundary that
 * `lib/dashboard/age.ts` already documents as accepted.
 */
export const dynamic = "force-dynamic";

/**
 * The product, auth-free — and now WHOLE. This used to render the dashboard
 * twin decapitated: the board on a bare page, no rail, no nav, no identity,
 * while the full `AppShellFrame` mount lived unlinked on /demo/shell as a
 * test harness. A visitor never saw the app; they saw a component. The front
 * door now renders `DemoShell` — the same shell frame the protected layout
 * mounts, the same locked dashboard geometry, the same components end to end
 * — so the demo IS the signed-in experience, minus only a session. Only the
 * transport and the data are simulated, the contract this family has always
 * held.
 *
 * What an anonymous visitor's shell does differently is confined to the
 * chrome, and every control still works or says what it is: the nav resolves
 * to the public twins (`demoNavHrefs` — sample inbox, in-browser import, the
 * settings twin), the session edge carries the provenance pill instead of a
 * sign-out, and the rail footer follows the fixture identity with the demo's
 * one conversion block (`DemoSignupCta`). Nothing covers the board; the board
 * is the pitch.
 *
 * The decision-trace showcase that closed the old page is not lost, it is
 * outgrown: the landing renders `DecisionTrace` itself, and the nav's Inbox
 * item leads to /demo/inbox, where the sample inbox traces REAL classifier
 * verdicts rather than this page's fixture ones.
 *
 * `?pipeline=early` renders the same shell over the early-search projection —
 * every row at `applied`, the measured shape of the real production account.
 * The healthy seed spread literally cannot show the distribution the worklist
 * redesign exists for, so the skewed case keeps its own reviewable, testable
 * URL. The harness knobs (`?review`, `?queue`, `?session`) stay on
 * /demo/shell, which renders this same tree — see its header for what each
 * knob measures and why nothing links to it.
 */
export default async function DemoPage({
  searchParams,
}: {
  searchParams: Promise<{ pipeline?: string }>;
}) {
  const { pipeline } = await searchParams;
  // Whatever the visitor set on /demo/settings — read on the SERVER and
  // passed down as props, the same shape the signed-in dashboard reads out of
  // the Supabase user's metadata. Absent cookie → both flags off, the live
  // default (#216). The ambient-rail pref rides the same jar (its own cookie,
  // written by the demo Settings' Appearance toggle).
  const jar = await cookies();
  const notifications = parseDemoNotificationPrefs(jar.get(DEMO_NOTIFICATIONS_COOKIE)?.value);
  const ambient = parseDemoAmbientPref(jar.get(DEMO_AMBIENT_COOKIE)?.value);
  return (
    <DemoShell
      pipeline={pipeline === "early" ? "early" : "seed"}
      notifications={notifications}
      ambient={ambient}
    />
  );
}
