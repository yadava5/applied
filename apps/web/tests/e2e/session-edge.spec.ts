import { expect, test, type Page } from "@playwright/test";

/**
 * The board's session edge, and the one geometry claim #172 rests on: the
 * header row holds ONE line at the owner's own width.
 *
 * WHY THIS FILE EXISTS AT ALL. #172 moved `Sign out` off the header row and
 * into that row's `⋯` menu because the row-level button (~97px) wrapped the
 * row to two lines at 1024 and spent the difference out of the worklist — the
 * one region the dashboard exists to show. The change touched six components
 * and could not be gated by anything here: `/demo/shell` is the only surface
 * that mounts the signed-in shell without a session, and it deliberately
 * renders `DemoFixturePill` at exactly the spot the real page renders its
 * session edge (`DemoDashboard`'s `trailing`). So the twin did not contain
 * the thing the change changed, and every gate in the repo could stay green
 * across it in both directions. `/demo/shell?session=1` closes that hole: it
 * mounts the real pair the signed-in page passes to `SyncBar` (`withSignOut`
 * on, `trailing` unset). The knob is declared in that route's own doc comment
 * beside `?review=N` and `?queue=`, and nothing links to it.
 *
 * WHAT "ONE LINE" IS MEASURED AS, and why not a pixel number. A hardcoded
 * height (the wrapped row measured 82px) is a magic number that goes stale
 * the first time a control's padding or the type scale moves, and it cannot
 * say WHICH way it failed. Two structural measures are asserted instead, both
 * derived from the row's own flex behaviour:
 *
 *   1. Distinct child CENTRES. The row is `flex flex-wrap items-center`, so
 *      every item on one flex line shares that line's centre — regardless of
 *      how tall each item is (an `<h1>` at 20px and the Sync button at 38px
 *      sit on one line with different `top`s but the SAME centre, which is
 *      why centres and not tops). One flex line ⇒ one cluster of centres; a
 *      wrap ⇒ two, separated by roughly a line box. Clustered at 2px to
 *      absorb sub-pixel rounding.
 *   2. The row's height against its TALLEST laid-out child. The row carries
 *      no padding of its own, so unwrapped those are equal by construction;
 *      wrapped it is at least the second line plus the 8px `gap-y-2`.
 *
 * Both are reported with every child's box in the failure message, together
 * with each child's flex-basis and what the children sum to AS LAID OUT — a
 * grown flex child (the ledger chip) has already absorbed the row's slack by
 * the time it is measured, so that sum is a description of the arrangement,
 * NOT the row's deficit. The basis column is the one to read when asking
 * whether something fits: line breaking happens on hypothetical sizes, before
 * any growing or shrinking.
 *
 * Children with `position: absolute` are excluded: the row's status region is
 * a persistent live region wearing `sr-only` while silent, i.e. a 1×1 absolute
 * box that is in no flex line at all and whose centre is meaningless here.
 *
 * BOTH WIDTHS. 1024×768 is the primary case — it is the owner's own window
 * width and the `lg` boundary, where this row first becomes the screen's top
 * line (TopBar yields on the board route) and where the wrap was reported.
 * 1280×800 is asserted too because the row and the band change shape at `xl`;
 * a fix that only holds at the width it was measured at is the recurring
 * defect here, not a fix.
 *
 * PROVED ABLE TO FAIL, not assumed. The same assertions, from the same
 * helpers byte-for-byte, were run against `origin/main`'s shape — main's
 * session edge (the row-level `SignOutButton`) mounted through the same knob
 * in a detached worktree, headless Chromium, `next build && next start`,
 * 2026-08-13:
 *
 *     main @1024×768   2 lines, row 82px  (h1 75.95 · subtitle 159.13 ·
 *                      ledger basis 160 · controls 244.45 · sign-out 84.52,
 *                      12px gaps — the button and its gap are 96.52 of the
 *                      736px the row has)
 *     branch @1024×768 1 line,  row 38px
 *     both @1280×800   1 line,  row 38px — the width where it never wrapped,
 *                      which is why 1024 is the case that had to be gated
 *
 * Before the assertion runs it is positively controlled on that rig: main's
 * row-level sign-out must be present AND visible in the row, or the knob has
 * mounted the wrong shape and a red reading would mean nothing. A spec that
 * has never been shown red is a check that cannot fail, which is the defect
 * this repo keeps finding.
 *
 * WHAT THIS DOES NOT GATE, stated plainly. The twin's row has more slack than
 * the owner's: the fixture Gmail state has never synced, so the recency slot
 * reads "not synced yet" (75.64px) where his reads "synced N minutes ago"
 * (115.17px at 3 minutes, 122.33px at 59). At 1024 the ledger chip grows into
 * 220.47px of slack here; with the live phrase swapped into this rig's DOM —
 * a diagnostic, rendered on no surface, so do not expect to reproduce it — it
 * grows into 180.94px, i.e. the owner's row clears one line by roughly 21px
 * where this one clears it by roughly 60. So this file gates the ARRANGEMENT —
 * no row-level session control, sign-out reachable in the menu, one line —
 * and it would still pass a future regression that spent 30px of the row. A
 * budget assertion on the live row needs a session and belongs with the specs
 * that have one.
 */

