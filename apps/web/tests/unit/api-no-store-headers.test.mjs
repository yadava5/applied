/**
 * Every route handler under `app/api/` returns user-scoped JSON, and any of
 * them can carry a session cookie `@supabase/ssr` wrote during the request. So
 * none of them may be left with no `Cache-Control` — because on Vercel, a
 * handler that declares nothing does not get "no header", it gets
 * `public, max-age=0, must-revalidate` (#315, measured against production).
 *
 * WHY THIS GATE EXISTS RATHER THAN A REVIEW HABIT. The defect is an OMISSION.
 * There is nothing on the page to notice: `NextResponse.json(body)` is the
 * obvious spelling and it is the defective one, `tsc --noEmit` has no opinion,
 * and the missing header only becomes `public` at the edge, where no test in
 * this repo looks. #234, #240, #242 and #312 are the same omission in four
 * other places. A fifth handler must not be able to ship without it.
 *
 * WHAT THIS FILE CAN AND CANNOT PROVE. It proves the DECLARATION exists, is
 * spelled the way the installed library spells it, and covers every route
 * handler in the tree. It cannot prove the header lands on the wire — only a
 * request can, and that was measured separately on a production build
 * (`next build && next start`), where `GET /api/account/delete` and
 * `GET /api/applications` both returned the three headers below and `/login`
 * was left alone. See the note in next.config.ts.
 *
 * NOTHING HERE RESTATES THE HEADER VALUES. They are read at runtime out of the
 * installed `@supabase/ssr`, the same trick `helpers/callbackSession.mjs` uses:
 * a literal frozen into a test file agrees with a stale config just as happily
 * as with a correct one, and a version bump that changed the directives would
 * be invisible.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, relative, resolve as resolvePath } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import ts from "typescript";

const require = createRequire(import.meta.url);

/** `apps/web`. */
const WEB_ROOT = resolvePath(dirname(fileURLToPath(import.meta.url)), "../..");

/**
 * Deep import: the package publishes no `exports` map, so the subpath is
 * reachable. `applyServerStorage` is the function that calls `setAll` with the
 * headers, and using the installed one is the entire point.
 */
const { applyServerStorage } = require("@supabase/ssr/dist/main/cookies.js");

/**
 * The headers the INSTALLED `@supabase/ssr` hands to `setAll` when it writes a
 * session. Probed, not restated.
 */
async function libraryHeaders() {
  let emitted = null;
  await applyServerStorage(
    {
      getAll: () => [],
      setAll: (cookies, headers) => {
        emitted = { cookies, headers };
      },
      setItems: {
        "sb-test-auth-token": JSON.stringify({
          access_token: "t",
          refresh_token: "r",
          expires_at: Math.floor(Date.now() / 1000) + 3600,
          token_type: "bearer",
          user: { id: "00000000-0000-0000-0000-000000000000" },
        }),
      },
      removedItems: {},
    },
    { cookieEncoding: "base64url", cookieOptions: null },
  );
  return emitted;
}

/**
 * `next.config.ts`, executed. Transpiled rather than imported because the file
 * is TypeScript and its only import is a type.
 */
