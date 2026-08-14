import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375, startConsoleWatch } from "./helpers";
import { requireSession } from "./session";

/**
 * E2E for "File an application".
 *
 * The owner's complaint was the old inline reveal opened onto empty, janky
 * dead space. The replacement is a clean, focus-trapped modal dialog. It's the
 * identical component on `/dashboard` (posts to the API) and on the public
 * `/demo` (demo mode: validated, confirmed, never saved) — so the reveal,
 * layout, validation, and submit UX are all exercisable here without a session.
 *
 * The one thing only a session can prove — that the DASHBOARD's button opens
 * that same dialog — sits behind `requireSession()` at the bottom. Without a
 * session it skips under the shared `E2E_NO_SESSION_SKIP (#188):` token, which
 * CI counts into the job summary; with `E2E_REQUIRE_SESSION=1` it fails instead.
 */

async function openForm(page: Page) {
  await page.goto("/demo");
  await page.getByRole("button", { name: /file an application/i }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  return dialog;
}

test.describe("file an application (via /demo)", () => {
  test("opens a clean modal with all fields — no empty dead space", async ({ page }) => {
    const watch = startConsoleWatch(page);
    const dialog = await openForm(page);

    await expect(dialog.getByRole("heading", { name: /file an application/i })).toBeVisible();
    await expect(dialog.getByLabel(/company/i)).toBeVisible();
    await expect(dialog.getByLabel(/^role/i)).toBeVisible();
    await expect(dialog.getByLabel(/stage/i)).toBeVisible();
    await expect(dialog.getByLabel(/applied date/i)).toBeVisible();
    await expect(dialog.getByLabel(/link/i)).toBeVisible();
    await expect(dialog.getByLabel(/notes/i)).toBeVisible();

    // The panel is centered within the viewport — no horizontal overflow.
    await expectNoHorizontalOverflow(page);
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("Escape and Cancel both close the dialog", async ({ page }) => {
    const dialog = await openForm(page);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();

    await page.getByRole("button", { name: /file an application/i }).first().click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("button", { name: /^cancel$/i }).click();
    await expect(page.getByRole("dialog")).toBeHidden();
  });

  test("rejects an invalid link and keeps the dialog open", async ({ page }) => {
    const dialog = await openForm(page);
    await dialog.getByLabel(/company/i).fill("Acme Robotics");
    await dialog.getByLabel(/^role/i).fill("Staff Engineer");
    await dialog.getByLabel(/link/i).fill("not a valid url");
    await dialog.getByRole("button", { name: /file it/i }).click();

    await expect(dialog.getByRole("alert")).toContainText(/valid URL/i);
    await expect(dialog).toBeVisible();
  });

  test("a valid filing confirms, is announced, and moves nothing (demo — not saved)", async ({
    page,
  }) => {
    await page.goto("/demo");
    // The receipt region exists BEFORE anything is filed, and is empty. This
    // is the announcement half of #81: a live region mounted on demand drops
    // its first announcement, so a region that appears WITH the confirmation
    // is a confirmation no screen-reader user is told about. Reverting to the
    // conditional mount fails here, on the pre-filing count.
    const receipt = page.locator("[data-filing-receipt]");
    await expect(receipt).toHaveCount(1);
    await expect(receipt).toHaveAttribute("role", "status");
    await expect(receipt).toHaveText("");

    // The layout-shift half: #81 measured the distribution card and everything
    // below it moving down ~13px when the in-flow confirmation appeared.
    const below = page.getByTestId("pipeline-pulse");
    await expect(below).toBeVisible();
    const before = await below.boundingBox();

    await page.getByRole("button", { name: /file an application/i }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByLabel(/company/i).fill("Acme Robotics");
    await dialog.getByLabel(/^role/i).fill("Staff Engineer");
    await dialog.getByRole("button", { name: /file it/i }).click();

    await expect(page.getByRole("dialog")).toBeHidden();
    // The SAME persistent node carries the confirmation — announced, honest
    // about not persisting.
    await expect(receipt).toContainText(/Filed “Acme Robotics” — demo only, not saved/);

    // …and the page did not shift: the receipt is an anchored overlay now,
    // not a flow insert. Reverting to in-flow fails here, on the y delta.
    const after = await below.boundingBox();
    expect(
      Math.abs((after?.y ?? 0) - (before?.y ?? Number.NaN)),
      "the content below the button moved when the confirmation appeared",
    ).toBeLessThanOrEqual(1);
  });

  test("no overflow with the dialog open on mobile", async ({ page }) => {
    await page.setViewportSize(MOBILE_375);
    await openForm(page);
    await expectNoHorizontalOverflow(page);
  });
});

test.describe("file an application (signed in — needs a session)", () => {
  test("the dashboard button opens the same modal", async ({ page }) => {
    await requireSession(page, "the real dashboard's file-application button opening the modal");
    await page.getByRole("button", { name: /file an application/i }).first().click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });
});
