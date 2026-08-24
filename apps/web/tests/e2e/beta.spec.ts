import { expect, test } from "@playwright/test";

import {
  expectNoHorizontalOverflow,
  MOBILE_375,
  startConsoleWatch,
} from "./helpers";
import { requireSession } from "./session";

/**
 * E2E for the beta-access notice.
 *
 * The rich <BetaCard> lives on /settings and the not-connected /inbox, which
 * are auth-gated and unreachable without a session — so these specs exercise
 * the publicly reachable surface: the dismissible site-wide banner, whose
 * popover carries the same verified copy + actions as the card. It is
 * root-layout chrome (`app/layout.tsx` mounts <BetaBanner/>), so the route
 * below is only the page these tests happen to load it on.
 *
 * IT USED TO BE `/`, AND THAT WAS THE BUG THESE TESTS WERE SITTING ON.
 * `BetaBanner`'s `HIDE_ON` has always said a fixed app toast must not float
 * over the marketing landing; it listed `/landing-a|b|c`, and when candidate
 * B was promoted into `app/page.tsx` the list did not follow. So the pill
 * shipped on the one landing a stranger actually loads — and this suite,
 * loading `/`, read that regression as its happy path. A spec that asserts
 * the pill is visible on the surface the product says must not have it will
 * never fail when the rule breaks; it fails when the rule is FIXED.
 *
 * `/privacy` is the honest host: public, reachable without a session, and
 * genuinely a surface the pill belongs on. `/` now carries the opposite
 * assertion at the foot of this file, and the two are each other's control —
 * one proves the pill can render, the other proves the route rule bites.
 */
const BANNER_ROUTE = "/privacy";

// encodeURIComponent("Applied beta access request") === "Applied%20beta%20access%20request"
const ADMIN_MAILTO =
  /^mailto:aesh\.03\.23@gmail\.com\?subject=Applied%20beta%20access%20request/;

