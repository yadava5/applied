/**
 * The `?redirect=` guard the whole sign-in flow shares
 * (`lib/auth/redirect.ts`), and the wiring that makes it unavoidable.
 *
 * THE DEFECT THIS EXISTS FOR. All three sign-in surfaces vetted a
 * caller-supplied destination with `value.startsWith("/") ? value :
 * "/dashboard"`, under a comment reading "Refuse open redirects: only allow
 * same-origin paths". `//evil.com` starts with a slash. `?redirect=//evil.com`
 * therefore sent a user who had just typed their password to an attacker's
 * site — via `router.replace` on `/login`, and as a genuine 302 out of
 * `/callback`. A check that cannot fail, shipped behind a comment claiming the
 * fix.
 *
 * TWO HALVES, ON PURPOSE.
 *
 *  1. The predicate itself: every bypass vector, and every legitimate path
 *     that must keep working. Testing only these would leave the vulnerable
 *     shape reachable — a call site that skips the helper is exactly what the
 *     old code was.
 *  2. The wiring: the three files that read or forward a destination must pass
 *     it through `safeRedirectPath`, and none of them may still carry the
 *     `startsWith("/")` guard that failed. Asserted against the source the way
 *     `protected-routes.test.mjs` asserts the auth boundary, because
 *     `/login` is a client component behind `useSearchParams` and `/callback`
 *     is a Route Handler — neither is loadable under `node --test`, and a
 *     stub-based imitation of Next would be a second, worse runtime to trust.
 *     What this half proves is narrow but real: reverting either sink to the
 *     raw value turns it red.
 *
 * Run:  node --test tests/unit/auth-redirect.test.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve as resolvePath } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { DEFAULT_REDIRECT, safeRedirectPath } from "../../lib/auth/redirect.ts";

/** `apps/web` — this file sits at `tests/unit/`. */
const WEB_ROOT = resolvePath(dirname(fileURLToPath(import.meta.url)), "../..");

const read = (relative) =>
  readFileSync(resolvePath(WEB_ROOT, relative), "utf8");

test("the fallback is the dashboard, and it is itself a safe path", () => {
  assert.equal(DEFAULT_REDIRECT, "/dashboard");
  assert.equal(safeRedirectPath(DEFAULT_REDIRECT), DEFAULT_REDIRECT);
});

test("off-origin destinations are refused, however they are spelled", () => {
  const vectors = [
    // The live bypass: protocol-relative, and a slash is all `startsWith`
    // ever asked for.
    "//evil.com",
    "//evil.com/dashboard",
    "///evil.com",
    "//evil.com@applied.example.com",
    // A browser reads `/\` as protocol-relative too.
    "/\\evil.com",
    "/\\/evil.com",
    "/\\\\evil.com",
    "\\/evil.com",
    "\\\\evil.com",
    // Schemes — absolute, and the two that execute rather than navigate.
    "http://evil.com",
    "https://evil.com/dashboard",
    "HTTP://evil.com",
    "javascript:alert(document.cookie)",
    "JavaScript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "mailto:someone@evil.com",
    // Control characters a browser strips before parsing, which reassemble
    // into the protocol-relative form above.
    "/\t/evil.com",
    "/\n/evil.com",
    "/\r/evil.com",
    "/\t\\evil.com",
    // Same-origin by the parser, but its pathname normalises to `//evil.com`
    // — protocol-relative again as soon as a router is handed the string.
    "/..//evil.com",
    "/a/../..//evil.com",
    // Not a path at all: this would resolve to `/dashboard`-alike relatives
    // and must not be silently accepted.
    "dashboard",
    "evil.com",
    "%2f%2fevil.com",
    "",
  ];

  for (const vector of vectors) {
    assert.equal(
      safeRedirectPath(vector),
      DEFAULT_REDIRECT,
      `should refuse ${JSON.stringify(vector)}`,
    );
  }
});

test("nothing returned can be read as an off-origin URL", () => {
  // The return value is what a router is handed, so it is the thing that has
  // to be safe — not the input that produced it.
  for (const vector of [
    "//evil.com",
    "/..//evil.com",
    "/\\evil.com",
    "https://redirect.invalid/dashboard",
    "/dashboard",
    "/inbox?status=applied#top",
  ]) {
    const result = safeRedirectPath(vector);
    assert.ok(result.startsWith("/"), `${result} should be a path`);
    assert.ok(!result.startsWith("//"), `${result} should not be host-relative`);
    assert.ok(!result.includes("\\"), `${result} should carry no backslash`);
    assert.equal(
      new URL(result, "https://applied.example.com").origin,
      "https://applied.example.com",
      `${result} should stay on the app's origin`,
    );
  }
});

