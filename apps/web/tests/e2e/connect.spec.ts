import { expect, test } from "@playwright/test";

import { startConsoleWatch } from "./helpers";

/**
 * E2E for the Gmail connect flow's honest failure handling and for the
 * no-connection import fallback being surfaced where it should be.
 *
 * The authed connect states (a signed-in tester actually reaching Google
 * consent) need a real Supabase session and a configured backend, which the
 * suite can't stand up — those are reasoned about, not driven here. What we
 * CAN prove without a session is that the unauthenticated connect entry point
 * does not dead-end: it routes to sign-in rather than to a misleading
 * "not enabled" page or a raw error.
 */

test.describe("Gmail connect — honest degradation", () => {
  test("unauthenticated /api/gmail/authorize routes to sign-in, not an error", async ({ page }) => {
    const watch = startConsoleWatch(page);
    const response = await page.goto("/api/gmail/authorize");
    // Ends on the login page, carrying a redirect back to settings.
    await expect(page).toHaveURL(/\/login/);
    expect(response?.url() ?? page.url()).toMatch(/redirect=%2Fsettings|redirect=\/settings/);
    await expect(page.getByRole("heading", { name: /sign in to jobtracker/i })).toBeVisible();
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("the landing try-it area surfaces the no-connection import path", async ({ page }) => {
    await page.goto("/");
    const importLink = page.getByRole("link", { name: /import your mail/i }).first();
    await expect(importLink).toHaveAttribute("href", "/import");
    // Landing links to the live app open in a new tab (the landing standard),
    // so the import path is proven by the popup it opens.
    const [popup] = await Promise.all([page.waitForEvent("popup"), importLink.click()]);
    await expect(popup).toHaveURL(/\/import$/);
    await expect(popup.getByRole("heading", { name: "Import your mail" })).toBeVisible();
  });
});