test.describe("beta access notice", () => {
  test("the beta pill renders and expands into the beta details", async ({
    page,
  }) => {
    const watch = startConsoleWatch(page);
    await page.goto(BANNER_ROUTE);

    const toggle = page.getByRole("button", { name: /limited access/i });
    await expect(toggle).toBeVisible();

    // The card/details are collapsed until asked for.
    const panel = page.getByRole("region", { name: /beta access/i });
    await expect(panel).toHaveCount(0);

    await toggle.click();
    await expect(panel).toBeVisible();
    // The seat cap is the honest Google OAuth test-user limit — always 100,
    // never a hydration-stranded 0/-1. (This shared BETA_SEATS constant also
    // feeds the rich <BetaCard> seat panel on the auth-gated /settings & /inbox,
    // where it is rendered as a static server number for the same reason.)
    await expect(panel.getByText(/\b100 beta testers\b/i)).toBeVisible();
    await expect(
      panel.getByText(/Google's OAuth test-user cap/i),
    ).toBeVisible();

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("the email-admin action composes to the admin mailbox with the right subject", async ({
    page,
  }) => {
    await page.goto(BANNER_ROUTE);
    await page.getByRole("button", { name: /limited access/i }).click();

    const mailto = page.getByRole("link", {
      name: "Email admin for beta access",
    });
    await expect(mailto).toHaveAttribute("href", ADMIN_MAILTO);
    // It only composes an email — never a live navigation target.
    await expect(mailto).toHaveAttribute("href", /body=/);
  });

  /**
   * THE PRESENT HALF OF A PAIR. Read it with "the signed-in app offers no
   * route into the demo" at the foot of this file — neither assertion means
   * anything alone. An absence-only gate would stay green against a build
   * where the popover's second action had simply been deleted, which is the
   * over-correction this pair exists to catch.
   *
   * WHAT THE SECOND ACTION IS NOW, and why it changed. It used to be "Try the
   * sample inbox" → /demo/inbox, on the argument that this pill's `HIDE_ON`
   * list left only signed-out visitors. That argument was wrong, and this test
   * was standing on it: `HIDE_ON` names ROUTES, and BANNER_ROUTE is /privacy —
   * a route a SIGNED-IN user reaches from a standing link on the protected
   * Inbox page and from the Gmail card in Settings, and which wears the full
   * app shell when they do. This test ran signed out, so it never saw the
   * other half of its own subject. The pill now carries /import instead: the
   * real classifier over the reader's own mail, in their browser, no account
   * and no connection — the same pair `BetaCard` offers inside the app, so
   * there is no divergence left between the two surfaces to justify.
   *
   * `tests/unit/no-demo-inside-the-app.test.mjs` holds the static half, walks
   * from the ROOT layout, and executes on every PR — which this spec, behind
   * `requireSession()`, still does not.
   */
  test("the popover's second action is the import path, not the demo", async ({
    page,
  }) => {
    await page.goto(BANNER_ROUTE);
    await page.getByRole("button", { name: /limited access/i }).click();

    const panel = page.getByRole("region", { name: /beta access/i });
    // The seat request is the popover's point and must survive alongside it.
    await expect(
      panel.getByRole("link", { name: /email admin for beta access/i }),
    ).toBeVisible();

    // The absence half, asserted HERE rather than only on a signed-in surface,
    // because this popover is root-layout chrome: it is the same DOM either
    // way, and this is the one place the assertion executes.
    await expect(panel.locator('a[href^="/demo"]')).toHaveCount(0);

    await panel.getByRole("link", { name: /import your own mail/i }).click();

    await expect(page).toHaveURL(/\/import$/);
  });

  test("the banner is dismissible and stays dismissed across reloads", async ({
    page,
  }) => {
    await page.goto(BANNER_ROUTE);

    const toggle = page.getByRole("button", { name: /limited access/i });
    await expect(toggle).toBeVisible();

    await page.getByRole("button", { name: /dismiss beta notice/i }).click();
    await expect(toggle).toHaveCount(0);

    // Persisted in localStorage — still gone after a reload. The heading is
    // the control that the reload actually landed a rendered page: without
    // it, a blank response would satisfy the toHaveCount(0) below and this
    // test would pass on a broken route. It follows BANNER_ROUTE.
    await page.reload();
    await expect(
      page.getByRole("heading", {
        name: /What Applied reads, and what it keeps/i,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /limited access/i }),
    ).toHaveCount(0);
  });

  test("no console errors and no horizontal overflow at 375px with the popover open", async ({
    page,
  }) => {
    const watch = startConsoleWatch(page);
    await page.setViewportSize(MOBILE_375);
    await page.goto(BANNER_ROUTE);

    const toggle = page.getByRole("button", { name: /limited access/i });
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(
      page.getByRole("region", { name: /beta access/i }),
    ).toBeVisible();

    await expectNoHorizontalOverflow(page);
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });
});

/**
 * THE `privacy positioning (landing)` DESCRIBE WAS DELETED HERE, and what it
 * covered is worth naming rather than losing quietly.
 *
 * It asserted the OLD landing's PRIVACY section — "Your inbox stays yours",
 * the three pillars, and four code-verified strings rendered on the page:
 * `gmail.readonly`, `allowRemoteModels = false`, "never handed to one" and
 * "22.8 MB". That section does not exist on the landing this repo now serves
 * (the pinned composition promoted from `/landing-b`), which makes its
 * privacy argument in its own register — retention, not model provenance —
 * so there is nothing here to re-point the locators at.
 *
 * The claims themselves are not unclaimed: the model/scope facts still live
 * in the System Card and in `ml/`, and the new landing's retention promise is
 * held by `tests/unit/landing-variants.test.mjs` (a source scan, which names
 * the backend test that proves it). But those four strings no longer have a
 * RENDER-TIME gate anywhere in this suite. If the landing ever states them
 * again, gate them again.
 */

/**
 * The route rule, gated on both sides.
 *
 * `HIDE_ON` is a list of strings in a component nothing on the landing
 * imports, so no source scan of the landing's module graph can see it — the
 * pill reaches the page through `app/layout.tsx`, which Next COMPOSES rather
 * than imports. That is the same blind spot that let a benchmark figure sit
 * in the root metadata through an entire copy sweep. The only instrument that
 * sees it is a render.
 *
 * Both halves are here on purpose. The `/privacy` case is the positive
 * control: if the pill ever stops rendering anywhere, the landing assertion
 * below would still pass while asserting nothing, and this suite would go
 * green over a deleted feature.
 */
test.describe("the beta pill's route rule", () => {
  const PILL = /limited access/i;

  test("the pill does not float over the marketing landing, and still renders where it belongs", async ({
    page,
  }) => {
    // The landing: a fixed app toast here is app chrome leaking into
    // marketing. At 375 it also OCCLUDED the board — hit-testing the pill's
    // centre returned the still's own "Software Engineer, Simulation" row.
    await page.setViewportSize(MOBILE_375);
    await page.goto("/");
    // Positive control on the page itself: we are on the landing, not on an
    // error route that trivially has no pill.
    await expect(
      page.getByRole("heading", { name: /You lose the email/i }),
    ).toBeVisible();
    // The pill mounts on a deferred macrotask, so a bare toHaveCount(0) would
    // pass simply by racing it. Wait for the page to settle first.
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("button", { name: PILL })).toHaveCount(0);

    // The control: the same pill, same viewport, on a route that keeps it.
    await page.goto(BANNER_ROUTE);
    await expect(page.getByRole("button", { name: PILL })).toBeVisible();
  });
});

/**
 * THE ABSENT HALF OF THE PAIR ABOVE (#495).
 *
 * `<BetaCard>` is the renderer that sits INSIDE the product —
 * `app/(app)/(protected)/inbox/page.tsx` and `GmailConnectionCard` on
 * /settings — and it carried "Try the sample inbox" → /demo/inbox until #495.
 * Nothing inside the app is the demo, so it is gone from there and stays gone.
 *
 * The assertion is deliberately about the WHOLE signed-in page rather than the
 * card alone: the card renders only in the not-connected state, so a
 * card-scoped locator would silently assert nothing against a connected
 * account and look exactly like a pass. "This route offers no link into
 * /demo" is true whatever the connection state, and it is the directive
 * itself rather than a proxy for it.
 *
 * Auth-gated, so it goes through `requireSession()` and skips loudly under the
 * shared `E2E_NO_SESSION_SKIP (#188):` token when there is no session — the
 * banner half above runs without one and keeps the pair honest meanwhile.
 */
test.describe("no demo inside the app", () => {
  test("the signed-in inbox offers no route into the demo", async ({
    page,
  }) => {
    await requireSession(
      page,
      "the signed-in inbox carrying no link into /demo",
    );
    await page.goto("/inbox");

    // Arrival is asserted on the URL, not on a heading: /inbox's own <h1> is
    // sr-only and its visible chrome differs by connection state, while a
    // bounce to /login would satisfy both toHaveCount(0)s below for the wrong
    // reason. requireSession() guarantees the session; this guarantees the
    // route.
    await expect(page).toHaveURL(/\/inbox$/);
    await expect(page.locator('a[href^="/demo"]')).toHaveCount(0);
    await expect(page.getByRole("link", { name: /sample inbox/i })).toHaveCount(
      0,
    );
  });
});