test("an absolute URL naming the resolution origin is not echoed back", () => {
  // The trap in validating by origin equality and then returning the input:
  // the dummy origin the helper parses against would pass its own check.
  assert.equal(
    safeRedirectPath("https://redirect.invalid/dashboard"),
    DEFAULT_REDIRECT,
  );
});

test("the destinations the product actually uses still work", () => {
  const kept = [
    "/dashboard",
    "/inbox",
    "/settings",
    "/import",
    "/applications/42",
    "/inbox?status=needs_review",
    "/dashboard?tab=pulse&sort=deadline",
    "/settings#notifications",
    "/inbox?status=applied#first",
    "/", // the marketing page is a legitimate landing spot
  ];

  for (const path of kept) {
    assert.equal(safeRedirectPath(path), path, `should keep ${path}`);
  }
});

test("an absent destination is the dashboard, not a crash", () => {
  assert.equal(safeRedirectPath(null), DEFAULT_REDIRECT);
  assert.equal(safeRedirectPath(undefined), DEFAULT_REDIRECT);
});

test("the guard is idempotent, which is what lets a sink re-apply it", () => {
  for (const vector of ["//evil.com", "/dashboard", "/inbox?a=1#b", "/..//x"]) {
    const once = safeRedirectPath(vector);
    assert.equal(safeRedirectPath(once), once, `not idempotent for ${vector}`);
  }
});

/**
 * The wiring half. Each entry is a place a destination is read or spent, and
 * the shape the source must have there. Revert any one of them to the raw
 * value and this test is the thing that notices.
 */
const WIRED = [
  {
    file: "app/(auth)/login/page.tsx",
    required: [
      [
        /const redirectTo = safeRedirectPath\(\s*searchParams\.get\("redirect"\)/,
        "read ?redirect= through the guard",
      ],
      [
        /router\.replace\(safeRedirectPath\(/,
        "guard the router.replace sink itself",
      ],
      [/armBoot\(safeRedirectPath\(/, "guard the boot flag it arms"],
    ],
  },
  {
    file: "app/(auth)/callback/route.ts",
    required: [
      [
        /const nextPath = safeRedirectPath\(\s*searchParams\.get\("redirect"\)/,
        "resolve the 302 target through the guard",
      ],
      [
        /NextResponse\.redirect\(new URL\(nextPath, origin\)\)/,
        "still redirect to the guarded path and nothing else",
      ],
    ],
  },
  {
    file: "components/auth/GoogleSignInButton.tsx",
    required: [
      [
        /const safeRedirect = safeRedirectPath\(redirectTo\)/,
        "guard what it hands to /callback",
      ],
      [
        /callbackUrl\.searchParams\.set\("redirect", safeRedirect\)/,
        "forward the guarded value, not the prop",
      ],
    ],
  },
];

/**
 * Comments are prose, not behaviour — and these files now quote the broken
 * expression in order to explain it. Strip block comments and whole-line `//`
 * ones so the "must not come back" check below reads code only. Deliberately
 * not a parser: it does not touch a trailing `//` after code, because a
 * naive one would also eat the `https://` inside a string literal.
 */
const codeOnly = (source) =>
  source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .join("\n");

for (const { file, required } of WIRED) {
  test(`${file} spends a destination only through safeRedirectPath`, () => {
    const code = codeOnly(read(file));

    // Positive control: a mis-typed path, or a comment stripper that ate the
    // file, would otherwise make every assertion below vacuous.
    assert.ok(code.length > 200, `${file} read back as ${code.length} chars`);
    assert.ok(
      code.includes("safeRedirectPath"),
      `${file} does not import or call the guard at all`,
    );

    for (const [pattern, why] of required) {
      assert.ok(pattern.test(code), `${file} should ${why}`);
    }

    // The exact expression that failed. It is not a synonym for the guard and
    // must not come back as one.
    assert.ok(
      !/startsWith\("\/"\)/.test(code),
      `${file} still vets a redirect with startsWith("/")`,
    );
  });
}
