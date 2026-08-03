import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375, startConsoleWatch } from "./helpers";

/**
 * E2E for the dashboard's content.
 *
 * The signed-in `/dashboard` is auth-gated and unreachable without a Supabase
 * session (see navigation.spec / shell.spec). But it renders from the SAME
 * components as the public `/demo` twin — StatTiles, the classifier-context
 * strip, the pipeline funnel + board, and recent activity — fed by fixture
 * rows adapted to the exact API shape. So we drive that content on `/demo`
 * here, and add a skip-guarded pass that becomes real coverage of `/dashboard`
 * itself the moment the suite runs against a session.
 */

async function reachDashboardOrSkip(page: Page): Promise<void> {
  await page.goto("/dashboard");
  test.skip(
    /\/login/.test(page.url()),
    "no authenticated Supabase session in this environment — /dashboard is unreachable",
  );
}

test.describe("dashboard content (via the public /demo twin)", () => {
  test("renders the headline stat tiles with real values", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/demo");

    await expect(page.getByText("applications", { exact: true })).toBeVisible();
    await expect(page.getByText("this week", { exact: true })).toBeVisible();
    await expect(page.getByText("in motion", { exact: true })).toBeVisible();
    await expect(page.getByText("offers", { exact: true })).toBeVisible();
    // The 10 fixture applications drive the total tile.
    await expect(page.getByText("10", { exact: true }).first()).toBeVisible();

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("shows the classifier-context strip with the honest gate/F1/CI numbers", async ({ page }) => {
    await page.goto("/demo");
    await expect(page.getByText("auto-file gate", { exact: true })).toBeVisible();
    await expect(page.getByText("0.85", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("macro-F1", { exact: true })).toBeVisible();
    await expect(page.getByText("0.979", { exact: true })).toBeVisible();
    await expect(page.getByText("CI floor", { exact: true })).toBeVisible();
  });

  test("renders the pipeline funnel and status board", async ({ page }) => {
    await page.goto("/demo");
    await expect(page.getByText(/pipeline distribution · 10 applications/i)).toBeVisible();
    await expect(page.getByText(/advanced past applied/i)).toBeVisible();
    // Board columns and a representative card.
    await expect(page.getByRole("region", { name: /offered — 1/i })).toBeVisible();
    await expect(page.getByText("Beacon Health")).toBeVisible();
  });

  test("renders the recent-activity feed", async ({ page }) => {
    await page.goto("/demo");
    await expect(page.getByRole("heading", { name: /recent activity/i })).toBeVisible();
    await expect(page.getByText(/latest 5/i)).toBeVisible();
    // The most recently filed fixture application leads the feed.
    await expect(page.getByText(/Copperline/).first()).toBeVisible();
  });

  test("no console errors and no horizontal overflow at 375px", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.setViewportSize(MOBILE_375);
    await page.goto("/demo");
    await expect(page.getByText("in motion", { exact: true })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });
});

test.describe("dashboard (signed in — needs a session)", () => {
  test("shows the stat tiles and a way to file an application", async ({ page }) => {
    await reachDashboardOrSkip(page);
    // Either populated (stat tiles) or empty (the empty-state hero) — both must
    // offer the file-application entry point and never be a blank page.
    await expect(page.getByRole("button", { name: /file an application/i }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: /pipeline/i })).toBeVisible();
  });
});