async function loadConfig() {
  const absolute = resolvePath(WEB_ROOT, "next.config.ts");
  const { outputText } = ts.transpileModule(readFileSync(absolute, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: absolute,
  });
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`;
  return import(url);
}

/** Every `route.ts` under `app/`, as the URL path Next will serve it at. */
function routeHandlerPaths() {
  const appRoot = resolvePath(WEB_ROOT, "app");
  const found = [];

  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      const full = resolvePath(dir, entry);
      if (statSync(full).isDirectory()) {
        if (entry !== "node_modules") walk(full);
      } else if (entry === "route.ts" || entry === "route.tsx") {
        // Route GROUPS — `(auth)`, `(app)`, `(protected)` — are not reflected
        // in the URL. Dropping them is what makes `/api/...` comparable to the
        // `source` pattern in next.config.ts; leaving them in would make
        // `app/(app)/api/x/route.ts` look uncovered when it is not.
        const segments = relative(appRoot, dirname(full))
          .split("/")
          .filter((s) => s && !(s.startsWith("(") && s.endsWith(")")));
        found.push({
          file: relative(WEB_ROOT, full),
          url: `/${segments.join("/")}`,
        });
      }
    }
  };

  walk(appRoot);
  return found.sort((a, b) => a.url.localeCompare(b.url));
}

/**
 * Route handlers that are deliberately NOT covered by the `/api` entry, each
 * with the reason. An allowlist rather than a silent exception: a handler
 * appearing outside `/api` should stop the build and be a decision.
 *
 * Both are PKCE callbacks. They carry the INITIAL session rather than a
 * refreshed one, and they are redirects rather than JSON. They are excluded
 * here for a structural reason: they sit beside PAGE routes, so covering them
 * would mean widening the `source` pattern onto paths that serve HTML, and
 * `/login` legitimately carries `s-maxage=31536000` as a prerender.
 *
 * STATED PLAINLY BECAUSE IT MATTERS: at the time of writing, PR #312 — which
 * applies the very same library headers to these two responses at the handler,
 * with `callback-session-headers.test.mjs` — is OPEN, NOT MERGED. So this
 * allowlist records where the fix belongs, not a fix that has landed. If #312
 * is closed unmerged, these two entries become a hole and the right move is to
 * cover them here rather than to leave the reason string standing.
 */
const NOT_UNDER_API = new Map([
  ["/callback", "PKCE callback — handler-level headers, PR #312 (open)"],
  ["/reset-password/callback", "password-recovery PKCE callback — PR #312 (open)"],
]);

test("the no-store entry spells the headers the installed @supabase/ssr uses", async () => {
  const emitted = await libraryHeaders();

  // Vacuity guard. If the fixture stopped producing a cookie write there would
  // be no headers to compare and the assertions below would pass on nothing.
  assert.ok(
    emitted !== null,
    "applyServerStorage never called setAll — the fixture no longer produces a cookie write",
  );
  assert.ok(
    Object.keys(emitted.headers ?? {}).length > 0,
    "the installed @supabase/ssr passed no headers to setAll. If a version bump legitimately removed them, this test is obsolete — delete it rather than weakening it.",
  );

  const { default: config, API_NO_STORE_SOURCE } = await loadConfig();
  const entries = await config.headers();
  const entry = entries.find((e) => e.source === API_NO_STORE_SOURCE);

  assert.ok(
    entry,
    `no headers() entry with source "${API_NO_STORE_SOURCE}". Every route handler under /api would fall back to Vercel's default, which is "public" (#315).`,
  );

  for (const [name, value] of Object.entries(emitted.headers)) {
    const declared = entry.headers.find(
      (h) => h.key.toLowerCase() === name.toLowerCase(),
    );
    assert.ok(declared, `next.config.ts declares no "${name}" for ${API_NO_STORE_SOURCE}`);
    assert.equal(
      declared.value,
      value,
      `"${name}" in next.config.ts is "${declared.value}" but @supabase/ssr hands setAll "${value}". These must agree — see next.config.ts.`,
    );
  }
});

test("every route handler is covered by the no-store entry, or allowlisted with a reason", async () => {
  const { API_NO_STORE_SOURCE } = await loadConfig();
  const routes = routeHandlerPaths();

  // Vacuity guard: a walk that found nothing would agree with everything.
  assert.ok(
    routes.length > 0,
    "found no route handlers under app/ — the walk is broken, so this test asserts nothing",
  );

  // Prefix, deliberately, rather than re-implementing Next's `source` → regexp
  // compilation. A gate that reimplements the matcher tests the reimplementation.
  const prefix = API_NO_STORE_SOURCE.replace(/:path\*$/, "");
  assert.equal(prefix, "/api/", "the source pattern changed shape; update this test");

  const uncovered = routes.filter(
    (r) => !r.url.startsWith(prefix) && !NOT_UNDER_API.has(r.url),
  );

  assert.deepEqual(
    uncovered,
    [],
    `route handler(s) outside "${API_NO_STORE_SOURCE}" and not allowlisted: ` +
      `${uncovered.map((r) => `${r.url} (${r.file})`).join(", ")}. ` +
      "A route handler declaring no Cache-Control gets Vercel's default, and that default is " +
      "\"public\" (#315). Either move it under /api, or add it to NOT_UNDER_API with the " +
      "reason it is handled elsewhere.",
  );
});

test("the allowlist names only handlers that exist", async () => {
  // Otherwise a route could be renamed, drop out of coverage, and leave its
  // stale allowlist entry behind still looking like a decision.
  const urls = new Set(routeHandlerPaths().map((r) => r.url));
  const stale = [...NOT_UNDER_API.keys()].filter((url) => !urls.has(url));

  assert.deepEqual(
    stale,
    [],
    `NOT_UNDER_API names route(s) that no longer exist: ${stale.join(", ")}. ` +
      "Remove them, so the allowlist keeps meaning what it says.",
  );
});
