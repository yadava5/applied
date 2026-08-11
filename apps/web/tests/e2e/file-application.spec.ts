import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, MOBILE_375, startConsoleWatch } from "./helpers";

/**
 * E2E for "File an application".
 *
 * The owner's complaint was the old inline reveal opened onto empty, janky
 * dead space. The replacement is a clean, focus-trapped modal dialog. It's the
 * identical component on `/dashboard` (posts to the API) and on the public
 * `/demo` (demo mode: validated, confirmed, never saved) — so the reveal,
 * layout, validation, and submit UX are all exercisable here without a session.
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

  test("a valid filing confirms and closes (demo — not saved)", async ({ page }) => {
    const dialog = await openForm(page);
    await dialog.getByLabel(/company/i).fill("Acme Robotics");
    await dialog.getByLabel(/^role/i).fill("Staff Engineer");
    await dialog.getByRole("button", { name: /file it/i }).click();

    await expect(page.getByRole("dialog")).toBeHidden();
    // Scoped by text: /demo now mounts SyncBar's persistent live regions too,
    // so a bare role=status locator resolves to several elements.
    const confirmation = page.getByRole("status").filter({ hasText: /Acme Robotics/ });
    await expect(confirmation).toContainText(/demo only, not saved/i);
  });

  test("no overflow with the dialog open on mobile", async ({ page }) => {
    await page.setViewportSize(MOBILE_375);
    await openForm(page);
    await expectNoHorizontalOverflow(page);
  });
});

test.describe("file an application (signed in — needs a session)", () => {
  test("the dashboard button opens the same modal", async ({ page }) => {
    await page.goto("/dashboard");
    test.skip(/\/login/.test(page.url()), "no session — /dashboard is unreachable");
    await page.getByRole("button", { name: /file an application/i }).first().click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });
});
