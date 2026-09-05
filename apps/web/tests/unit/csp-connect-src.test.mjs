/**
 * `connect-src` must name the Supabase project THIS deployment is pointed at.
 *
 * THE DEFECT (#740). The directive was a literal: `connect-src 'self'
 * https://<one project ref>.supabase.co`, frozen into `lib/security/csp.ts`.
 * A deployment configured against any other Supabase project — a fork, a
 * staging project, a restored project with a new ref, CI — built green and
 * then shipped a policy that blocks its own auth traffic. Nothing type-checks
 * a hostname, and no gate in this repo looked at this directive: before this
 * file, `git grep -n connect-src -- apps/web` returned the constant, the
 * System Card's separate policy, and one comment. Zero assertions. The same
 * grep for `script-src` returned four files.
 *
 * WHAT IT COSTS IS SIGN-IN, NOT A REFRESH. Every browser-side Supabase call
 * goes to this origin and is blocked at the FIRST attempt:
 * `signInWithPassword` on /login, `signOut`, signup, forgot-password,
 * `SetNewPasswordForm`, the Google button, and the whole live half of
 * `lib/settings/transport.ts`. Meanwhile `app/api/**` is same-origin and keeps
 * answering under `'self'`, so uptime checks, smoke tests and the server logs
 * all read healthy while nobody can log in.
 *
 * AND IT HAS ALREADY HAPPENED HERE. `tests/e2e/auth.spec.ts` documents CI and
 * local dev running against the placeholder `https://example.supabase.co` with
 * the old policy naming the real project: "the fetch fails in the page and no
 * request is ever routed". That is this defect, observed, and it is the reason
 * that spec needed a second instrument to see anything at all.
 *
 * WHY THE ORIGIN IS AN ARGUMENT AND THIS TEST DOES NOT TOUCH `process.env`.
 * `NEXT_PUBLIC_*` is inlined by Next as literal text at build time — `lib/env.ts`
 * says so, and says it is why those reads are spelled out in full rather than
 * indexed. So a test that set `process.env.NEXT_PUBLIC_SUPABASE_URL` would be
 * exercising a runtime lookup production does not perform, and would pass
 * whatever the shipped bundle actually contains. The parameter exists so the
 * value can be VARIED by a caller, which is the only thing that distinguishes
 * a policy built from configuration from one with a host baked in.
 *
 * WHY NO ASSERTION NAMES THE REAL PROJECT. An expectation asserting the
 * current project's host would have passed against the hardcoded literal too
 * — a check that cannot fail, which is the exact shape #740 is made of. Both
 * fixtures below are invented refs, and neither is this deployment's. That
 * also keeps a project ref out of a new file in a public repo.
 *
 * THE CONTROL. Restoring the literal to `lib/security/csp.ts` reds the first
 * two tests here. Run before this landed.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { buildNonceCsp } from "../../lib/security/csp.ts";

/**
 * Two fabricated project refs. TWO, not one: a single fixture is satisfied by
 * re-hardcoding that one value, so it would prove the policy contains a
 * string and not that the string came from the caller.
 */
const ALPHA = "https://alpha-project-ref.supabase.co";
const BETA = "https://beta-project-ref.supabase.co";

/** Fixed, because nothing here is testing the nonce — only that it survives. */
const NONCE = "e2ecfbb14d9a4f0b8c1d7a3f6b52e08d";

/** The policy, split the way `buildNonceCsp` joins it. */
const directives = (policy) => policy.split("; ");

/**
 * The one `connect-src` directive, asserting there is exactly one. Two would
 * be a policy the browser intersects, and zero would make every comparison
 * below a comparison against `undefined`.
 */
function connectSrcOf(policy) {
  const found = directives(policy).filter((d) => d.startsWith("connect-src"));
  assert.equal(
    found.length,
    1,
    `expected exactly one connect-src directive, found ${found.length} in: ${policy}`,
  );
  return found[0];
}

test("the origin the caller passes is the origin the policy names", () => {
  // Exact equality, not `.includes`. A substring check still passes when a
  // second, hardcoded host is appended to the directive — which is the defect
  // wearing a slightly different hat.
  assert.equal(connectSrcOf(buildNonceCsp(NONCE, ALPHA)), `connect-src 'self' ${ALPHA}`);
  assert.equal(connectSrcOf(buildNonceCsp(NONCE, BETA)), `connect-src 'self' ${BETA}`);
});

test("no remote origin reaches the policy except the one passed in", () => {
  // The whole policy, not just `connect-src`: this is what actually forbids a
  // baked-in host, wherever in the string someone puts it. `'self'` and the
  // scheme-less sources are not absolute URLs and are not matched.
  for (const origin of [ALPHA, BETA]) {
    const remotes = [...buildNonceCsp(NONCE, origin).matchAll(/https?:\/\/[^\s;]+/g)].map(
      (m) => m[0],
    );
    assert.deepEqual(
      remotes,
      [origin],
      `the policy reaches a remote origin the caller never asked for (built for ${origin})`,
    );
  }
});

test("nothing but connect-src moves when the origin changes", () => {
  // Non-interference, diffed rather than eyeballed. Building both in this one
  // process holds `NODE_ENV` — and therefore the `'unsafe-eval'` dev gate on
  // `script-src` — identical across the pair, so any difference here is
  // genuinely attributable to the origin.
  const withoutConnectSrc = (policy) =>
    directives(policy).filter((d) => !d.startsWith("connect-src"));

  assert.deepEqual(
    withoutConnectSrc(buildNonceCsp(NONCE, ALPHA)),
    withoutConnectSrc(buildNonceCsp(NONCE, BETA)),
  );
});

test("the fixtures and the policy are non-degenerate, so the above can fail", () => {
  // Every assertion in this file compares two built policies or a directive
  // against a fixture. All of them pass vacuously against a collapsed policy
  // or a pair of identical fixtures, so both are pinned.
  assert.notEqual(ALPHA, BETA, "one fixture used twice compares nothing");

  const policy = buildNonceCsp(NONCE, ALPHA);
  assert.ok(
    directives(policy).length >= 9,
    `the policy collapsed to ${directives(policy).length} directive(s)`,
  );
  assert.match(policy, /script-src [^;]*'nonce-e2ecfbb14d9a4f0b8c1d7a3f6b52e08d'/);
});
