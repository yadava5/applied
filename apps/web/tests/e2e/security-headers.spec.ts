import { test, expect } from "@playwright/test";

import { securityHeaders } from "../../next.config";

/**
 * The response envelope, which the rest of this suite treats as out of scope.
 *
 * `next.config.ts` sets five security headers on `source: "/(.*)"` — every
 * route, public included. Nothing in this repository read one off a live
 * response, so #600 changed `X-Frame-Options` from `DENY` to `SAMEORIGIN`,
 * rebuilt, and served it:
 *
 *     curl -sI http://127.0.0.1:3000/  ->  X-Frame-Options: SAMEORIGIN
 *     PLAYWRIGHT_PROD_BUILD=1 playwright test  ->  299 passed, exit 0
 *     pnpm test:unit                           ->  617 passed, exit 0
 *
 * (Those two counts are #600's, measured on 2026-08-29. The suite has grown
 * since; they are quoted as the record of that pass, not as current totals.)
 *
 * A clickjacking-relevant downgrade on every public page, invisible to the
 * whole estate. The suite exercises what is RENDERED; this asserts what is
 * SENT.
 *
 * IMPORTED **AND** RETYPED, because the two catch different things and the
 * first draft of this file shipped only one of them.
 *
 * Importing the list catches DRIFT: a header the config declares that never
 * reaches the wire, which is what a platform or proxy change looks like. It
 * cannot catch an EDIT. `expect(served[key]).toBe(value)` with `value` read
 * from the config compares the config against itself, so changing
 * `X-Frame-Options` to `SAMEORIGIN` moves the served header and the
 * expectation together and the test stays green. Measured, all five values
 * mutated one at a time, served and confirmed by `curl`: **5 of 5 green**,
 * including #600's literal `DENY` -> `SAMEORIGIN`.
 *
 * So `POLICY` below is deliberately hand-written. It is NOT the #590 defect of
 * a retyped copy drifting from its source: a security header's value is a
 * DECISION, and a decision needs a second party. `expectedFromConfig` holds the
 * two together, so a legitimate policy change reds this file and has to be
 * made twice, on purpose, in the same commit.
 *
 * NOT PROD-GATED, deliberately. `next.config.ts`'s `headers()` applies under
 * `next dev` as well, and #600's third question was whether this belongs to the
 * dev job too. It does: the dev job runs on every frontend PR, and a header
 * downgrade is not a production-only mistake. `production.spec.ts` is where
 * things that genuinely need `next start` live, and this is not one of them.
 *
 * Content-Security-Policy is deliberately absent from the imported list — it is
 * built per request with a nonce in `lib/security/csp.ts` and owned by
 * `scripts/csp-gate.mjs`, which compares the served header against the served
 * body. Asserting a constant CSP here would fight that.
 */

/** A public route: no session, no redirect, and the surface a stranger loads. */
const PUBLIC_ROUTE = "/";

/**
 * The policy, written out. Changing a value here AND in `next.config.ts` is the
 * supported way to change a security header; changing it in only one place is
 * what this file exists to stop.
 */
const POLICY: Record<string, string> = {
  "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
};

test.describe("security headers", () => {
  test("a public response carries the policy this app committed to", async ({
    request,
  }) => {
    const response = await request.get(PUBLIC_ROUTE);

    // The response has to be real before any header assertion means anything.
    // A 404 or a redirect carries its own headers and would let the loop below
    // pass against a page that is not the one under test.
    expect(response.status(), `${PUBLIC_ROUTE} did not answer 200`).toBe(200);

    const received = response.headers();
    for (const [key, value] of Object.entries(POLICY)) {
      expect(
        received[key.toLowerCase()],
        `${key} is missing or downgraded on ${PUBLIC_ROUTE}. The policy is ` +
          `"${value}". Every route matches source: "/(.*)", so a difference ` +
          `here ships on every public page. If this change is intended, edit ` +
          `POLICY in this file as well as next.config.ts — deliberately two ` +
          `edits, because a security header's value is a decision.`,
      ).toBe(value);
    }
  });

  test("next.config.ts declares exactly the policy, in both directions", () => {
    // The half that needs no server, and the half that reds on an edit. Without
    // it, `securityHeaders` and POLICY could drift apart with the suite green:
    // the test above would keep passing on whatever the config happened to
    // serve, because it would be reading its expectation from the same place.
    //
    // BOTH DIRECTIONS, and the second one is not symmetry for its own sake. A
    // first draft asserted only POLICY ⊆ declared. Adding a sixth entry to
    // `securityHeaders` then put a new header on every public response — served,
    // confirmed by `curl` — with all three tests GREEN, because POLICY did not
    // name it, so nothing visited it. An ADDED header is a policy change like
    // any other and needs the same second party a changed one does.
    const declared = Object.fromEntries(securityHeaders.map((h) => [h.key, h.value]));

    expect(
      declared,
      "next.config.ts and POLICY disagree. Every difference here reaches every " +
        "public response, so changing one without the other is the defect this " +
        "file exists to catch — including ADDING a header.",
    ).toEqual(POLICY);

    // Absolute, not relative to POLICY. `securityHeaders.length >= POLICY.length`
    // is satisfied at 0 >= 0, and every loop in this file then iterates zero
    // times and reports a pass.
    expect(
      Object.keys(POLICY).length,
      "POLICY has been emptied, so nothing above asserts anything.",
    ).toBeGreaterThanOrEqual(5);
  });

  test("nothing the config declares goes missing on the wire", async ({ request }) => {
    // The drift half, and the reason the list is imported at all. A header
    // ADDED to next.config.ts but never served is invisible to both tests
    // above, because POLICY does not know about it. This is also the control
    // that catches `source` no longer matching the route: measured by breaking
    // it to "/no-such-path-xyz" with every value untouched — the server stays
    // up, answers 200, and this reds.
    const response = await request.get(PUBLIC_ROUTE);
    expect(response.status()).toBe(200);
    const received = response.headers();

    expect(
      securityHeaders.length,
      "next.config.ts declares no security headers at all, so the loop below " +
        "would iterate zero times and report a pass.",
    ).toBeGreaterThanOrEqual(5);

    for (const { key, value } of securityHeaders) {
      expect(received[key.toLowerCase()], `${key} is declared but not served`).toBe(value);
    }
  });
});
