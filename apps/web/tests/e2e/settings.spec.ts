import { expect, test, type Page } from "@playwright/test";

import { startConsoleWatch } from "./helpers";

/**
 * E2E for Settings.
 *
 * Settings is auth-gated (the `(app)` layout bounces a signed-out visitor to
 * `/login`), so the full section coverage below is skip-guarded and becomes
 * real the moment the suite runs against a session. What we CAN drive without a
 * session is the Appearance theme mechanism itself — the same pre-paint script
 * the theme switch persists into — proven on a publicly reachable, theme-honoring
 * page.
 */

async function reachSettingsOrSkip(page: Page): Promise<void> {
  await page.goto("/settings");
  test.skip(
    /\/login/.test(page.url()),
    "no authenticated Supabase session in this environment — /settings is unreachable",
  );
}

test.describe("appearance theme (public mechanism)", () => {
  test("a saved light theme is applied before paint, and dark restores it", async ({ page }) => {
    const watch = startConsoleWatch(page);

    // Import is a real, theme-honoring page reachable without auth.
    await page.goto("/import");
    await page.evaluate(() => localStorage.setItem("jt-theme", "light"));
    await page.reload();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe("light");

    await page.evaluate(() => localStorage.setItem("jt-theme", "dark"));
    await page.reload();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe("dark");

    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });
});

test.describe("settings sections (signed in — needs a session)", () => {
  test("renders every wired section", async ({ page }) => {
    await reachSettingsOrSkip(page);

    await expect(page.getByRole("heading", { name: /^settings$/i })).toBeVisible();
    for (const name of [
      /^profile$/i,
      /^appearance$/i,
      /^gmail$/i,
      /^notifications$/i,
      /^classification$/i,
      /your data/i,
      /^account$/i,
    ]) {
      await expect(page.getByRole("heading", { name })).toBeVisible();
    }
  });

  test("the appearance switch is a working radiogroup", async ({ page }) => {
    await reachSettingsOrSkip(page);
    const group = page.getByRole("radiogroup", { name: /theme/i });
    await expect(group).toBeVisible();
    await group.getByRole("radio", { name: /light/i }).click();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe("light");
    // Reset so the run doesn't leave the app themed light.
    await group.getByRole("radio", { name: /dark/i }).click();
  });

  test("the classification gate shows a live review count", async ({ page }) => {
    await reachSettingsOrSkip(page);
    await expect(page.getByText(/would wait for your review/i)).toBeVisible();
    await expect(page.getByRole("slider", { name: /gate/i })).toBeVisible();
  });

  test("account deletion is gated behind a typed confirmation", async ({ page }) => {
    await reachSettingsOrSkip(page);
    await page.getByRole("button", { name: /delete account/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const confirmButton = dialog.getByRole("button", { name: /permanently delete/i });
    await expect(confirmButton).toBeDisabled();
    await dialog.getByRole("textbox").fill("DELETE");
    await expect(confirmButton).toBeEnabled();
  });
});
