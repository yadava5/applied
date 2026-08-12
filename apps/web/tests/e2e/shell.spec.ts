import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375, startConsoleWatch } from "./helpers";

/**
 * E2E for the authed app shell: the sidebar active-state indicator, the mobile
 * navigation menu, and `/import` rendering INSIDE the shell for a signed-in
 * user (so it is never a dead end).
 *
 * The shell only renders for an authenticated Supabase session, which this
 * suite can't stand up (see `connect.spec.ts` / `beta.spec.ts` for the same
 * constraint). So the shell assertions below `test.skip` themselves when a
 * visit to `/dashboard` bounces to `/login` — they become real coverage the
 * moment the suite runs against a session (locally or in a seeded CI), and
 * never turn red in the meantime. The signed-OUT half of the `/import`
 * dual-mode split IS driven here, since that is publicly reachable.
 */

/** Skip the current test unless a real session lets us reach the app shell. */
async function requireSession(page: Page): Promise<void> {
  await page.goto("/dashboard");
  test.skip(
    /\/login/.test(page.url()),
    "no authenticated Supabase session in this environment — shell is unreachable",
  );
}

/**
 * The shell's GEOMETRY, measured on /demo/shell — a public fixture route that
 * mounts the REAL primitives (`AppShellFrame`, `LOCKED_PAGE_CLASS`,
 * `PipelineBoard variant="locked"`), not a copy of their class names, over
 * the demo fixture store. That is what makes the headline claim of the
 * signed-in redesign — "the document never scrolls" — executable in every
 * environment: the previous assertion lived only behind a session skip
 * (dashboard.spec.ts) and had never run.
 *
 * Mutation-tested at introduction (headless Chromium, measured 2026-08-12):
 *   - `h-dvh overflow-hidden` removed from `AppShellFrame` → the document
 *     lock goes red at all three widths (doc scrollHeight/clientHeight:
 *     1089/800, 1327/768, 1979/812); restored → 800/800, 768/768, 812/812.
 *   - the wrapper's `lg:has-[.page-locked]:min-h-0` removed → the document
 *     lock still PASSES (800/800) while <main> scrolls (1033/744) and the
 *     worklist loses its internal scroll (834/834) — the exact "dashboard
 *     still scrolls" failure shipped before, which is why the pane and
 *     overflow assertions below exist and are the load-bearing half.
 */
