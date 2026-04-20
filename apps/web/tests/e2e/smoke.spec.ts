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
 */
test("login page renders sign-in form", async ({ page }) => {
  await page.goto("/login");

  await expect(
    page.getByRole("heading", { name: /sign in to jobtracker/i }),
  ).toBeVisible();

  await expect(page.getByLabel(/email/i)).toBeVisible();
  await expect(page.getByLabel(/password/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /^sign in/i })).toBeVisible();
});
