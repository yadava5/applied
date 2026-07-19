import { expect, test } from "@playwright/test";

import {
  expectNoHorizontalOverflow,
  MOBILE_375,
  startConsoleWatch,
} from "./helpers";

/**
 * E2E for the beta-access notice and the privacy positioning.
 *
 * The rich <BetaCard> lives on /settings and the not-connected /inbox, which
 * are auth-gated and unreachable without a session — so these specs exercise
 * the publicly reachable surfaces: the dismissible site-wide banner (whose
 * popover carries the same verified copy + actions as the card) and the
 * landing's privacy section.
 */

// encodeURIComponent("JobTracker beta access request") === "JobTracker%20beta%20access%20request"
const ADMIN_MAILTO =
  /^mailto:aesh\.03\.23@gmail\.com\?subject=JobTracker%20beta%20access%20request/;

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
    await expect(panel.getByText(/100 beta testers/i)).toBeVisible();
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
      page.getByRole("heading", { name: /Your inbox already holds the verdict/i }),
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

test.describe("privacy positioning (landing)", () => {
  test("the privacy section renders with the verified claims", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: /your inbox stays yours/i }),
    ).toBeVisible();

    // The three verified pillars.
    await expect(page.getByRole("heading", { name: /no llm reads your mail/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /it can run in your browser/i })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /read-only, by construction/i }),
    ).toBeVisible();

    // Load-bearing, code-verified facts — scoped to the privacy section so the
    // landing's other mentions of the same strings don't trip strict mode.
    const section = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: /your inbox stays yours/i }) });
    await expect(section.getByText(/gmail\.readonly/)).toBeVisible();
    await expect(section.getByText(/allowRemoteModels = false/)).toBeVisible();
    await expect(section.getByText(/never handed to one/i)).toBeVisible();
    await expect(section.getByText(/22\.8 MB/)).toBeVisible();
  });

  test("the on-device link routes to the sample inbox", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /see it classify on-device/i }).click();
    await expect(page).toHaveURL(/\/demo\/inbox$/);
  });
});
