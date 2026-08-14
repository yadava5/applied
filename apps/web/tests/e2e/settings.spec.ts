import { expect, test } from "@playwright/test";

import { startConsoleWatch } from "./helpers";
import { requireSession } from "./session";

/**
 * E2E for Settings.
 *
 * Settings is auth-gated (the `(app)` layout bounces a signed-out visitor to
 * `/login`), so the full section coverage below is guarded by
 * `requireSession()` and becomes real the moment the suite runs against a
 * session. Without one it skips — but under the shared, greppable
 * `E2E_NO_SESSION_SKIP (#188):` token that CI counts into the job summary, and
 * `E2E_REQUIRE_SESSION=1` turns those skips into failures. What we CAN drive
 * without a session is the Appearance theme mechanism itself — the same
 * pre-paint script the theme switch persists into — proven on a publicly
 * reachable, theme-honoring page.
 *
 * The guard probes `/dashboard`, not `/settings`: both sit behind the same
 * `(app)` layout, so one probe answers for both, and each test navigates to
 * `/settings` itself once the session is known to be real.
 */

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

test.describe("settings (via the public /demo/settings twin)", () => {
  // The REAL settings sections over the simulated settings transport — the
  // only executing coverage these components have: `/settings` needs a
  // Supabase session that neither CI nor a local checkout can mint, so the
  // signed-in describe below skips everywhere it matters.

  test("renders every wired section, with the section rail", async ({ page }) => {
    const watch = startConsoleWatch(page);
    await page.goto("/demo/settings");

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
    await expect(page.getByRole("navigation", { name: /settings sections/i })).toBeVisible();
    // The provenance badge — this page must never read as a real account.
    await expect(page.getByText("demo · fixture account · nothing is saved")).toBeVisible();
    // #199: the sign-in method is DERIVED from the identity list (the fixture
    // is the measured email-only shape), no longer a hardcoded literal.
    await expect(page.getByText("Email & password", { exact: true })).toBeVisible();
    // #200: two of the named captions used to render on this twin — their
    // absence is asserted so a reintroduction fails here.
    await expect(page.getByText(/stored on your account/i)).toHaveCount(0);
    await expect(page.getByText(/export downloads your rows/i)).toHaveCount(0);
    expect(watch.errors, watch.errors.join("\n")).toEqual([]);
  });

  test("change password: offered on the email-identity account, signup floor enforced, success reported", async ({
    page,
  }) => {
    await page.goto("/demo/settings");
    await page.getByRole("button", { name: /^change password$/i }).click();

    const newPassword = page.getByLabel("new password", { exact: true });
    const confirm = page.getByLabel("confirm new password", { exact: true });

    // Below the signup floor → refused before any network, on the app's copy.
    await newPassword.fill("short");
    await confirm.fill("short");
    await page.getByRole("button", { name: /^update password$/i }).click();
    await expect(page.getByRole("alert")).toContainText(/at least 8 characters/i);

    // Long enough but unconfirmed → the confirm field is the problem.
    await newPassword.fill("long enough password");
    await confirm.fill("long enough passw0rd");
    await page.getByRole("button", { name: /^update password$/i }).click();
    await expect(page.getByRole("alert")).toContainText(/don’t match/i);

    // A matching pair runs the whole machine to the success status.
    await confirm.fill("long enough password");
    await page.getByRole("button", { name: /^update password$/i }).click();
    await expect(page.getByRole("status").filter({ hasText: "Password updated" })).toBeVisible();
  });

  test("the appearance switch is a working radiogroup — the real theme mechanism", async ({
    page,
  }) => {
    await page.goto("/demo/settings");
    const group = page.getByRole("radiogroup", { name: /theme/i });
    await expect(group).toBeVisible();
    await group.getByRole("radio", { name: /light/i }).click();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe("light");
    // Reset so the run doesn't leave the app themed light.
    await group.getByRole("radio", { name: /dark/i }).click();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe("dark");
  });

  test("the classification gate shows a live consequence as it moves", async ({ page }) => {
    await page.goto("/demo/settings");
    await expect(page.getByText(/would wait for your review/i)).toBeVisible();
    await expect(page.getByRole("slider", { name: /gate/i })).toBeVisible();
  });

  test("a profile save runs the whole machine and reports Saved", async ({ page }) => {
    await page.goto("/demo/settings");
    const name = page.getByPlaceholder("e.g. Ayush Yadav");
    await name.fill("Sam Fixture II");
    await page.getByRole("button", { name: "Save profile" }).click();
    await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  });

  test("account deletion is gated behind a typed confirmation — and the demo refuses honestly", async ({
    page,
  }) => {
    await page.goto("/demo/settings");
    await page.getByRole("button", { name: /delete account/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const confirmButton = dialog.getByRole("button", { name: /permanently delete/i });
    await expect(confirmButton).toBeDisabled();
    await dialog.getByRole("textbox").fill("DELETE");
    await expect(confirmButton).toBeEnabled();
    // On the twin the transport answers with the one honest difference —
    // nothing exists to delete — through the same error surface the live
    // route uses for a deployment without deletion enabled.
    await confirmButton.click();
    await expect(dialog.getByRole("alert")).toContainText(/simulated account/i);
  });

  test("the disconnect control is disabled with a reason, never a dead button that lies", async ({
    page,
  }) => {
    await page.goto("/demo/settings");
    const disconnect = page.getByRole("button", { name: /^disconnect$/i });
    await expect(disconnect).toBeDisabled();
    await expect(disconnect).toHaveAttribute("title", /simulated account/i);
  });
});

test.describe("settings sections (signed in — needs a session)", () => {
  test("renders every wired section", async ({ page }) => {
    await requireSession(page, "every wired Settings section rendering on the real /settings");
    await page.goto("/settings");

    // Re-pointed for #199: the visible page name now lives in the shell
    // TopBar's location label; the page keeps exactly one sr-only h1 for the
    // document outline, so this asserts presence-and-uniqueness, not
    // visibility.
    await expect(page.getByRole("heading", { level: 1, name: /^settings$/i })).toHaveCount(1);
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
    await requireSession(page, "the Appearance theme radiogroup on the real /settings");
    await page.goto("/settings");
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
    await requireSession(page, "the classification gate's live review count, against real data");
    await page.goto("/settings");
    await expect(page.getByText(/would wait for your review/i)).toBeVisible();
    await expect(page.getByRole("slider", { name: /gate/i })).toBeVisible();
  });

  test("account deletion is gated behind a typed confirmation", async ({ page }) => {
    await requireSession(page, "the real account-deletion confirmation gate");
    await page.goto("/settings");
    await page.getByRole("button", { name: /delete account/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const confirmButton = dialog.getByRole("button", { name: /permanently delete/i });
    await expect(confirmButton).toBeDisabled();
    await dialog.getByRole("textbox").fill("DELETE");
    await expect(confirmButton).toBeEnabled();
  });
});
