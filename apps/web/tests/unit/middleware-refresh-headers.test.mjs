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
 * HOW THIS TEST WORKS. It does not restate the header values. It drives the
 * REAL `applyServerStorage` out of the installed package twice:
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
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve as resolvePath } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import ts from "typescript";

const require = createRequire(import.meta.url);

// `lib/env.ts` validates at import time and the middleware imports it. These
// are never dialled — the Supabase client is stubbed — but they must parse.
process.env.NEXT_PUBLIC_SUPABASE_URL ??= "https://stub.supabase.co";
process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??= "stub-anon-key";

/** `apps/web` — what the `@/*` path alias in tsconfig.json points at. */
const WEB_ROOT = resolvePath(dirname(fileURLToPath(import.meta.url)), "../..");

/**
 * Deep import: the package publishes no `exports` map (only `main`/`module`),
 * so the subpath is reachable. `applyServerStorage` is the function that calls
 * `setAll` with the headers, and using the installed one is the entire point —
 * a hand-rolled imitation would only ever assert what this file believes.
 */
const { applyServerStorage } = require("@supabase/ssr/dist/main/cookies.js");

/** Enough of a session for the library to encode into cookies. */
const SESSION = {
  access_token: "test-access-token",
  refresh_token: "test-refresh-token",
  expires_at: Math.floor(Date.now() / 1000) + 3600,
  token_type: "bearer",
  user: { id: "00000000-0000-0000-0000-000000000000" },
};
const STORAGE_KEY = "sb-test-auth-token";
const STORAGE = { cookieEncoding: "base64url", cookieOptions: null };

/** The cookie writes + headers the INSTALLED library emits for that session. */
async function libraryEmission() {
  let emitted = null;
  await applyServerStorage(
    {
      getAll: () => [],
      setAll: (cookies, headers) => {
        emitted = { cookies, headers };
      },
      setItems: { [STORAGE_KEY]: JSON.stringify(SESSION) },
      removedItems: {},
    },
    STORAGE,
  );
  return emitted;
}

/**
 * Load the real `lib/supabase/middleware.ts` with `@supabase/ssr` replaced by a
 * stub, so `createServerClient` is ours but every other line — the cookie
 * plumbing, the response rebuild, the redirects — is the shipping code.
 *
 * Only the ENTRY module's specifiers are rewritten; `@/lib/env` and
 * `@/lib/supabase/protectedRoutes` are then loaded by Node's native TypeScript
 * stripping, exactly as the other unit tests here load their `.ts` modules.
 */
async function loadUpdateSession() {
  const entry = resolvePath(WEB_ROOT, "lib/supabase/middleware.ts");

  // The stub reads a hook off `globalThis` at call time rather than closing
  // over test state: a `data:` URL module cannot share a binding with us.
  const stub = `data:text/javascript;base64,${Buffer.from(
    "export function createServerClient(url, key, options) {" +
      "  return globalThis.__supabaseStub(url, key, options);" +
      "}",
  ).toString("base64")}`;

  const { outputText } = ts.transpileModule(readFileSync(entry, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: entry,
  });

  const rewritten = outputText.replace(
    /(\bfrom\s*|\bimport\s*\(\s*)["']([^"']+)["']/g,
    (_match, head, spec) => `${head}"${resolveSpecifier(spec)}"`,
  );

  return import(
    `data:text/javascript;base64,${Buffer.from(rewritten).toString("base64")}`
  ).then((m) => m.updateSession);

  function resolveSpecifier(spec) {
    if (spec === "@supabase/ssr") return stub;
    if (spec.startsWith("@/"))
      return pathToFileURL(resolvePath(WEB_ROOT, `${spec.slice(2)}.ts`)).href;
    // `next/server` has no ESM resolution without the extension under plain
    // `node --test`; Next's own bundler adds it.
    return import.meta.resolve(spec.startsWith("next/") ? `${spec}.js` : spec);
  }
}

/**
 * Run `updateSession` against a request whose session refreshes mid-flight.
 *
 * `auth.getUser()` is where the real client triggers the silent refresh, so the
 * stub drives `applyServerStorage` from inside it — the same ordering the real
 * client has, and the ordering that matters, since `setAll` fires while
 * `updateSession` is still building its response.
 */
async function refreshDuring(pathname) {
  const { NextRequest } = await import("next/server.js");
  const updateSession = await loadUpdateSession();

  let cookieMethods = null;
  globalThis.__supabaseStub = (_url, _key, options) => {
    cookieMethods = options.cookies;
    return {
      auth: {
        async getUser() {
          await applyServerStorage(
            {
              getAll: () => cookieMethods.getAll(),
              setAll: (cookies, headers) =>
                cookieMethods.setAll(cookies, headers),
              setItems: { [STORAGE_KEY]: JSON.stringify(SESSION) },
              removedItems: {},
            },
            STORAGE,
          );
          return { data: { user: SESSION.user }, error: null };
        },
      },
    };
  };

  try {
    return await updateSession(
      new NextRequest(`https://applied.test${pathname}`, {
        headers: { cookie: "sb-test-auth-token=stale" },
      }),
    );
  } finally {
    delete globalThis.__supabaseStub;
  }
}

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
  const response = await refreshDuring("/dashboard");

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
  const response = await refreshDuring("/dashboard");

  for (const { name } of expected) {
    assert.ok(
      response.cookies.get(name) !== undefined,
      `refreshed cookie "${name}" is missing from the response`,
    );
  }
});
