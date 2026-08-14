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
 * mounts the real pair the signed-in page passes to `SyncBar` (`signedIn`
 * on, `trailing` unset). The knob is declared in that route's own doc comment
 * beside `?review=N` and `?queue=`, and nothing links to it.
 *
 * WHAT "ONE LINE" IS MEASURED AS, and why not a pixel number. A hardcoded
 * height (the wrapped row measured 82px) is a magic number that goes stale
 * the first time a control's padding or the type scale moves, and it cannot
 * say WHICH way it failed. Two structural measures are asserted instead, both
 * derived from the row's own flex behaviour, and a third that is frankly a
 * backstop rather than a measurement (see 3):
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
 *   3. A loose ceiling on the row's height. Both measures above are relative
 *      to the children, so both would pass if the CONTROLS CLUSTER ever
 *      wrapped inside itself: it stays one flex child with one centre, and
 *      the row stays exactly as tall as it. Implausible with today's
 *      contents; free to guard against. Shown red the same way everything
 *      else here was — the ceiling temporarily set to 20px reported the
 *      row's real 38px at both widths, so the assertion executes.
 *
 * All three are reported with every child's box in the failure message,
 * together with each child's flex-basis and what the children sum to AS LAID
 * OUT — a grown flex child (the ledger chip) has already absorbed the row's
 * slack by the time it is measured, so that sum is a description of the
 * arrangement, NOT the row's deficit. The basis column is the one to read when
 * asking whether something fits: line breaking happens on hypothetical sizes,
 * before any growing or shrinking.
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
 * where this one clears it by roughly 60. So the assertions above gate the
 * ARRANGEMENT — no row-level session control, sign-out reachable in the menu,
 * one line — and nothing more: a row that grew 8px taller is still one line
 * and still under the ceiling (38 + 8 = 46), and those 8px come straight out
 * of the worklist. That is why the worklist floor at the bottom
 * of this file exists. It records what the fold actually BOUGHT (the
 * signed-in twin's worklist share at 1024, against `shell.spec.ts`'s recorded
 * floors for the default twin) and goes red when the row stops being cheap,
 * which is a different regression from the row stopping being one line —
 * neither assertion implies the other. A budget assertion on the LIVE row is
 * still out of reach: it needs a session, and belongs with the specs that
 * have one.
 *
 * The last test here is the mirror of the knob's absence assertions: the
 * DEFAULT twin (no `?session=1`) must still wear its fixture signage. Nothing
 * else asserts that, so a flipped prop default would strip the honesty
 * affordance off /demo/shell with every gate in the repo green.
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

      // Backstop, not a measurement. Both assertions above are RELATIVE to the
      // children, so both would pass if the controls cluster wrapped inside
      // itself: it would remain one flex child with one centre, and the row
      // would remain exactly as tall as it. A ceiling is the only thing that
      // sees that. It is loose (the row measures 38px) because the honest
      // alternative — asserting the height equals a recorded number — was
      // rejected: that goes stale the first time a control's padding or the
      // type scale moves, which is the same reason the two measures above are
      // structural rather than pixel counts. Anything under 48px is one line
      // of these controls; two is 84px+.
      expect(
        geometry.height,
        `the row is ${geometry.height}px — one flex line of these controls is under 48px, so something inside a child has wrapped\n${describeRow(geometry)}`,
      ).toBeLessThanOrEqual(48);
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

/**
 * What the fold actually BOUGHT, recorded the way `shell.spec.ts` records it —
 * `worklist-pane` clientHeight against a floor, same locator, same slack.
 * That file's floors are all measured on the DEFAULT twin, which still
 * renders the fixture frame and the pill and still wraps its header at 1024,
 * so the signed-in arrangement's worklist share is recorded NOWHERE and a
 * change that spent the fold's pixels back on the header row would pass every
 * gate in the repo — this file's assertions included. Work the arithmetic: a
 * row 8px taller is still ONE line and still under the 48px ceiling
 * (38 + 8 = 46), and only the floor below sees it (620 − 8 = 612 < 613). The
 * two fail on different regressions and neither implies the other: the
 * assertions above say the row is one line, this one says it stays cheap.
 *
 * Measured 2026-08-13 on this branch, `next build && next start`, headless
 * Chromium, against `shell.spec.ts`'s readings for the default twin at the
 * same widths (592 at 1024×768, 652 at 1280×800):
 *
 *     1024×768   620 here vs 592 default — the +28px #172 claims for the
 *                worklist, independently reproduced. The primary case: it is
 *                the owner's own width and the only one where the row wrapped.
 *     1280×800   652 here vs 652 default — unchanged, as expected; the row
 *                never wrapped at `xl`, so there was nothing to buy back.
 *
 * The floors are the measurement less 7px — the same slack `shell.spec.ts`
 * allows at all three of its widths, enough for sub-pixel and font drift and
 * nothing like the tens of pixels a real regression costs.
 */
for (const { viewport, floor } of [
  { viewport: { width: 1024, height: 768 }, floor: 613 },
  { viewport: { width: 1280, height: 800 }, floor: 645 },
]) {
  test(`the signed-in row leaves the worklist its share at ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto(SESSION_TWIN);
    await expect(page.getByRole("heading", { level: 1, name: "Applications" })).toBeVisible();

    const client = await page.getByTestId("worklist-pane").evaluate((el) => el.clientHeight);
    expect(
      client,
      `the worklist pane shrank to ${client}px (floor ${floor}px) — the header row is spending back the height the fold freed (#172)`,
    ).toBeGreaterThanOrEqual(floor);
  });
}

test("the DEFAULT twin still wears its fixture signage", async ({ page }) => {
  // The mirror of the knob's absence assertions, and the only thing asserting
  // the twin's honesty affordances are there AT ALL: those say the pill and
  // the frame are GONE under `?session=1`, which a flipped prop default would
  // satisfy on every surface — stripping the signage off /demo/shell for
  // every organic visitor with every gate in the repo still green.
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/demo/shell");
  await expect(page.getByRole("heading", { level: 1, name: "Applications" })).toBeVisible();

  const row = page.locator("[data-sync-header-row]");

  // The provenance pill, in the row's `trailing` slot.
  await expect(
    row.getByRole("link", { name: /fixture data/ }),
    "the demo pill is gone from the default twin's header row",
  ).toBeVisible();
  // The fixture recency frame — the phrase the knob swaps the live component
  // in for, and the one that says plainly that no mail is being read.
  await expect(
    row.getByText(/simulated account/),
    "the default twin's recency slot no longer says the account is simulated",
  ).toBeVisible();
  // And the menu keeps its fixture name: no session here, so nothing to end
  // and no reason for the trigger to promise more than sync options.
  await expect(row.getByRole("button", { name: "Sync options" })).toBeVisible();
  await expect(
    row.getByRole("button", { name: "More actions" }),
    "the default twin is rendering the signed-in menu",
  ).toHaveCount(0);
});
