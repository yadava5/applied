import { expect, test } from "@playwright/test";

/**
 * Golden-path E2E smoke test: the /login page must render its form.
 *
 * Guards against two classes of regression that would otherwise slip
 * through unit CI:
 *
 * 1. A bad env-var schema change in `lib/env.ts` that throws on import
 *    and 500s the route.
 * 2. A Supabase/SSR cookie-handling bug in `proxy.ts` or
 *    `lib/supabase/*` that crashes the route segment.
 *
 * Assertions are kept narrow — heading + submit button + both inputs —
 * so copy tweaks don't cause red CI, but a truly broken page does.
 *
 * The heading is asserted by ROLE AND LEVEL, never by its words. Pinning the
 * copy here is what turned a deliberate rewrite of the greetings into four
 * red specs across three files, which is precisely what this docblock says
 * it is avoiding. A level-1 heading with text in it proves the page composed;
 * which sentence it holds is a product decision, not a contract.
 */
test("login page renders sign-in form", async ({ page }) => {
  await page.goto("/login");

  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).not.toBeEmpty();

  await expect(page.getByLabel(/email/i)).toBeVisible();
  await expect(page.getByLabel(/password/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /^sign in/i })).toBeVisible();
});

test("signup page renders the create-account form", async ({ page }) => {
  await page.goto("/signup");

  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).not.toBeEmpty();
  await expect(page.getByLabel(/email/i)).toBeVisible();
  await expect(page.getByLabel(/password/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /create account/i })).toBeVisible();

  // Cross-link back to sign-in — never a dead end.
  await page.getByRole("link", { name: /^sign in$/i }).click();
  await expect(page).toHaveURL(/\/login$/);
});
