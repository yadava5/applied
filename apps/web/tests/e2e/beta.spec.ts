import { expect, test } from "@playwright/test";

import {
  expectNoHorizontalOverflow,
  MOBILE_375,
  startConsoleWatch,
} from "./helpers";

/**
 * E2E for the beta-access notice.
 *
 * The rich <BetaCard> lives on /settings and the not-connected /inbox, which
 * are auth-gated and unreachable without a session — so these specs exercise
 * the publicly reachable surface: the dismissible site-wide banner, whose
 * popover carries the same verified copy + actions as the card. It is
 * root-layout chrome (`app/layout.tsx` mounts <BetaBanner/>), so `/` is only
 * the page these tests happen to load it on.
 */

// encodeURIComponent("Applied beta access request") === "Applied%20beta%20access%20request"
const ADMIN_MAILTO =
  /^mailto:aesh\.03\.23@gmail\.com\?subject=Applied%20beta%20access%20request/;

test.describe("beta access notice", () => {
  test("the beta pill renders and expands into the beta details", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/");

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
    await expect(panel.getByText(/Google's OAuth test-user cap/i)).toBeVisible();

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("the email-admin action composes to the admin mailbox with the right subject", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /limited access/i }).click();

    const mailto = page.getByRole("link", { name: "Email admin for beta access" });
    await expect(mailto).toHaveAttribute("href", ADMIN_MAILTO);
    // It only composes an email — never a live navigation target.
    await expect(mailto).toHaveAttribute("href", /body=/);
  });

  test("the sample-inbox link routes to /demo/inbox", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /limited access/i }).click();

    await page
      .getByRole("region", { name: /beta access/i })
      .getByRole("link", { name: /try the sample inbox/i })
      .click();

    await expect(page).toHaveURL(/\/demo\/inbox$/);
    await expect(page.getByRole("heading", { name: "Sample inbox" })).toBeVisible();
  });

  test("the banner is dismissible and stays dismissed across reloads", async ({ page }) => {
    await page.goto("/");

    const toggle = page.getByRole("button", { name: /limited access/i });
    await expect(toggle).toBeVisible();

    await page.getByRole("button", { name: /dismiss beta notice/i }).click();
    await expect(toggle).toHaveCount(0);

    // Persisted in localStorage — still gone after a reload.
    await page.reload();
    await expect(
      page.getByRole("heading", { name: /lose the offer\. You lose the email/i }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /limited access/i })).toHaveCount(0);
  });

  test("no console errors and no horizontal overflow at 375px with the popover open", async ({
    page,
  }) => {
    const watch = startConsoleWatch(page);
    await page.setViewportSize(MOBILE_375);
    await page.goto("/");

    const toggle = page.getByRole("button", { name: /limited access/i });
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(page.getByRole("region", { name: /beta access/i })).toBeVisible();

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