/** The knob. `?session=1` = the signed-in session edge on the fixture twin. */
const SESSION_TWIN = "/demo/shell?session=1";

interface RowChildBox {
  /** Enough of the node to recognise it in a failure message. */
  name: string;
  top: number;
  height: number;
  width: number;
  centre: number;
  /** What the flex line was broken on, before any growing or shrinking. */
  basis: string;
}

interface HeaderRowGeometry {
  /** The row's own border box — what wrapping actually grows. */
  height: number;
  width: number;
  /** The laid-out children's widths plus a column gap each — the arrangement
   *  as it ended up, not a deficit: a grown child has taken the slack. */
  laidOut: number;
  columnGap: number;
  children: RowChildBox[];
}

/**
 * Read the header row's boxes. One `evaluate`, used by every assertion below
 * and by nothing else, so the numbers in a green report and a red one are
 * produced by the same code.
 */
async function measureHeaderRow(page: Page): Promise<HeaderRowGeometry> {
  return page.locator("[data-sync-header-row]").evaluate((row) => {
    const rowRect = row.getBoundingClientRect();
    const columnGap = Number.parseFloat(getComputedStyle(row).columnGap) || 0;

    const children = Array.from(row.children)
      .map((el) => ({ el, rect: el.getBoundingClientRect(), style: getComputedStyle(el) }))
      // Out of the flex flow (the `sr-only` status live region) or not
      // rendered (`hidden lg:flex` below `lg`) — neither sits on a line.
      .filter(
        ({ rect, style }) =>
          style.position !== "absolute" &&
          style.position !== "fixed" &&
          rect.width > 0 &&
          rect.height > 0,
      )
      .map(({ el, rect, style }) => ({
        name: `${el.tagName.toLowerCase()}[${(el.textContent ?? "").trim().slice(0, 28) || el.className.slice(0, 28)}]`,
        top: Math.round(rect.top * 100) / 100,
        height: Math.round(rect.height * 100) / 100,
        width: Math.round(rect.width * 100) / 100,
        centre: Math.round((rect.top + rect.height / 2) * 100) / 100,
        basis: style.flexBasis,
      }));

    const laidOut =
      children.reduce((sum, c) => sum + c.width, 0) + columnGap * (children.length - 1);

    return {
      height: Math.round(rowRect.height * 100) / 100,
      width: Math.round(rowRect.width * 100) / 100,
      laidOut: Math.round(laidOut * 100) / 100,
      columnGap,
      children,
    };
  });
}

/**
 * How many flex lines the children occupy: centres clustered at 2px. The
 * tolerance is for sub-pixel rounding only — a real wrap separates the two
 * clusters by a whole line box plus the row's 8px `gap-y-2`.
 */
function lineCount(children: RowChildBox[]): number {
  const centres = children.map((c) => c.centre).sort((a, b) => a - b);
  let lines = 0;
  let anchor = Number.NEGATIVE_INFINITY;
  for (const centre of centres) {
    if (centre - anchor > 2) {
      lines += 1;
      anchor = centre;
    }
  }
  return lines;
}

