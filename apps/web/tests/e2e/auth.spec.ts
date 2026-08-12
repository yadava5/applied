import { expect, test, type Page } from "@playwright/test";

/**
 * E2E for the two auth forms (`/login`, `/signup`).
 *
 * The defect this file exists for: both forms set `noValidate` — deliberately,
 * so the app writes its own error copy instead of the browser's bubbles — but
 * nothing replaced the checks that switch turns off. Measured against the live
 * deployment, an empty `/login` submit, a `not-an-email`, and a three-character
 * password each fired a real `POST /auth/v1/token?grant_type=password`, and the
 * page said nothing at all until the server answered. `/signup` checked the
 * password by hand but never the email, so a malformed address still cost a
 * real `POST /auth/v1/signup`. A held Enter key on an empty form spends live
 * requests against an auth rate limit.
 *
 * So each case asserts BOTH halves: a message the user can see, and zero calls
 * to Supabase's auth API. The counter is proved to work by a positive control
 * (`the interceptor is real`) — a route filter that never matches would make
 * every "zero calls" assertion pass for the wrong reason, which is the exact
 * shape of check this repo has been bitten by.
 *
 * No real credential is ever submitted: every address is `.invalid` (RFC 2606,
 * guaranteed never to resolve) and every request to the auth API is aborted at
 * the route before it can leave the machine.
 */

interface AuthWatch {
  /** Requests that reached the network layer and were aborted there. */
  routeCalls: string[];
  /** Every auth request the app ATTEMPTED, blocked or not. */
  attempts: () => Promise<string[]>;
}

/**
 * Two instruments, because one of them cannot see the whole truth.
 *
 * `page.route` aborts anything bound for Supabase's auth API — the safety net,
 * so even a bug in this spec cannot put a credential on the wire. But it can
 * only count what reaches the network layer, and the app ships a CSP whose
 * `connect-src` names the real Supabase project (`next.config.ts`). CI and
 * local dev both run with the placeholder `https://example.supabase.co`, which
 * that CSP blocks: the fetch fails in the page and no request is ever routed.
 * Measured — the well-formed submit below rendered "Failed to fetch" with the
 * route counter still at zero. A route-only assertion would therefore read
 * zero whether the form validated or not: a check that cannot fail.
 *
 * So the primary instrument wraps `window.fetch` before any page script runs
 * and records the ATTEMPT, which is the property under test — an invalid
 * submit must not even try.
 */
async function watchAuth(page: Page): Promise<AuthWatch> {
  const routeCalls: string[] = [];

  await page.addInitScript(() => {
    const attempts: string[] = [];
    (window as unknown as { __authAttempts: string[] }).__authAttempts = attempts;
    const nativeFetch = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/auth/v1/")) attempts.push(`${init?.method ?? "GET"} ${url}`);
      return nativeFetch(input, init);
    };
  });

  await page.route("**/auth/v1/**", async (route) => {
    routeCalls.push(`${route.request().method()} ${route.request().url()}`);
    await route.abort();
  });

  return {
    routeCalls,
    attempts: () =>
      page.evaluate(
        () => (window as unknown as { __authAttempts?: string[] }).__authAttempts ?? [],
      ),
  };
}

/**
 * Assert the form spent nothing: no attempt, and nothing on the wire.
 *
 * Polled rather than read once. A single read is only sound while a visible
 * message is asserted first (which is what makes the page settle); polling
 * means a request issued a beat later fails this instead of slipping past a
 * snapshot taken too early, whatever order a future edit puts the assertions
 * in. A passing case still costs one read.
 */
async function expectNoAuthTraffic(watch: AuthWatch): Promise<void> {
  await expect
    .poll(async () => await watch.attempts(), { message: "the form called the auth API" })
    .toEqual([]);
  await expect
    .poll(() => watch.routeCalls, { message: "a request reached the network" })
    .toEqual([]);
}

/** Forget anything the page did on load; only the submit is under test. */
async function resetAuthWatch(page: Page, watch: AuthWatch): Promise<void> {
  await page.evaluate(() => {
    const w = window as unknown as { __authAttempts?: string[] };
    if (w.__authAttempts) w.__authAttempts.length = 0;
  });
  watch.routeCalls.length = 0;
}

