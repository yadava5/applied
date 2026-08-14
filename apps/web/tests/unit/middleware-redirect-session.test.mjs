/**
 * NO EXIT FROM `updateSession` MAY DROP THE RESPONSE.
 *
 * `lib/supabase/middleware.ts` builds `supabaseResponse` and lets
 * `@supabase/ssr` write onto it: the rotated auth cookies, and (since #240) the
 * no-store headers the library passes to `setAll`. Both redirect branches used
 * to `return NextResponse.redirect(url)` — a brand-new response — throwing all
 * of that away. Supabase had already rotated the refresh token server-side, so
 * the browser kept presenting a token the server had spent. That is the
 * "random logout" signature (#241).
 *
 * WHY THIS FILE HAS TWO KINDS OF TEST.
 *
 *   1. BEHAVIOUR — every exit is driven with a session that changes mid-flight,
 *      and the response it returns must carry the cookies and headers the
 *      INSTALLED library emitted for that scenario. Expectations are derived at
 *      runtime from `applyServerStorage`, never restated as literals, so a
 *      version bump is compared against the new values (#240's idiom).
 *
 *   2. SHAPE — the exits are enumerated out of the source. An assertion that
 *      only covered the exits visible today would not catch the fourth one
 *      somebody adds next month, and this file has now produced this same
 *      defect twice. So every `return` in `updateSession` must hand back either
 *      `supabaseResponse` or a call to `redirectPreservingSession`, whose
 *      behaviour the tests above pin. A new bare `NextResponse.redirect` goes
 *      red on the shape test even though no behaviour test knows the branch
 *      exists.
 *
 * The shape test is the kind that quietly stops testing anything, so it carries
 * its own negative controls: it is run against a deliberately broken source and
 * must reject it, and against a source with no exits at all — an `every()` over
 * an empty list is green, which is exactly how this sort of gate dies.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import ts from "typescript";

import {
  MIDDLEWARE_PATH,
  REFRESH,
  SESSION,
  SIGN_OUT,
  libraryEmission,
  readMiddlewareSource,
  runUpdateSession,
} from "./helpers/middlewareSession.mjs";

/** The only two things an exit of `updateSession` is allowed to return. */
const RESPONSE_IDENTIFIER = "supabaseResponse";
const REDIRECT_HELPER = "redirectPreservingSession";

/* -------------------------------------------------------------------------- */
/* 1. BEHAVIOUR — drive every exit                                             */
/* -------------------------------------------------------------------------- */

/**
 * Every branch `updateSession` can leave through, with a session event that
 * makes the library write cookies while the response is being built.
 *
 * The signed-out case uses `SIGN_OUT`, not `REFRESH`: when a session cannot be
 * revived the library emits `maxAge: 0` deletions rather than a write. Dropping
 * those is the first branch's own failure mode — stale chunked auth cookies
 * left in the browser — and it needs its own fixture to be reached at all.
 */
const EXITS = [
  {
    what: "protected path, session gone → redirect to /login",
    pathname: "/dashboard",
    options: { user: null, scenario: SIGN_OUT },
    redirectsTo: "/login",
  },
  {
    what: "signed-in user on /login → redirect to /dashboard",
    pathname: "/login",
    options: { user: SESSION.user, scenario: REFRESH },
    redirectsTo: "/dashboard",
  },
  {
    what: "signed-in user on a protected path → pass through",
    pathname: "/dashboard",
    options: { user: SESSION.user, scenario: REFRESH },
    redirectsTo: null,
  },
];

