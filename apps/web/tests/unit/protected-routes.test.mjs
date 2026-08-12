/**
 * Every page under `app/(app)/` must be gated by the proxy, not only by the
 * layout.
 *
 * Both mechanisms redirect a signed-out visitor, so the omission is invisible
 * to any "does it redirect?" test — which is why it survived. The difference is
 * where you land afterwards: the proxy sends you to
 * `/login?redirect=<where you were going>` and the login form honours it, while
 * `app/(app)/layout.tsx`'s defence-in-depth `redirect("/login")` carries no
 * such hint and drops you on the dashboard.
 *
 * Measured against production before the fix:
 *
 *     /dashboard  →  307  /login?redirect=%2Fdashboard
 *     /inbox      →  307  /login
 *     /settings   →  307  /login
 *
 * `/inbox` and `/settings` had been in `app/(app)/` since they were written and
 * were never added to the list, even though the middleware's own comment says
 * to extend it when adding a protected page. So this test derives the expected
 * set from the directory rather than restating it: a new protected page fails
 * here on the commit that creates it.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  PROTECTED_PREFIXES,
  isProtectedPath,
} from "../../lib/supabase/protectedRoutes.ts";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const appGroupDir = join(webRoot, "app", "(app)");

/** URL prefixes implied by the directories inside `app/(app)/`. */
function routesInProtectedGroup() {
  return readdirSync(appGroupDir, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    // A route group in parentheses contributes no URL segment; a page needs a
    // page.tsx to exist at all.
    .filter((e) => !e.name.startsWith("(") && !e.name.startsWith("_"))
    .filter((e) => existsSync(join(appGroupDir, e.name, "page.tsx")))
    .map((e) => `/${e.name}`);
}

test("the protected group is not empty — otherwise this file proves nothing", () => {
  // Guards the guard. If the directory moved, every assertion below would pass
  // vacuously against an empty list.
  assert.ok(
    routesInProtectedGroup().length >= 3,
    `expected pages under app/(app)/, found ${JSON.stringify(routesInProtectedGroup())}`,
  );
});

test("every page in app/(app)/ is gated by the proxy", () => {
  const missing = routesInProtectedGroup().filter(
    (route) => !PROTECTED_PREFIXES.includes(route),
  );

  assert.deepEqual(
    missing,
    [],
    `these pages live in app/(app)/ but are not in PROTECTED_PREFIXES, so a ` +
      `signed-out visitor is redirected by the layout instead of the proxy and ` +
      `loses their return path after signing in: ${missing.join(", ")}`,
  );
});

test("the list names no route that does not exist", () => {
  const known = routesInProtectedGroup();
  const stale = PROTECTED_PREFIXES.filter((p) => !known.includes(p));
  assert.deepEqual(stale, [], `PROTECTED_PREFIXES names removed routes: ${stale.join(", ")}`);
});

test("matching covers the page and everything beneath it, and nothing else", () => {
  assert.equal(isProtectedPath("/settings"), true);
  assert.equal(isProtectedPath("/settings/billing"), true);
  assert.equal(isProtectedPath("/inbox"), true);
  assert.equal(isProtectedPath("/dashboard"), true);

  // Public routes must stay public — a prefix match that is too eager here
  // would lock signed-out visitors out of the demo and the landing.
  assert.equal(isProtectedPath("/"), false);
  assert.equal(isProtectedPath("/demo"), false);
  assert.equal(isProtectedPath("/demo/inbox"), false);
  assert.equal(isProtectedPath("/import"), false);
  assert.equal(isProtectedPath("/login"), false);

  // A path that merely STARTS with the same characters is a different route.
  assert.equal(isProtectedPath("/settings-export"), false);
  assert.equal(isProtectedPath("/inboxes"), false);
});
