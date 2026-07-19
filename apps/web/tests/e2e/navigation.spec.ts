import { expect, test } from "@playwright/test";

import { startConsoleWatch } from "./helpers";

/**
 * E2E for route gating and honest degradation. The signed-in surfaces
 * (`/dashboard`, `/inbox`, `/settings`) must bounce an unauthenticated
 * visitor to `/login` rather than crashing or leaking shell UI. The public
 * sample inbox must load without auth.
 */
test.describe("route gating", () => {
  for (const path of ["/dashboard", "/inbox", "/settings"]) {
    test(`unauthenticated ${path} redirects to /login`, async ({ page }) => {
      const watch = startConsoleWatch(page);
      await page.goto(path);
      await expect(page).toHaveURL(/\/login/);
      await expect(page.getByRole("heading", { name: /sign in to jobtracker/i })).toBeVisible();
      expect(watch.errors, watch.errors.join("\n")).toEqual([]);
    });
  }

  test("the sample inbox is reachable without auth", async ({ page }) => {
    await page.goto("/demo/inbox");
    await expect(page).toHaveURL(/\/demo\/inbox$/);
    await expect(page.getByRole("heading", { name: "Sample inbox" })).toBeVisible();
  });
});