for (const { what, pathname, options } of EXITS) {
  test(`${what}: the rotated cookies reach the browser`, async () => {
    const emitted = await libraryEmission(options.scenario);
    assert.ok(
      emitted !== null && emitted.cookies.length > 0,
      "the fixture produced no cookie write at all, so this assertion would be vacuous — fix the scenario, not the assertion",
    );

    const response = await runUpdateSession(pathname, options);

    for (const { name, value, options: cookieOptions } of emitted.cookies) {
      const got = response.cookies.get(name);
      assert.ok(
        got !== undefined,
        `"${name}" is missing from the response. Supabase already rotated this token server-side; a response that does not carry it leaves the browser holding a spent one — see #241.`,
      );
      assert.equal(got.value, value, `"${name}" carries the wrong value`);
      assert.equal(
        got.maxAge,
        cookieOptions.maxAge,
        `"${name}" carries the wrong Max-Age. A deletion (Max-Age=0) that arrives as a write, or the reverse, is the same bug in the other direction.`,
      );
    }
  });

  test(`${what}: the no-store headers reach the browser`, async () => {
    const { headers: expected } = await libraryEmission(options.scenario);
    assert.ok(
      Object.keys(expected ?? {}).length > 0,
      "the installed @supabase/ssr passed no headers to setAll; if a version bump removed them this test is obsolete, delete it rather than weakening it",
    );

    const response = await runUpdateSession(pathname, options);

    for (const [name, value] of Object.entries(expected)) {
      assert.equal(
        response.headers.get(name),
        value,
        `"${name}" is missing from the response. A response carrying auth cookies must not be cacheable by a shared cache (#234/#240) — and that applies to redirects too.`,
      );
    }
  });
}

/**
 * Headers Next puts on its own `next()` response that must not be carried onto
 * a 307.
 *
 * `NextResponse.next({ request })` sets `x-middleware-next: 1` and the
 * `x-middleware-override-headers` / `x-middleware-request-*` family: continue
 * to the route, with these request headers rewritten. On a redirect there is no
 * route to continue to. Copying the whole header set across — the obvious way
 * to write this fix, and what the issue's sketch does — would put "continue to
 * the route" on a 307. Verified present on a `next()` response under Next 16.3.
 *
 * `x-middleware-set-cookie` is deliberately NOT in this list. It is not
 * something the fix chose to carry: `NextResponse#cookies.set` writes it on any
 * response, a bare `NextResponse.redirect` included, and it is Next's own
 * channel for propagating a middleware cookie write. Next consumes it; it does
 * not reach the browser (confirmed on the wire against a production build).
 */
const FORBIDDEN_ON_REDIRECT = (name) =>
  name.startsWith("x-middleware-") && name !== "x-middleware-set-cookie";

test("a redirect exit is still a redirect, and carries no request-rewrite plumbing", async () => {
  for (const { pathname, options, redirectsTo } of EXITS) {
    if (redirectsTo === null) continue;
    const response = await runUpdateSession(pathname, options);

    assert.equal(response.status, 307, `${pathname} stopped redirecting`);
    assert.equal(
      new URL(response.headers.get("location")).pathname,
      redirectsTo,
      `${pathname} redirected somewhere unexpected`,
    );
    const plumbing = [...response.headers.keys()].filter(FORBIDDEN_ON_REDIRECT);
    assert.deepEqual(
      plumbing,
      [],
      `${pathname} carried Next's request-rewrite plumbing onto a redirect: ${plumbing.join(", ")}`,
    );
  }
});

/* -------------------------------------------------------------------------- */
/* 2. SHAPE — enumerate the exits                                              */
/* -------------------------------------------------------------------------- */

const FUNCTION_LIKE = [
  ts.isFunctionDeclaration,
  ts.isFunctionExpression,
  ts.isArrowFunction,
  ts.isMethodDeclaration,
  ts.isGetAccessorDeclaration,
  ts.isSetAccessorDeclaration,
  ts.isConstructorDeclaration,
];

/**
 * Every `return` that leaves `updateSession` itself.
 *
 * The walk stops at nested function boundaries on purpose: the `cookies`
 * option object passed to `createServerClient` contains a `getAll()` whose
 * `return request.cookies.getAll()` is not an exit of `updateSession`, and
 * counting it would make this gate red for the wrong reason.
 */
