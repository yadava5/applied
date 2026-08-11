import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375, startConsoleWatch } from "./helpers";

/**
 * E2E for the dashboard's content.
 *
 * The signed-in `/dashboard` is auth-gated and unreachable without a Supabase
 * session (see navigation.spec / shell.spec). But it renders from the SAME
 * `PipelineBoard` component as the public `/demo` twin — the header hierarchy,
 * the board with search/company-filter/expanders — fed by fixture rows adapted
 * to the exact API shape. So we drive that content on `/demo` here, and add a
 * skip-guarded pass that becomes real coverage of `/dashboard` itself the
 * moment the suite runs against a session.
 *
 * What is deliberately ABSENT is asserted too: the stat-tile row, the
 * classifier-context strip (auto-file gate / macro-F1 / CI floor), the
 * distribution bars and the recent-activity feed were removed from every
 * signed-in surface and from this twin — their reappearance is a regression.
 */

async function reachDashboardOrSkip(page: Page): Promise<void> {
  await page.goto("/dashboard");
  test.skip(
    /\/login/.test(page.url()),
    "no authenticated Supabase session in this environment — /dashboard is unreachable",
  );
}

test.describe("dashboard content (via the public /demo twin)", () => {
  test("the header is one honest line of state, and the board leads", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/demo");

    await expect(page.getByRole("heading", { name: "Pipeline" })).toBeVisible();
    // The one prose data line — 14 fixtures, 11 in motion (10 applied + 1
    // interviewing), 0 offers. The page's only rendering of the totals.
    await expect(page.getByText("14 filed · 11 in motion · 0 offers")).toBeVisible();

    // Board columns carry the per-stage counts (the fixtures are shaped like a
    // real early search: applied-heavy, offered honestly empty).
    await expect(page.getByRole("region", { name: /applied — 10/i })).toBeVisible();
    await expect(page.getByRole("region", { name: /interviewing — 1/i })).toBeVisible();
    await expect(page.getByRole("region", { name: /offered — 0/i })).toBeVisible();
    await expect(page.getByRole("region", { name: /closed — 3/i })).toBeVisible();
    await expect(page.getByText("none yet")).toBeVisible();

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("the metrics-poster surfaces stay dead: no tiles, no strip, no funnel, no feed", async ({
    page,
  }) => {
    await page.goto("/demo");
    await expect(page.getByRole("heading", { name: "Pipeline" })).toBeVisible();

    // Classifier internals belong to the landing/system card, never a board.
    await expect(page.getByText("auto-file gate", { exact: true })).toHaveCount(0);
    await expect(page.getByText("CI floor", { exact: true })).toHaveCount(0);
    // The one-category bar chart and the board-restating feed.
    await expect(page.getByText(/pipeline distribution/i)).toHaveCount(0);
    await expect(page.getByRole("heading", { name: /recent activity/i })).toHaveCount(0);
    // The stat-tile row's labels.
    await expect(page.getByText("in motion", { exact: true })).toHaveCount(0);
    await expect(page.getByText("this week", { exact: true })).toHaveCount(0);
  });

  test("a card is an application: role is the discriminator, company repeats", async ({ page }) => {
    await page.goto("/demo");

    // Northstar Systems holds three applications in two different columns.
    // (`exact` so the "2 more at Northstar Systems" chips don't also match.)
    await expect(page.getByText("Northstar Systems", { exact: true })).toHaveCount(3);
    await expect(page.getByText("ML Engineer", { exact: true })).toBeVisible();
    await expect(page.getByText("ML Engineer, Platform", { exact: true })).toBeVisible();
    await expect(page.getByText("Research Engineer, Applied ML", { exact: true })).toBeVisible();

    // The light same-company affordance filters the board to that employer.
    await page
      .getByRole("button", { name: /show all applications at Northstar Systems/i })
      .first()
      .click();
    await expect(page.getByText("3 of 14 shown")).toBeVisible();
    await expect(page.getByText("Harbor Analytics")).toHaveCount(0);
    // …and the filter chip clears it.
    await page.getByRole("button", { name: /stop filtering by Northstar Systems/i }).click();
    // (`exact` on every visible-company assertion: the interactive cards'
    // sr-only "Change stage for {company}" labels otherwise trip strict mode.)
    await expect(page.getByText("Harbor Analytics", { exact: true })).toBeVisible();
  });

  test("board search narrows by company or role, live", async ({ page }) => {
    await page.goto("/demo");

    const search = page.getByRole("searchbox", { name: /search the board/i });
    await search.fill("engineer, payments");
    await expect(page.getByText("1 of 14 shown")).toBeVisible();
    await expect(page.getByText("Copperline", { exact: true })).toBeVisible();
    await expect(page.getByText("Quarry Data")).toHaveCount(0);

    await search.fill("");
    await expect(page.getByText("Quarry Data", { exact: true })).toBeVisible();
  });

  test("a tall column expands on the page instead of scrolling inside it", async ({ page }) => {
    await page.goto("/demo");

    // 10 applied fixtures, 8 shown collapsed: the newest rows wait behind the
    // expander rather than behind a nested scrollbar.
    await expect(page.getByText("Waypoint Robotics")).toHaveCount(0);
    await page.getByRole("button", { name: "show all 10" }).click();
    await expect(page.getByText("Waypoint Robotics", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "show fewer" }).click();
    await expect(page.getByText("Waypoint Robotics")).toHaveCount(0);
  });

  test("no console errors and no horizontal overflow at 375px", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.setViewportSize(MOBILE_375);
    await page.goto("/demo");
    await expect(page.getByRole("heading", { name: "Pipeline" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });
});

test.describe("dashboard (signed in — needs a session)", () => {
  test("shows the pipeline header and a way to file an application", async ({ page }) => {
    await reachDashboardOrSkip(page);
    // Either populated (the board) or empty (the empty-state hero) — both must
    // offer the file-application entry point and never be a blank page.
    await expect(page.getByRole("button", { name: /file an application/i }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: /pipeline/i })).toBeVisible();
  });

  // The "Re-sync is retired" vocabulary guard lives in demo.spec.ts, where it
  // executes on every run — here it would sit behind a session skip CI can
  // never satisfy, which is a check that cannot fail.
});
