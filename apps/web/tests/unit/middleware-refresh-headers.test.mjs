/**
 * A response that carries refreshed Supabase auth cookies must also carry the
 * no-store headers `@supabase/ssr` hands to `setAll`.
 *
 * WHAT THE LIBRARY ACTUALLY DOES. Since 0.12.x, `SetAllCookies` takes a SECOND
 * parameter — `node_modules/@supabase/ssr/src/types.ts:32-59` types it and says
 * why: "Responses that set auth cookies must not be cached by CDNs or reverse
 * proxies, otherwise one user's session token can be served to a different
 * user." `applyServerStorage` passes it at `src/cookies.ts:632-658` (shipped
 * identically at `dist/main/cookies.js:499-503`), and
 * `createServerClient.ts:173-198` fires that path on `TOKEN_REFRESHED`.
 *
 * WHY NO EXISTING GATE CAUGHT IT. `lib/supabase/middleware.ts` declares its
 * `setAll` with one parameter. TypeScript assigns a one-parameter function to a
 * two-parameter callback type without complaint — that is sound, ordinary
 * variance, not a bug in the checker — so `tsc --noEmit` was always going to
 * pass and the headers were dropped silently.
 *
 * HOW THIS TEST WORKS. It does not restate the header values. The harness in
 * `helpers/middlewareSession.mjs` drives the REAL `applyServerStorage` out of
 * the installed package twice:
 *
 *   1. against a probe `setAll`, to learn what the installed version actually
 *      passes — the expected set is whatever the library ships, so a bump that
 *      changes or adds a header is compared against the new value, not a stale
 *      literal frozen into this file;
 *   2. against the app's real `setAll`, reached by loading the real
 *      `lib/supabase/middleware.ts` with only `@supabase/ssr` stubbed, so the
 *      response object under assertion is the one `updateSession` returns.
 *
 * The middleware rebuilds its response inside `setAll`
 * (`supabaseResponse = NextResponse.next({ request })`), which is the correct
 * `@supabase/ssr` shape for keeping refreshed tokens flowing. This test pins
 * the consequence that shape has for anything set before that line: the headers
 * must be applied AFTER the rebuild, or they do not survive it.
 *
 * The sibling file `middleware-redirect-session.test.mjs` (#241) pins the same
 * property on the REDIRECT exits, which return a different response object.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  libraryEmission,
  runUpdateSession,
} from "./helpers/middlewareSession.mjs";

test("the installed @supabase/ssr passes headers alongside refreshed cookies", async () => {
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

test("a refreshed session response carries the library's no-store headers", async () => {
  const { headers: expected } = await libraryEmission();
  const response = await runUpdateSession("/dashboard");

  for (const [name, value] of Object.entries(expected)) {
    assert.equal(
      response.headers.get(name),
      value,
      `"${name}" did not survive the response rebuild in setAll. A response carrying fresh auth cookies must not be cacheable — see the module comment.`,
    );
  }
});

test("the refreshed cookies still reach the browser", async () => {
  // Guards the fix: preserving headers must not cost the cookies, which are
  // the reason the rebuild exists at all.
  const { cookies: expected } = await libraryEmission();
  const response = await runUpdateSession("/dashboard");

  for (const { name } of expected) {
    assert.ok(
      response.cookies.get(name) !== undefined,
      `refreshed cookie "${name}" is missing from the response`,
    );
  }
});
