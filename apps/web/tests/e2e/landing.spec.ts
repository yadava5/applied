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

  // The CountUp island rolls each proof stat up from zero the first time it
  // scrolls into view. This guards that it always SETTLES on the true value —
  // the failure mode that (in its at/above-fold form) stranded the beta seat
  // cap at 0. Each tile is located by its description, then asserted to carry
  // its real, code-verified number once animated.
  test("the proof stats count up and settle on their true values", async ({ page }) => {
    await page.goto("/");

    const tile = (description: string | RegExp) =>
      page
        .locator("div")
        .filter({ has: page.getByText(description) })
        .filter({ hasText: /\d/ })
        .last();

    const floor = tile("the merge fails below it");
    await floor.scrollIntoViewIfNeeded();
    await expect(floor).toContainText("0.95");

    const tests = tile("tests in the backend suite");
    await tests.scrollIntoViewIfNeeded();
    await expect(tests).toContainText("182");

    const classes = tile(/8 predicted \+ needs_review/);
    await classes.scrollIntoViewIfNeeded();
    await expect(classes).toContainText("9");
  });
});
