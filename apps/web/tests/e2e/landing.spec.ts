import { expect, test } from "@playwright/test";

import {
  expectNoHorizontalOverflow,
  MOBILE_375,
  startConsoleWatch,
} from "./helpers";

/**
 * E2E for the marketing landing (`/`). Confirms the narrative renders, the
 * primary navigation controls actually route, and the page is clean + mobile
 * safe. Copy assertions are kept to load-bearing phrases so wording tweaks
 * don't turn CI red.
 */
test.describe("landing (/)", () => {
  test("renders the hero and is free of console errors", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: /Your inbox already holds the verdict/i }),
    ).toBeVisible();

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("primary CTA routes to the live demo", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /Enter the live demo/i }).click();
    await expect(page).toHaveURL(/\/demo$/);
  });

  test("the Sample inbox door routes to /demo/inbox", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /^Sample inbox/i }).click();
    await expect(page).toHaveURL(/\/demo\/inbox$/);
    await expect(page.getByRole("heading", { name: "Sample inbox" })).toBeVisible();
  });

  test("the in-narrative sample-inbox CTA routes to /demo/inbox", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /See it label a full sample inbox/i }).click();
    await expect(page).toHaveURL(/\/demo\/inbox$/);
  });

  test("the Sign in nav control routes to /login", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /^Sign in$/i }).click();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("no horizontal overflow at 375px", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.setViewportSize(MOBILE_375);
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: /Your inbox already holds the verdict/i }),
    ).toBeVisible();
    await expectNoHorizontalOverflow(page);
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });
});
