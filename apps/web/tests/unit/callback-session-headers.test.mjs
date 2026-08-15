/**
 * The PKCE callback responses carry the INITIAL session cookies, so they must
 * also carry the no-store headers `@supabase/ssr` hands to `setAll`.
 *
 * WHY THIS GATE EXISTS. #234/#240 fixed the same defect in
 * `lib/supabase/middleware.ts`; #242 is the other `setAll`, in
 * `lib/supabase/server.ts`. Nothing failed either time, and the reason is worth
 * stating because it decides what this file must assert: TypeScript assigns a
 * ONE-parameter function to the library's two-parameter `SetAllCookies` type
 * without complaint — ordinary, sound variance — so `tsc --noEmit` cannot see a
 * dropped `headers` parameter. Nor can it see a `setAll` that ACCEPTS the
 * parameter and ignores it, which is what `server.ts` did between #248 and
 * #242. An arity check would have gone green on that state. So this test is
 * behavioural: it asserts the headers reach the response the handler returns.
 *
 * WHAT IS OBSERVED, NOT ASSUMED. On a production build (`next build &&
 * next start`) against a local fake auth server, a real exchange through
 * `/callback` returned a 307 carrying `sb-<ref>-auth-token=<session>` and no
 * cache directive of any kind, with `cookieStore.set` succeeding — the catch in
 * `server.ts` does NOT fire in a Route Handler. The harness therefore uses a
 * cookie jar whose writes succeed; see `helpers/callbackSession.mjs`.
 *
 * BOTH handlers are covered. `/reset-password/callback` builds its redirect
 * BEFORE the client exists, so the headers have to be applied to that
 * already-constructed object after the exchange — a different mistake from the
 * one `/callback` can make, and invisible if only one route were tested.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  CALLBACK_ROUTES,
  FAILING_CODE,
  libraryEmission,
  runCallback,
} from "./helpers/callbackSession.mjs";

test("the installed @supabase/ssr passes headers alongside the session cookies", async () => {
  const emitted = await libraryEmission();

  assert.ok(
    emitted !== null,
    "applyServerStorage never called setAll — the fixture no longer produces a cookie write, so every assertion below would be vacuous",
  );
  assert.ok(
    emitted.cookies.length > 0,
    "expected at least one cookie write to carry the session",
  );
  assert.ok(
    Object.keys(emitted.headers ?? {}).length > 0,
    "the installed @supabase/ssr passed no headers to setAll. If a version bump legitimately removed them, this whole test is obsolete — delete it rather than weakening it.",
  );
});

for (const route of CALLBACK_ROUTES) {
  test(`${route.name} writes the session cookies through the route handler`, async () => {
    // Vacuity guard for the two tests below: if the exchange stopped writing
    // cookies, a response with no headers would be correct and they would pass
    // while asserting nothing.
    const { writes } = await runCallback(route);

    assert.ok(
      writes.length > 0,
      "the handler set no cookies at all — the exchange did not reach setAll, so the header assertions would be vacuous",
    );
  });

  test(`${route.name} response carries the library's no-store headers`, async () => {
    const { headers: expected } = await libraryEmission();
    const { response } = await runCallback(route);

    for (const [name, value] of Object.entries(expected)) {
      assert.equal(
        response.headers.get(name),
        value,
        `"${name}" never reached the response from ${route.name}. A response carrying fresh auth cookies must not be cacheable — see lib/supabase/server.ts.`,
      );
    }
  });

  test(`${route.name} still redirects, and still sets the cookies`, async () => {
    // Guards the fix: applying headers must not cost the redirect or the
    // cookies, which are the reason the handler exists.
    const { response, writes } = await runCallback(route);
    const { cookies: expected } = await libraryEmission();

    assert.equal(response.status, 307, `${route.name} stopped redirecting`);
    for (const { name } of expected) {
      assert.ok(
        writes.some((write) => write.name === name),
        `session cookie "${name}" was never written by ${route.name}`,
      );
    }
  });

  test(`${route.name} still redirects when the exchange fails`, async () => {
    // The failure branch also runs `applySessionHeaders`. It must be a no-op
    // rather than a throw when the library never wrote anything.
    const { response } = await runCallback(route, { code: FAILING_CODE });

    assert.equal(response.status, 307);
  });
}