/**
 * What the FORM shows when it refuses to submit — scoped to the form because
 * Next's own route announcer is a second `role="alert"` on every page.
 */
function alertText(page: Page) {
  return page.locator("form").getByRole("alert");
}

test.describe("auth forms validate before they touch the network", () => {
  test("the interceptor is real: a well-formed submit DOES reach the auth API", async ({
    page,
  }) => {
    // The positive control for every zero-traffic assertion below. The address
    // is syntactically valid and in the RFC 2606 `.invalid` TLD, so it can
    // never resolve, and the request is aborted at the route regardless —
    // nothing leaves this machine.
    const watch = await watchAuth(page);
    await page.goto("/login");
    await page.getByLabel(/email/i).fill("nobody@example.invalid");
    await page.getByLabel(/password/i).fill("not-a-real-password");
    await page.getByRole("button", { name: /^sign in/i }).click();

    await expect
      .poll(async () => (await watch.attempts()).length, {
        message: "the auth watch never saw a call — the zero assertions are vacuous",
      })
      .toBeGreaterThan(0);
    expect((await watch.attempts()).join("\n")).toContain("/auth/v1/token");
  });

  test("/login: an empty submit is refused without a request", async ({ page }) => {
    const watch = await watchAuth(page);
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    await resetAuthWatch(page, watch);

    await page.getByRole("button", { name: /^sign in/i }).click();

    await expect(alertText(page)).toHaveText("Enter your email address.");
    // …and focus lands on the field to fix, not nowhere.
    await expect(page.getByLabel(/email/i)).toBeFocused();
    await expectNoAuthTraffic(watch);
  });

  test("/login: a malformed email is refused without a request", async ({ page }) => {
    const watch = await watchAuth(page);
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    await resetAuthWatch(page, watch);

    await page.getByLabel(/email/i).fill("not-an-email");
    await page.getByLabel(/password/i).fill("notarealpassword");
    await page.getByRole("button", { name: /^sign in/i }).click();

    await expect(alertText(page)).toHaveText("That doesn’t look like an email address.");
    await expect(page.getByLabel(/email/i)).toHaveAttribute("aria-invalid", "true");
    await expectNoAuthTraffic(watch);
  });

  test("/login: a password under the floor is refused without a request", async ({ page }) => {
    const watch = await watchAuth(page);
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    await resetAuthWatch(page, watch);

    await page.getByLabel(/email/i).fill("test@example.invalid");
    await page.getByLabel(/password/i).fill("ab1");
    await page.getByRole("button", { name: /^sign in/i }).click();

    // 6, not 8: /login must still accept a password an existing account has.
    await expect(alertText(page)).toHaveText("Password must be at least 6 characters.");
    await expect(page.getByLabel(/password/i)).toBeFocused();
    await expectNoAuthTraffic(watch);
  });

  test("/signup: a malformed email is refused without a request", async ({ page }) => {
    const watch = await watchAuth(page);
    await page.goto("/signup");
    await page.waitForLoadState("networkidle");
    await resetAuthWatch(page, watch);

    // Long enough to clear the password floor — this pair used to reach
    // POST /auth/v1/signup, because only the password was ever checked.
    await page.getByLabel(/email/i).fill("not-an-email");
    await page.getByLabel(/password/i).fill("longenoughpassword");
    await page.getByRole("button", { name: /create account/i }).click();

    await expect(alertText(page)).toHaveText("That doesn’t look like an email address.");
    await expect(page.getByLabel(/email/i)).toBeFocused();
    await expectNoAuthTraffic(watch);
  });

  test("/signup: the 8-character promise is still enforced, and still free", async ({ page }) => {
    const watch = await watchAuth(page);
    await page.goto("/signup");
    await page.waitForLoadState("networkidle");
    await resetAuthWatch(page, watch);

    await page.getByLabel(/email/i).fill("nobody@example.invalid");
    await page.getByLabel(/password/i).fill("short12");
    await page.getByRole("button", { name: /create account/i }).click();

    // The hint says "At least 8 characters" and the form means it — Supabase's
    // own floor is 6, so this check is the only thing keeping that promise.
    await expect(alertText(page)).toHaveText("Password must be at least 8 characters.");
    await expectNoAuthTraffic(watch);
  });
});
