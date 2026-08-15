/**
 * Every page behind the auth boundary must be gated by the proxy, not only by
 * the layout — and every page that is NOT behind it must be there on purpose.
 *
 * Both mechanisms redirect a signed-out visitor, so the omission is invisible
 * to any "does it redirect?" test — which is why it survived. The difference is
 * where you land afterwards: the proxy sends you to
 * `/login?redirect=<where you were going>` and the login form honours it, while
 * the layout's defence-in-depth `redirect("/login")` carries no such hint and
 * drops you on the dashboard.
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
 * WHY THERE ARE NOW TWO HALVES. `app/(app)/` stopped meaning "protected" when
 * `/import` and `/privacy` moved into it. They had to move: the app shell is
 * mounted by `app/(app)/layout.tsx`, and a shell rendered from inside a page —
 * which is what those two used to do — is a DIFFERENT React subtree, so
 * navigating to either tore the whole shell down and rebuilt it mid-session.
 * Both routes are public at the same URL by requirement (the no-sign-in mail
 * import; the policy document Google's reviewer fetches anonymously), so the
 * auth boundary moved down one level to the `(protected)` route group and the
 * shell stayed up top.
 *
 * Repointing this file at `(protected)/` alone would have LOST the property the
 * paragraphs above describe: a new page added under `app/(app)/` but outside
 * `(protected)/` would be silently public with every assertion green — the
 * "checks that cannot fail" shape. So the second half exists: everything under
 * `app/(app)/` that is not in `(protected)/` must be named on `PUBLIC_IN_SHELL`
 * below. There is no way to add a route to this group that neither gate sees.
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
const protectedGroupDir = join(appGroupDir, "(protected)");

/**
 * The routes that are DELIBERATELY reachable without a session while still
 * wearing the app shell when there is one. Adding a directory to `app/(app)/`
 * outside `(protected)/` without adding it here is a failure, and it should be:
 * the choice to leave a route ungated is exactly the kind that must be typed
 * out rather than inferred from where a folder happens to sit.
 */
const PUBLIC_IN_SHELL = ["/import", "/privacy"];

/** The URL segments a directory listing contributes: a page needs a `page.tsx`,
 *  and a name in parentheses is a route group that contributes no segment. */
function routeDirs(dir) {
  return readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .filter((e) => !e.name.startsWith("(") && !e.name.startsWith("_"))
    .filter((e) => existsSync(join(dir, e.name, "page.tsx")))
    .map((e) => `/${e.name}`)
    .sort();
}

/** URL prefixes implied by the directories inside `app/(app)/(protected)/`. */
function routesInProtectedGroup() {
  return routeDirs(protectedGroupDir);
}

/** Routes inside the shell group but OUTSIDE the auth boundary. */
function publicRoutesInShell() {
  return routeDirs(appGroupDir);
}

/** Every route group nested directly inside `app/(app)/`. */
function nestedGroups() {
  return readdirSync(appGroupDir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && e.name.startsWith("("))
    .map((e) => e.name)
    .sort();
}

test("the protected group is not empty — otherwise this file proves nothing", () => {
  // Guards the guard. If the directory moved, every assertion below would pass
  // vacuously against an empty list. `readdirSync` THROWS on a missing
  // directory, which is the louder half of the same protection.
  assert.ok(
    routesInProtectedGroup().length >= 3,
    `expected pages under app/(app)/(protected)/, found ${JSON.stringify(routesInProtectedGroup())}`,
  );
});

test("`(protected)` is the only route group inside the shell group", () => {
  // The second half below reasons about DIRECT children of `app/(app)/`. A
  // second nested group would hide routes from both halves — a group name
  // contributes no URL segment, so its pages would be neither scanned as
  // protected nor listed as public. Rather than recurse into a structure nobody
  // has chosen yet, fail and make the choice explicit.
  assert.deepEqual(
    nestedGroups(),
    ["(protected)"],
    "a new route group under app/(app)/ hides its pages from both halves of " +
      "this file — decide what it is for, then teach this test about it",
  );
});

test("every page in app/(app)/(protected)/ is gated by the proxy", () => {
  const missing = routesInProtectedGroup().filter(
    (route) => !PROTECTED_PREFIXES.includes(route),
  );

  assert.deepEqual(
    missing,
    [],
    `these pages live in app/(app)/(protected)/ but are not in ` +
      `PROTECTED_PREFIXES, so a signed-out visitor is redirected by the layout ` +
      `instead of the proxy and loses their return path after signing in: ` +
      `${missing.join(", ")}`,
  );
});

test("every page in app/(app)/ outside (protected)/ is a declared public route", () => {
  // The complementary half. Without it, repointing the scan at `(protected)/`
  // would let a route added one level up ship ungated with this file green.
  assert.deepEqual(
    publicRoutesInShell(),
    [...PUBLIC_IN_SHELL].sort(),
    "a route under app/(app)/ is outside the (protected) group, so NOTHING " +
      "redirects a signed-out visitor away from it — neither the proxy nor a " +
      "layout. If that is intended, name it in PUBLIC_IN_SHELL; if not, move " +
      "it into app/(app)/(protected)/",
  );
});

test("the declared public routes really are ungated", () => {
  // The other direction: a route on the allowlist that ALSO sits in
  // PROTECTED_PREFIXES would be redirected by the proxy, and the public page it
  // exists to serve — the no-sign-in import, the policy Google fetches
  // anonymously — would be unreachable. Both mistakes are one edit apart.
  for (const route of PUBLIC_IN_SHELL) {
    assert.equal(
      isProtectedPath(route),
      false,
      `${route} is declared public but matches PROTECTED_PREFIXES, so the ` +
        `proxy bounces anonymous visitors to /login`,
    );
  }
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