function collectExits(source) {
  const file = ts.createSourceFile(
    MIDDLEWARE_PATH,
    source,
    ts.ScriptTarget.ES2022,
    /* setParentNodes */ true,
  );

  let fn = null;
  file.forEachChild((node) => {
    if (ts.isFunctionDeclaration(node) && node.name?.text === "updateSession")
      fn = node;
  });
  if (fn === null || fn.body === undefined) return null;

  const exits = [];
  const visit = (node) => {
    if (FUNCTION_LIKE.some((is) => is(node))) return; // a different function
    if (ts.isReturnStatement(node)) {
      exits.push({
        text: node.expression?.getText(file) ?? "return;",
        line:
          file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1,
        sanctioned: isSanctioned(node.expression),
      });
    }
    ts.forEachChild(node, visit);
  };
  ts.forEachChild(fn.body, visit);
  return exits;
}

function isSanctioned(expression) {
  if (expression === undefined) return false;
  if (ts.isIdentifier(expression))
    return expression.text === RESPONSE_IDENTIFIER;
  return (
    ts.isCallExpression(expression) &&
    ts.isIdentifier(expression.expression) &&
    expression.expression.text === REDIRECT_HELPER
  );
}

/** Throws with a message a reader can act on. The tests below call it. */
function assertEveryExitPreservesSession(source) {
  const exits = collectExits(source);

  assert.ok(
    exits !== null,
    "could not find `updateSession` in lib/supabase/middleware.ts. If it was renamed, rename it here too — a checker that cannot locate its subject passes silently.",
  );
  assert.ok(
    exits.length >= EXITS.length,
    `found ${exits.length} exit(s) from updateSession but this file drives ${EXITS.length}. Either the walk broke, or branches were removed — an every() over too few exits is a gate that agrees with anything.`,
  );

  const dropped = exits.filter((exit) => !exit.sanctioned);
  assert.deepEqual(
    dropped.map((exit) => `line ${exit.line}: return ${exit.text}`),
    [],
    `these exits from updateSession discard the session response. Every exit must return \`${RESPONSE_IDENTIFIER}\` or \`${REDIRECT_HELPER}(...)\`; a bare NextResponse.redirect throws away the rotated auth cookies and the no-store headers (#241).`,
  );
}

test("every exit from updateSession preserves the session response", () => {
  assertEveryExitPreservesSession(readMiddlewareSource());
});

test("NEGATIVE CONTROL: a newly added bare redirect is caught", () => {
  // The exits driven above are the ones that exist today. This proves the
  // enumerator catches one that does not — the fourth `return` somebody adds
  // next month, which no behaviour test in this file could know about.
  const source = readMiddlewareSource();
  const mutant = source.replace(
    /\n  return supabaseResponse;\n\}/,
    '\n  if (request.nextUrl.pathname === "/newly-added") {\n' +
      "    return NextResponse.redirect(request.nextUrl.clone());\n" +
      "  }\n\n  return supabaseResponse;\n}",
  );
  assert.notEqual(
    mutant,
    source,
    "could not inject the mutation — the anchor `return supabaseResponse;` at the end of updateSession moved, so this control was about to pass without testing anything",
  );

  // Count, not just "it threw": while the real file still had bare redirects
  // this control would have thrown for reasons that had nothing to do with the
  // injection, and reported success either way.
  const dropped = (text) => collectExits(text).filter((e) => !e.sanctioned);
  assert.equal(
    dropped(mutant).length,
    dropped(source).length + 1,
    "the enumerator did not attribute exactly one new dropped exit to the injected branch",
  );

  assert.throws(
    () => assertEveryExitPreservesSession(mutant),
    /discard the session response/,
    "the enumerator accepted a bare NextResponse.redirect. It is not a gate.",
  );
});

test("NEGATIVE CONTROL: a source with no exits is caught", () => {
  // `[].every(...)` is `true`. If the walk ever stops finding returns — a
  // rename, a refactor into a nested arrow, a broken parse — the allowlist
  // check above would pass over an empty list and report nothing.
  assert.throws(
    () =>
      assertEveryExitPreservesSession(
        "export async function updateSession(request) {}",
      ),
    /found 0 exit\(s\)/,
    "the enumerator was happy with zero exits, which means it is happy with anything",
  );
});
