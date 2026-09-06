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
 * only count what reaches the NETWORK layer, and a request the browser refuses
 * to issue never gets there. The primary instrument therefore wraps
 * `window.fetch` before any page script runs and records the ATTEMPT, which is
 * the property actually under test: an invalid submit must not even try.
 *
 * THAT DISTINCTION WAS NOT ACADEMIC, AND THE HISTORY IS WORTH KEEPING. Until
 * #740 the CSP's `connect-src` was a hardcoded project ref, while CI and local
 * dev both boot against the placeholder `https://example.supabase.co`. The
 * policy blocked the placeholder outright: measured here, the well-formed
 * submit below rendered "Failed to fetch" with the route counter still at
 * zero. A route-only assertion would have read zero whether the form validated
 * or not — a check that cannot fail. (The directive lives in
 * `lib/security/csp.ts`, not `next.config.ts` as this note used to say; it
 * moved when the policy became per-request and nonce-based.)
 *
 * SINCE #740 the directive is built from `NEXT_PUBLIC_SUPABASE_URL`, so under
 * the placeholder the policy names the placeholder and these fetches are no
 * longer blocked in the page. That changes what the route counter sees for a
 * submit the form ALLOWS — the positive control below now reaches the route as
 * well as the wrapper — and changes nothing for the cases this file is about,
 * where the form refuses and no fetch is issued at all. `expectNoAuthTraffic`
 * still asserts both, and the wrapper is still the primary instrument: it is
 * the one that cannot be made vacuous by a policy, an offline runner or a
 * DNS failure.
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

/**
 * #741. `/callback` builds every failure redirect from `new URL("/login",
 * origin)` where `origin` comes from `request.url` — so the question of what
 * decides that origin is a security question before it is a harness one.
 *
 * MEASURED, on both `next dev` and a real `next start` production build, six
 * configurations: request via `localhost`, request via `127.0.0.1`,
 * `Host: example.test`, `Host: 127.0.0.1`, the server bound to the default
 * host, and the server bound to `127.0.0.1` explicitly. Every one of them
 * answered `location: http://localhost:<port>/login?error=missing_code`.
 * `request.url`'s host follows NEITHER the `Host` header NOR `--hostname`.
 *
 * That is the safe default and this test pins it. Trusting a client-supplied
 * `Host` to build a redirect target is how host-header injection works: an
 * attacker who can make a victim's browser hit `/callback` with their own
 * `Host` would have the app hand the victim a redirect to their domain. The
 * issue's original closing condition — "a test driving the suite at a
 * non-localhost host" — is therefore deliberately NOT met here; it would be
 * asserting the behaviour this test exists to forbid.
 *
 * RAW `node:http`, NOT `page.goto` OR `request.get`. A browser refuses to set
 * `Host` at all, and an API client that silently dropped it would make this
 * pass for the wrong reason — the vacuity this repo keeps finding. A raw
 * socket write is the only instrument where what was sent is not in doubt, and
 * the control below reads the header back off the request object rather than
 * assuming it went out.
 */
test.describe("the callback's redirect target is not client-controlled (#741)", () => {
  const INJECTED = "attacker.example";

  /** One request, raw, with an explicit `Host`. Returns status + location. */
  async function callbackWithHost(
    baseURL: string,
    host: string,
  ): Promise<{ status: number; location: string; sent: string | undefined }> {
    const { request } = await import("node:http");
    const target = new URL("/callback", baseURL);
    return await new Promise((resolve, reject) => {
      const req = request(
        {
          hostname: target.hostname,
          port: target.port,
          path: target.pathname,
          method: "GET",
          headers: { Host: host },
        },
        (res) => {
          res.resume();
          resolve({
            status: res.statusCode ?? 0,
            location: String(res.headers.location ?? ""),
            sent: req.getHeader("Host") as string | undefined,
          });
        },
      );
      req.on("error", reject);
      req.end();
    });
  }

  test("a client-supplied Host header cannot move it", async ({ baseURL }) => {
    const injected = await callbackWithHost(baseURL!, INJECTED);

    // THE CONTROL: the header really was on the request. Without this the
    // assertion below passes just as well against a client that never sent it.
    expect(injected.sent, "the Host header was never put on the request").toBe(INJECTED);

    expect(injected.status, "/callback with no code should redirect").toBe(307);
    expect(injected.location).not.toContain(INJECTED);
    expect(
      injected.location,
      "the redirect followed the client's Host header — this is host-header injection",
    ).toMatch(/^https?:\/\/[^/]*localhost/);
  });

  test("and it answers the same thing without one", async ({ baseURL }) => {
    // The second arm of a one-variable pair: same request, honest Host. If the
    // two answers differed at all, the header would be influencing something.
    const honest = await callbackWithHost(baseURL!, new URL(baseURL!).host);
    const injected = await callbackWithHost(baseURL!, INJECTED);

    expect(honest.status).toBe(307);
    expect(injected.location).toBe(honest.location);
  });
});

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