test.describe("app shell — viewport lock (via /demo/shell, executes without a session)", () => {
  /** Document-level lock: the page body never scrolls, at any width. */
  const docHeights = (page: Page) =>
    page.evaluate(() => ({
      scroll: document.documentElement.scrollHeight,
      client: document.documentElement.clientHeight,
    }));

  /**
   * The dashboard's own H1 — "Applications", rendered by the shell's TOP BAR
   * (the board page surrendered its in-page header row to the worklist, so
   * the route title in the bar is the page heading now). `exact` and `level`
   * on purpose: this shell tree once held a SECOND heading whose name
   * contained the page word (the retired rail snapshot's h2), and
   * Playwright's default role-name matching is case-insensitive substring, so
   * the loose form resolved to both — a strict-mode violation that poisoned
   * every geometry test in this describe on its first CI run. The strict form
   * stays: if a duplicate H1 ever appears, it should fail the one assertion
   * that counts things, not every wait-for-load line.
   */
  const pageHeading = (page: Page) =>
    page.getByRole("heading", { level: 1, name: "Applications", exact: true });

  for (const viewport of [
    { width: 1280, height: 800 },
    { width: 1024, height: 768 }, // the lg boundary itself — the lock's smallest desktop
    { width: 375, height: 812 }, // below lg the PAGE flows inside <main>; the document still must not
  ]) {
    test(`the document itself never scrolls at ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      const watch = startConsoleWatch(page);
      await page.setViewportSize(viewport);
      await page.goto("/demo/shell");
      await expect(pageHeading(page)).toBeVisible();

      const doc = await docHeights(page);
      expect(
        doc.scroll,
        `document scrolls: scrollHeight=${doc.scroll} > clientHeight=${doc.client}`,
      ).toBeLessThanOrEqual(doc.client + 1);
      await expectNoHorizontalOverflow(page);
      expect(watch.errors, watch.errors.join("\n")).toEqual([]);
    });
  }

  for (const viewport of [
    { width: 1280, height: 800 },
    { width: 1280, height: 720 }, // the tightest common laptop pane
  ]) {
    test(`at ${viewport.width}×${viewport.height} the worklist is the ONE scroll pane — everything else holds still`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await page.goto("/demo/shell");
      await expect(pageHeading(page)).toBeVisible();

      // <main> fits its content exactly: header, notices and spine hold still.
      // This is the assertion that catches the failure the document-level lock
      // cannot — a broken min-h-0 chain scrolls the whole pane (SyncBar and
      // all), which reads as "the dashboard still scrolls" even while the
      // document technically holds.
      const main = await page
        .locator("main")
        .evaluate((el) => ({ scroll: el.scrollHeight, client: el.clientHeight }));
      expect(
        main.scroll,
        `the shell pane scrolls: scrollHeight=${main.scroll} > clientHeight=${main.client}`,
      ).toBeLessThanOrEqual(main.client + 1);

      // NO other inner pane scrolls either — the first screen is still. This
      // is the assertion PR #122 lacked: its rail-mounted pulse made the sidebar
      // itself scroll (744px of column in a 537–717px middle pane at every
      // common laptop height) while the document- and main-level locks passed,
      // which the owner read — correctly — as "the dashboard still scrolls".
      const rogue = await page.evaluate(() => {
        const offenders: string[] = [];
        for (const el of Array.from(document.querySelectorAll("*"))) {
          const oy = getComputedStyle(el).overflowY;
          if (
            (oy === "auto" || oy === "scroll") &&
            el.scrollHeight > el.clientHeight + 1 &&
            el.getAttribute("data-testid") !== "worklist-pane"
          ) {
            offenders.push(
              `${el.tagName.toLowerCase()}[${
                el.getAttribute("data-testid") ?? el.getAttribute("aria-label") ?? el.className
              }] ${el.scrollHeight}>${el.clientHeight}`,
            );
          }
        }
        return offenders;
      });
      expect(rogue, `inner panes scroll besides the worklist: ${rogue.join(", ")}`).toEqual([]);

      // …and the lock is load-bearing, not satisfied by everything fitting:
      // the fixture worklist genuinely overflows and scrolls itself.
      const list = await page
        .getByTestId("worklist-pane")
        .evaluate((el) => ({ scroll: el.scrollHeight, client: el.clientHeight }));
      expect(
        list.scroll,
        `the worklist does not overflow (scrollHeight=${list.scroll}, clientHeight=${list.client}) — the lock is being asserted against nothing`,
      ).toBeGreaterThan(list.client + 1);
    });
  }

  test("the pulse is the board's full-width band — exactly one copy in the tree", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/demo/shell");
    await expect(pageHeading(page)).toBeVisible();

    // One rendered pulse, as a full-width band in the BOARD's own tree —
    // the dashboard's content area, where the owner keeps putting it back.
    // Both left-column homes are closed and provably empty of it: the stage
    // spine (#136, rejected) and the shell rail (PR #122, retired for
    // measured sidebar overflow). No display-none twin anywhere.
    const pulse = page.getByTestId("pipeline-pulse");
    await expect(pulse).toHaveCount(1);
    await expect(page.getByTestId("pipeline-board").getByTestId("pipeline-pulse")).toBeVisible();
    await expect(
      page.locator('aside[aria-label="Stages"]').getByTestId("pipeline-pulse"),
    ).toHaveCount(0);
    await expect(
      page.locator('aside:has(nav[aria-label="Primary"])').getByTestId("pipeline-pulse"),
    ).toHaveCount(0);
    await expect(pulse.getByTestId("pulse-week")).toHaveCount(8);

    // A BAND, not a column: it spans the board. A pulse that fits in a spine
    // again would pass every locator above and still be the rejected layout.
    const bandBox = await pulse.boundingBox();
    const boardBox = await page.getByTestId("pipeline-board").boundingBox();
    expect(bandBox?.width ?? 0).toBeGreaterThan((boardBox?.width ?? 1) * 0.9);

    // Same idea for the page heading: exactly ONE <h1> node in the DOM, not
    // one visible and one CSS-hidden. A hidden twin already shipped once
    // (TopBar kept rendering its copy under `lg:hidden` while the header row
    // rendered the visible one) — a duplicate document outline for screen
    // readers, and the exact two-nodes-one-hidden shape that produces
    // strict-mode locator failures. Counted at both breakpoints because the
    // twin only existed on one side of `lg`.
    await expect(page.locator("h1")).toHaveCount(1);

    // Below lg the band yields — a deliberate choice (the phone dashboard
    // leads with the worklist; age/deadline tags on the cards carry the same
    // ground truth), not a hidden duplicate.
    await page.setViewportSize(MOBILE_375);
    await expect(pulse).toBeHidden();
    await expect(page.getByTestId("pipeline-pulse")).toHaveCount(1);
    await expect(page.locator("h1")).toHaveCount(1);
  });

  test("the rail carries the nav rename and the board's stage lens + search", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/demo/shell");
    await expect(pageHeading(page)).toBeVisible();

    // The nav label is asserted HERE, where the sidebar renders without a
    // session — inside the session-gated describe below it was a check that
    // could not fail, guarding a rename CI never executed.
    await expect(
      page
        .locator('nav[aria-label="Primary"]')
        .getByRole("link", { name: "Applications", exact: true }),
    ).toBeVisible();

    // The stage lens lives in the rail's middle run (portaled by the board —
    // one state owner), with search above it: filters are route-local
    // navigation, and this is the void the owner pointed at.
    const lens = page.getByRole("group", { name: "Stages" });
    await expect(lens).toBeVisible();
    await expect(lens.getByRole("button", { name: "applied — 10" })).toBeVisible();
    await expect(lens.getByRole("searchbox", { name: /search the board/i })).toBeVisible();
    // …and the in-board spine is gone with it: the worklist owns the full
    // measure. (The chip strip still exists for below-`md`, CSS-picked — the
    // same both-in-DOM shape the chips/spine pair always had.)
    await expect(page.locator('aside[aria-label="Stages"]')).toHaveCount(0);

    // Filtering through the rail drives the same board.
    await lens.getByRole("button", { name: "interviewing — 4" }).click();
    await expect(page.getByRole("region", { name: /interviewing — 4/i })).toBeVisible();
    await expect(page.getByRole("region", { name: /applied — 10/i })).toHaveCount(0);
  });

  test("a sync reports without moving the board: idle → checking → result", async ({ page }) => {
    // The owner watched the whole page jump when "checking Gmail…" appeared.
    // The status now takes over the subtitle's slot in the header row for
    // exactly as long as it speaks, so the three routine states share one
    // geometry — asserted against the worklist pane, the thing that moved.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/demo/shell");
    await expect(pageHeading(page)).toBeVisible();

    const list = page.getByTestId("worklist-pane");
    const status = page.locator("[data-sync-surface]").getByRole("status");
    const idle = await list.boundingBox();

    await page.getByRole("button", { name: "Sync new mail from Gmail" }).click();
    await expect(status).toContainText("checking Gmail");
    const checking = await list.boundingBox();

    await expect(status).toContainText("2 filed, 3 already known");
    const settled = await list.boundingBox();

    expect(
      Math.abs((checking?.y ?? 0) - (idle?.y ?? 0)),
      "the board moved when the checking line appeared",
    ).toBeLessThanOrEqual(1);
    expect(
      Math.abs((settled?.y ?? 0) - (idle?.y ?? 0)),
      "the board moved when the sync result appeared",
    ).toBeLessThanOrEqual(1);
    expect(
      Math.abs((settled?.height ?? 0) - (idle?.height ?? 0)),
      "the worklist pane changed height across the sync",
    ).toBeLessThanOrEqual(1);
  });

  /**
   * The floor the band's return must never eat through: the worklist's own
   * viewport share. The document-lock gate CANNOT catch this failure —
   * `h-dvh overflow-hidden` plus the min-h-0 chain is structural, so chrome
   * that overspends its budget doesn't scroll the page; it silently shrinks
   * the one region the dashboard exists to show, with every geometry test
   * green. The floors are measured on /demo/shell (recorded 2026-08-12,
   * `next start`, headless Chrome, after the header row replaced the top bar
   * and the stage lens moved to the rail): worklist-pane clientHeight 652 at
   * 1280×800, 572 at 1280×720, 592 at 1024×768 (the demo pill wraps the
   * header to two lines at that width; the signed-in row holds one). A small
   * tolerance absorbs sub-pixel/font drift; a real regression (a fatter
   * band, a second header row, a reinstated notice line) costs tens of
   * pixels and lands far below it.
   */
  for (const { viewport, floor } of [
    { viewport: { width: 1280, height: 800 }, floor: 645 },
    { viewport: { width: 1280, height: 720 }, floor: 565 },
    { viewport: { width: 1024, height: 768 }, floor: 585 },
  ]) {
    test(`the worklist keeps its viewport share at ${viewport.width}×${viewport.height}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await page.goto("/demo/shell");
      await expect(pageHeading(page)).toBeVisible();

      const client = await page.getByTestId("worklist-pane").evaluate((el) => el.clientHeight);
      expect(
        client,
        `the worklist pane shrank to ${client}px (floor ${floor}px) — some chrome above it is spending the list's pixels`,
      ).toBeGreaterThanOrEqual(floor);
    });
  }

  test("light theme: still locked, still no horizontal overflow at 375", async ({ page }) => {
    // `jt-theme` is THEME_STORAGE_KEY (lib/theme.ts) — hardcoded here because
    // the e2e specs deliberately import nothing from the app source tree.
    await page.addInitScript(() => {
      try {
        localStorage.setItem("jt-theme", "light");
      } catch {
        /* storage unavailable — the default theme still exercises the layout */
      }
    });
    await page.setViewportSize(MOBILE_375);
    await page.goto("/demo/shell");
    await expect(pageHeading(page)).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    const doc = await docHeights(page);
    expect(doc.scroll).toBeLessThanOrEqual(doc.client + 1);
    await expectNoHorizontalOverflow(page);
  });
});

