import { expect, test, type Page } from "@playwright/test";

/**
 * #921: a row that has left the board is findable and restorable AFTER the
 * undo window closes.
 *
 * THE ASSERTION THAT MATTERS IS THE ORDER OF EVENTS, not the panel rendering.
 * A test that opened "Removed rows" and found a list would be green on a build
 * where the list is the board, on a build where the row is only there while its
 * window is still open, and on today's build if the panel simply existed
 * unreachable. So every case here waits for the window to CLOSE first —
 * `waitForCommit`, borrowed verbatim in shape from `row-removal.spec.ts` — and
 * only then goes looking. That instant is the whole issue: before this change
 * it was the point at which an accidental removal became indistinguishable from
 * a deliberate one and equally final.
 *
 * WAITED FOR, NEVER SLEPT THROUGH. The wait is the countdown disappearing and
 * the row leaving the board, which is the signal that the dismissal reached the
 * transport — not `waitForTimeout(UNDO_WINDOW_SECONDS)`, which would pass on a
 * build whose window never closed at all. It does mean each case spends the
 * real window, so the per-test timeout is raised deliberately below.
 *
 * WHAT MAKES EACH CASE RED — run these, they are the point of the file:
 *
 *  1. "the row is findable and restorable once the window has closed" — in
 *     `components/demo/DemoDashboard.tsx`, make `dismiss` drop the row instead
 *     of moving it (`removed: s.removed`), or make the `removed` transport
 *     answer `{ applications: [], total: 0 }`. Either reproduces the state this
 *     issue reports: the row is off the board and nothing lists it. The restore
 *     half reds separately if `restoreRow` stops filtering the removed list —
 *     the row comes back to the board AND stays offered here.
 *  2. "a search that finds nothing says where else to look" — set
 *     `canRecover={false}` on the twin's `PipelineBoard`, or delete the button
 *     from `emptyTrackLine`. The bare "none match" this restores is exactly the
 *     dead end the issue describes.
 *  3. "the panel says so when there is nothing to recover" — this one is a
 *     control on the other two: it proves the panel can render EMPTY, so a
 *     build that always drew rows (the board, say) could not satisfy both it
 *     and case 1.
 *
 * WHAT THIS FILE DOES NOT COVER, and it is not an oversight. The fourth door —
 * the committed tombstone's "Removed rows" link — cannot be driven here. On the
 * live board the tombstone paints for the length of the `router.refresh()`
 * round trip; on the fixture twin the transport commits its own store before
 * `dismiss` resolves, so the row unmounts in the same render and the tombstone
 * never appears. Making the twin pause to show it would be inventing a delay
 * the fixtures do not have in order to test a surface. It needs a signed-in
 * session, which CI does not have.
 *
 * Pagination is unexercised for a cheaper reason: the twin would need eleven
 * removals, and each one costs the real ten-second window. `removedRange` and
 * `pageCount` are asserted directly in `tests/unit/removed-rows.test.mjs`.
 */

/** The owner's width — every measurement in `row-removal.spec.ts` was taken
 *  here, and this file shares that file's board. */
const OWNER_VIEWPORT = { width: 1024, height: 768 };

/** The row this file removes. Same one `row-removal.spec.ts` uses: third of
 *  eight in `applied`, so the board is not left in an edge shape. */
const TARGET = "Harbor Analytics";

/**
 * The whole window, plus the round trip, plus room — and stated as a budget
 * rather than as a duration anything waits out. Playwright's default 30s is
 * enough for one window but not for a case that opens two.
 */
const WINDOW_BUDGET_MS = 60_000;

/** Open a row's `···` menu and choose "Not an application". */
async function dismiss(page: Page, company: string): Promise<void> {
  await page.locator(`button[aria-label^="Row actions for ${company}"]`).click();
  await page.getByRole("menuitem", { name: /Not an application/ }).click();
}

/**
 * Wait out the undo window and the commit behind it.
 *
 * The trap this avoids is the one `row-removal.spec.ts` documents: the pending
 * tombstone reads "<company> removed from the board · undo within Ns", so any
 * locator for the committed text matches INSIDE the cancellable window. Waiting
 * on the countdown's disappearance, then on the row leaving, is what puts
 * everything below on the far side of the cliff.
 */
