import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375, startConsoleWatch } from "./helpers";

/**
 * E2E for the dashboard's content.
 *
 * The signed-in `/dashboard` is auth-gated and unreachable without a Supabase
 * session (see navigation.spec / shell.spec). But it renders from the SAME
 * `PipelineBoard` component as the public `/demo` twin — the header hierarchy,
 * the stage spine, the grouped worklist with search/company-filter — fed by
 * fixture rows adapted to the exact API shape. So we drive that content on
 * `/demo` here, and add a skip-guarded pass that becomes real coverage of
 * `/dashboard` itself the moment the suite runs against a session.
 *
 * The board is a worklist now, not a kanban: stage groups render as regions
 * ONLY while they hold rows; an empty stage is a line in the spine (a button
 * named `${stage} — ${count}`), never a full-width box of nothing. The
 * `?pipeline=early` variant renders the measured production distribution —
 * every row in one stage — which is the case the worklist exists for and the
 * healthy seed spread cannot show.
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
  test("the header is one honest line of state, and the worklist leads", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/demo");

    await expect(page.getByRole("heading", { name: "Pipeline" })).toBeVisible();
    // The one prose data line — 17 fixtures, 14 in motion (10 applied + 4
    // interviewing), 0 offers. The page's only rendering of the totals.
    await expect(page.getByText("17 filed · 14 in motion · 0 offers")).toBeVisible();

    // Populated stages render as list groups, carrying their counts…
    await expect(page.getByRole("region", { name: /applied — 10/i })).toBeVisible();
    await expect(page.getByRole("region", { name: /interviewing — 4/i })).toBeVisible();
    await expect(page.getByRole("region", { name: /closed — 3/i })).toBeVisible();
    // …while the EMPTY stage renders no group at all: its emptiness is the
    // spine's one line, not a quarter of the screen.
    await expect(page.getByRole("region", { name: /offered/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "offered — 0" })).toBeVisible();

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("the spine is the stage lens: filtering to an empty stage says so", async ({ page }) => {
    await page.goto("/demo");

    await page.getByRole("button", { name: "offered — 0" }).click();
    // The selected stage renders its (empty) group with the honest copy…
    await expect(page.getByRole("region", { name: /offered — 0/i })).toBeVisible();
    await expect(page.getByText("none yet")).toBeVisible();
    // …and other groups leave the list while the lens is narrowed.
    await expect(page.getByRole("region", { name: /applied — 10/i })).toHaveCount(0);

    // Pressing the active stage again returns to the whole pipeline.
    await page.getByRole("button", { name: "offered — 0" }).click();
    await expect(page.getByRole("region", { name: /applied — 10/i })).toBeVisible();
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

  test("a row is an application: role is the discriminator, company repeats", async ({ page }) => {
    await page.goto("/demo");

    // Northstar Systems holds three applications in two different stages.
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
    await expect(page.getByText("3 of 17 shown")).toBeVisible();
    await expect(page.getByText("Harbor Analytics")).toHaveCount(0);
    // …and the filter chip clears it.
    await page.getByRole("button", { name: /stop filtering by Northstar Systems/i }).click();
    // (`exact` on every visible-company assertion: the interactive rows'
    // sr-only "Change stage for {company}" labels otherwise trip strict mode.)
    await expect(page.getByText("Harbor Analytics", { exact: true })).toBeVisible();
  });

  test("board search narrows by company or role, live", async ({ page }) => {
    await page.goto("/demo");

    const search = page.getByRole("searchbox", { name: /search the board/i });
    await search.fill("engineer, payments");
    await expect(page.getByText("1 of 17 shown")).toBeVisible();
    await expect(page.getByText("Copperline", { exact: true })).toBeVisible();
    await expect(page.getByText("Quarry Data")).toHaveCount(0);

    await search.fill("");
    await expect(page.getByText("Quarry Data", { exact: true })).toBeVisible();
  });

  test("the whole worklist is present — no expander, no nested scroll on the flow twin", async ({
    page,
  }) => {
    await page.goto("/demo");

    // Every applied row renders immediately (the old board held the newest two
    // behind a "show all 10" expander); the page is the one scroll context on
    // the flow twin, so nothing waits behind a control or an inner scrollbar.
    await expect(page.getByText("Waypoint Robotics", { exact: true })).toBeVisible();
    await expect(page.getByText("Copperline", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /show all \d+/ })).toHaveCount(0);
  });

  test("the early-search distribution renders deliberately, not as three empty boxes", async ({
    page,
  }) => {
    const watch = startConsoleWatch(page);
    // `?pipeline=early` is the measured production shape: every live row in
    // one stage (the real account is 29-0-0-0). This is the distribution the
    // worklist redesign exists for.
    await page.goto("/demo?pipeline=early");

    await expect(page.getByText("17 filed · 17 in motion · 0 offers")).toBeVisible();
    // One populated group…
    await expect(page.getByRole("region", { name: /applied — 17/i })).toBeVisible();
    // …and the three empty stages are spine lines, not rendered groups.
    for (const name of ["interviewing — 0", "offered — 0", "closed — 0"]) {
      await expect(page.getByRole("button", { name })).toBeVisible();
    }
    await expect(page.getByRole("region", { name: /interviewing/i })).toHaveCount(0);
    await expect(page.getByRole("region", { name: /closed/i })).toHaveCount(0);

    // The role slot holds its shape at the real board's density: this variant
    // blanks roughly the production share of roles (8 of 29 live rows), and
    // each prints the honest placeholder instead of shortening its row.
    expect(await page.getByText("role not captured", { exact: true }).count()).toBeGreaterThan(2);

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
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
    // Either populated (the worklist) or empty (the empty-state hero) — both
    // must offer the file-application entry point and never be a blank page.
    await expect(page.getByRole("button", { name: /file an application/i }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: /pipeline/i })).toBeVisible();
  });

  test("the dashboard is viewport-locked at desktop: the page itself does not scroll", async ({
    page,
  }) => {
    await reachDashboardOrSkip(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    // The shell is h-dvh with the worklist as the one scroll region — the
    // document never grows past the viewport (complaint: "the dashboard means
    // it's the screen size and doesn't scroll").
    const heights = await page.evaluate(() => ({
      scroll: document.documentElement.scrollHeight,
      client: document.documentElement.clientHeight,
    }));
    expect(heights.scroll).toBeLessThanOrEqual(heights.client + 1);
  });

  // The "Re-sync is retired" vocabulary guard lives in demo.spec.ts, where it
  // executes on every run — here it would sit behind a session skip CI can
  // never satisfy, which is a check that cannot fail.
});