test.describe("app shell — signed out (public)", () => {
  test("/import renders the standalone page, not the app shell, and offers a way home", async ({
    page,
  }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/import");
    await expect(page).toHaveURL(/\/import$/);
    await expect(page.getByRole("heading", { name: "Import your mail" })).toBeVisible();

    // No signed-in app chrome for an anonymous visitor.
    await expect(page.locator('nav[aria-label="Primary"]')).toHaveCount(0);
    await expect(page.getByRole("button", { name: /sign out/i })).toHaveCount(0);

    // But never a dead end: the header logo goes home and the sample inbox is
    // linked from the standalone header.
    const header = page.locator("header");
    // Matches the current brand. This asserted /job.*tracker/i until 2026-08-03,
    // which was the pre-rename name — the product has been "Applied" since, so
    // the test was failing against correct markup.
    await expect(header.getByRole("link", { name: /applied/i })).toHaveAttribute("href", "/");
    await expect(header.getByRole("link", { name: /sample inbox/i })).toHaveAttribute(
      "href",
      "/demo/inbox",
    );
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });
});

test.describe("app shell — signed in (needs a session)", () => {
  for (const { path, label } of [
    { path: "/dashboard", label: "Applications" },
    { path: "/inbox", label: "Inbox" },
    { path: "/settings", label: "Settings" },
  ]) {
    test(`the sidebar marks "${label}" as the current page on ${path}`, async ({ page }) => {
      await requireSession(page);
      await page.goto(path);

      const current = page.locator('a[aria-current="page"]');
      await expect(current).toContainText(label);
      // Exactly one item is current at a time.
      await expect(current).toHaveCount(1);
    });
  }

  test("/import renders inside the shell with 'Import mail' active, and nav can leave it", async ({
    page,
  }) => {
    await requireSession(page);
    await page.goto("/import");

    // The app sidebar is present and "Import mail" is the current item.
    const sidebar = page.locator('aside nav[aria-label="Primary"]');
    await expect(sidebar).toBeVisible();
    const current = page.locator('a[aria-current="page"]');
    await expect(current).toContainText("Import mail");

    // The import tool itself is here...
    await expect(page.getByRole("heading", { name: "Import your mail" })).toBeVisible();
    // ...and there is a way back into the rest of the app. `exact`: the brand
    // logo's own aria-label ("…go to your applications") substring-matches
    // the loose form now that the nav item is named "Applications".
    await page.getByRole("link", { name: "Applications", exact: true }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
  });

  test("mobile: the hamburger reveals the primary nav so there is always a way back", async ({
    page,
  }) => {
    await page.setViewportSize(MOBILE_375);
    await requireSession(page);
    await page.goto("/dashboard");

    // The desktop sidebar is hidden; the menu button is the way in.
    const menuButton = page.getByRole("button", { name: /open navigation menu/i });
    await expect(menuButton).toBeVisible();

    await menuButton.click();
    const mobileNav = page.locator("#mobile-nav");
    await expect(mobileNav).toBeVisible();
    await expect(mobileNav.getByRole("link", { name: "Inbox" })).toBeVisible();
    await expect(mobileNav.getByRole("link", { name: "Settings" })).toBeVisible();

    await expectNoHorizontalOverflow(page);

    // Tapping a destination navigates and closes the menu.
    await mobileNav.getByRole("link", { name: "Settings" }).click();
    await expect(page).toHaveURL(/\/settings$/);
  });
});