/** The measurement, laid out for a failure message. */
function describeRow(geometry: HeaderRowGeometry): string {
  const rows = geometry.children
    .map(
      (c) =>
        `    ${c.name} top=${c.top} h=${c.height} w=${c.width} centre=${c.centre} basis=${c.basis}`,
    )
    .join("\n");
  return [
    `row: height=${geometry.height} width=${geometry.width}`,
    `as laid out the children sum to ${geometry.laidOut}px incl. ${geometry.columnGap}px gaps — a description of the arrangement, not the deficit (a grown child has taken the slack); read the basis column for what the line was broken on`,
    `children (${geometry.children.length}):`,
    rows,
  ].join("\n");
}

for (const viewport of [
  { width: 1024, height: 768 }, // the owner's own width, and the `lg` boundary — the primary case
  { width: 1280, height: 800 }, // the `xl` floor: the row and the band change shape here
]) {
  test.describe(`the board's session edge at ${viewport.width}×${viewport.height}`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto(SESSION_TWIN);
      await expect(page.getByRole("heading", { level: 1, name: "Applications" })).toBeVisible();
    });

    test("the header row holds ONE line", async ({ page }) => {
      // The row must be found by identity, exactly once. A refactor that
      // dropped `data-sync-header-row` (or grew a second one) would otherwise
      // turn every number below into a measurement of something else.
      await expect(page.locator("[data-sync-header-row]")).toHaveCount(1);

      const geometry = await measureHeaderRow(page);
      const lines = lineCount(geometry.children);

      expect(
        lines,
        `the header row wrapped to ${lines} lines at ${viewport.width}px — that height comes out of the worklist (#172)\n${describeRow(geometry)}`,
      ).toBe(1);

      // Same fact from the other side: no padding on the row, so one flex
      // line means the row is exactly as tall as its tallest child.
      const tallest = Math.max(...geometry.children.map((c) => c.height));
      expect(
        geometry.height,
        `the row is ${geometry.height}px against a tallest child of ${tallest}px — that is a second line\n${describeRow(geometry)}`,
      ).toBeLessThanOrEqual(tallest + 1);
    });

    test("`Sign out` is in the row's `⋯` menu, and nowhere in the row itself", async ({ page }) => {
      const row = page.locator("[data-sync-header-row]");

      // Closed menu first: the session edge spends NO row width. This is the
      // half of #172 that a height measurement alone cannot pin — a row that
      // happens to fit its button today is not the arrangement that shipped.
      await expect(
        row.getByRole("button", { name: "Sign out" }),
        "a row-level sign-out control is back on the header row",
      ).toHaveCount(0);
      // …and the fixture pill is not doubling as one either: `?session=1`
      // replaces it, so the row under measurement is the signed-in row.
      await expect(row.getByRole("link", { name: /fixture data/ })).toHaveCount(0);

      // The trigger's name follows its contents — with a session edge folded
      // in it is more than sync options.
      await row.getByRole("button", { name: "More actions" }).click();
      const menu = page.getByRole("menu");
      await expect(menu).toBeVisible();
      await expect(menu.getByRole("menuitem", { name: "Sign out" })).toBeVisible();

      // Last item: sign-out sits after the sync actions, unhinted.
      const items = await menu.getByRole("menuitem").allInnerTexts();
      expect(items[items.length - 1], `menu items: ${JSON.stringify(items)}`).toContain("Sign out");
    });
  });
}

test("the twin's `Sign out` cannot end a session — it leaves for the demo", async ({ page }) => {
  // The honesty half of the knob, asserted rather than promised. There is no
  // session behind /demo/shell, so this item must not reach
  // `supabase.auth.signOut()` and must not strand an anonymous visitor at
  // /login; it goes where the pill it replaced goes. Its own test because a
  // navigation has no business running inside a geometry measurement.
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto(SESSION_TWIN);
  await expect(page.getByRole("heading", { level: 1, name: "Applications" })).toBeVisible();

  await page
    .locator("[data-sync-header-row]")
    .getByRole("button", { name: "More actions" })
    .click();
  await page.getByRole("menu").getByRole("menuitem", { name: "Sign out" }).click();

  await expect(page).toHaveURL(/\/demo$/);
  expect(page.url(), "the fixture twin bounced a visitor to /login").not.toMatch(/\/login/);
});
