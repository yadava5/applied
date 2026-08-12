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
   * The dashboard's own H1 — `exact` and `level` on purpose. This shell tree
   * once held a SECOND heading whose name contained "pipeline" (the retired
   * rail snapshot's h2), and Playwright's default role-name matching is
   * case-insensitive substring, so the loose form resolved to both — a
   * strict-mode violation that poisoned every geometry test in this describe
   * on its first CI run. The strict form stays: if a duplicate H1 ever
   * appears, it should fail the one assertion that counts things, not every
   * wait-for-load line.
   */
  const pageHeading = (page: Page) =>
    page.getByRole("heading", { level: 1, name: "Pipeline", exact: true });

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

  test("the pulse lives in the board's stage spine — exactly one copy in the tree", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/demo/shell");
    await expect(pageHeading(page)).toBeVisible();

    // One rendered pulse, inside the "Stages" aside — under the stage list,
    // where the owner pointed — and provably NOT in the shell rail (the
    // PR #122 slot, which the measured sidebar overflow retired) nor as a
    // display-none twin under the list (the pre-#122 duplicate).
    const pulse = page.getByTestId("pipeline-pulse");
    await expect(pulse).toHaveCount(1);
    await expect(
      page.locator('aside[aria-label="Stages"]').getByTestId("pipeline-pulse"),
    ).toBeVisible();
    await expect(
      page.locator('aside:has(nav[aria-label="Primary"])').getByTestId("pipeline-pulse"),
    ).toHaveCount(0);
    await expect(pulse.getByTestId("pulse-week")).toHaveCount(8);

    // Below lg the spine collapses into the chip strip and the pulse goes
    // with it — a deliberate choice (the phone dashboard leads with the
    // worklist; age/deadline tags on the cards carry the same ground truth),
    // not a hidden duplicate.
    await page.setViewportSize(MOBILE_375);
    await expect(pulse).toBeHidden();
    await expect(page.getByTestId("pipeline-pulse")).toHaveCount(1);
  });

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
    { path: "/dashboard", label: "Dashboard" },
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
    // ...and there is a way back into the rest of the app.
    await page.getByRole("link", { name: "Dashboard" }).click();
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
