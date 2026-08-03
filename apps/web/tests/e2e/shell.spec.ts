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