async function waitForCommit(page: Page, company: string): Promise<void> {
  await expect(page.getByText(/undo within \d+s/)).toHaveCount(0, { timeout: 20_000 });
  await expect(page.locator(`button[aria-label^="Row actions for ${company}"]`)).toHaveCount(0);
}

/** The permanent door: the board's command-row `⋯` menu. */
async function openPanelFromMenu(page: Page): Promise<void> {
  await page.getByRole("button", { name: /^(More actions|Sync options)$/ }).click();
  await page.getByRole("menuitem", { name: /^Removed rows/ }).click();
}

const panel = (page: Page) => page.getByRole("dialog").filter({ hasText: "Removed rows" });

test.describe("a removed row is reachable after the window closes", () => {
  test.use({ viewport: OWNER_VIEWPORT });

  test("the row is findable and restorable once the window has closed", async ({ page }) => {
    test.setTimeout(WINDOW_BUDGET_MS);
    await page.goto("/demo");
    await expect(page.locator('section[aria-label^="applied —"]')).toBeVisible();

    await dismiss(page, TARGET);
    // THE CLIFF. Past this line the in-cell Undo is gone, the dismissal has
    // been sent, and on the build this issue was filed against there was no
    // route, filter, toggle or link anywhere in the app that could name this
    // row again.
    await waitForCommit(page, TARGET);

    await openPanelFromMenu(page);
    const dialog = panel(page);
    await expect(dialog).toBeVisible();

    // Found — by employer, in a list the reader can read.
    const row = dialog.locator("li").filter({ hasText: TARGET });
    await expect(row).toHaveCount(1);
    // And attributed. The set has two authors (a hand removal and a rebuild's
    // purge) and this one was the reader's own, so the panel says so; a build
    // that stopped distinguishing them would still list the row and would be
    // telling everyone they did something they may not have done.
    await expect(row).toContainText("you removed this");

    // Restorable — the act the endpoint has always supported and the UI never
    // offered past the window.
    await row.getByRole("button", { name: new RegExp(`Put it back — ${TARGET}`) }).click();
    await expect(row).toContainText("back on the board");

    // AND ACTUALLY BACK. The confirmation inside the panel is not the claim
    // being tested; the board holding the row again is.
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(page.locator(`button[aria-label^="Row actions for ${TARGET}"]`)).toHaveCount(1);

    // And no longer offered here, which is the half a stale list would fail:
    // a row on the board with a "Put it back" button beside it is an action
    // that can only be wrong.
    await openPanelFromMenu(page);
    await expect(panel(page).locator("li").filter({ hasText: TARGET })).toHaveCount(0);
  });

  test("a search that finds nothing says where else to look", async ({ page }) => {
    test.setTimeout(WINDOW_BUDGET_MS);
    await page.goto("/demo");
    await expect(page.locator('section[aria-label^="applied —"]')).toBeVisible();

    await dismiss(page, TARGET);
    await waitForCommit(page, TARGET);

    // The panic path, in the place a reader actually looks: they type the
    // employer they cannot find into the board's own search.
    await page.getByRole("searchbox").first().fill(TARGET);
    await expect(page.getByText(/none match/).first()).toBeVisible();

    // Before #921 this line ended here. The row existed, the API could list it,
    // the API could restore it, and the board's answer was three words.
    //
    // The button is located at PAGE scope, not inside the `none match` text
    // node: `getByText` with a regex can resolve to an ancestor as easily as
    // to the element itself, and `.first()` then decides by DOM order — a
    // chain whose target depends on which node won is not a locator, it is a
    // coin toss that usually lands the same way. There is exactly one control
    // with this name on the board.
    await page.getByRole("button", { name: /check removed rows/i }).click();
    await expect(panel(page).locator("li").filter({ hasText: TARGET })).toHaveCount(1);
  });

  test("the panel says so when there is nothing to recover", async ({ page }) => {
    // The control for the two cases above: this build can render the panel
    // EMPTY. Without it, "the row is in the list" would also be satisfied by a
    // panel that showed the board, or any list at all.
    await page.goto("/demo");
    await expect(page.locator('section[aria-label^="applied —"]')).toBeVisible();

    await openPanelFromMenu(page);
    const dialog = panel(page);
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Nothing is off the board.");
    await expect(dialog.locator("li")).toHaveCount(0);
  });
});
