/**
 * Harness for driving the REAL `lib/supabase/middleware.ts#updateSession`
 * under `node --test`, with a session that refreshes (or is cleared) part-way
 * through the request.
 *
 * Extracted from `tests/unit/middleware-refresh-headers.test.mjs` (#240) so
 * that `middleware-redirect-session.test.mjs` (#241) drives the same code path
 * instead of growing a second, subtly different imitation of it. Nothing here
 * asserts; the two test files own their own expectations.
 *
 * The point of the harness is that only `@supabase/ssr`'s `createServerClient`
 * is replaced. The cookie plumbing, the response rebuild and the redirect
 * branches under test are the shipping module, and the cookie writes are
 * produced by the INSTALLED library's own `applyServerStorage` rather than by
 * a hand-rolled fixture — so a version bump is compared against what the new
 * version actually emits, not against a literal frozen into a test file.
 */
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
export const WEB_ROOT = resolvePath(
  dirname(fileURLToPath(import.meta.url)),
  "../../..",
);

/** The module under test, as text — the exit enumerator in #241 parses it. */
export const MIDDLEWARE_PATH = resolvePath(
  WEB_ROOT,
  "lib/supabase/middleware.ts",
);

export const readMiddlewareSource = () => readFileSync(MIDDLEWARE_PATH, "utf8");

/**
 * Deep import: the package publishes no `exports` map (only `main`/`module`),
 * so the subpath is reachable. `applyServerStorage` is the function that calls
 * `setAll` with the headers, and using the installed one is the entire point —
 * a hand-rolled imitation would only ever assert what this file believes.
 */
const { applyServerStorage } = require("@supabase/ssr/dist/main/cookies.js");

/** Enough of a session for the library to encode into cookies. */
export const SESSION = {
  access_token: "test-access-token",
  refresh_token: "test-refresh-token",
  expires_at: Math.floor(Date.now() / 1000) + 3600,
  token_type: "bearer",
  user: { id: "00000000-0000-0000-0000-000000000000" },
};
export const STORAGE_KEY = "sb-test-auth-token";
const STORAGE = { cookieEncoding: "base64url", cookieOptions: null };

/**
 * What the library does when a session is written back — the mid-flight token
 * refresh that `auth.getUser()` triggers.
 */
export const REFRESH = {
  setItems: { [STORAGE_KEY]: JSON.stringify(SESSION) },
  removedItems: {},
};

/**
 * What the library does when a session is cleared — a failed refresh or a
 * sign-out. It emits `maxAge: 0` deletions, and (verified against 0.12.4) the
 * same no-store headers as a write. Dropping these leaves stale chunked auth
 * cookies in the browser, which is the first redirect branch's failure mode.
 */
export const SIGN_OUT = {
  setItems: {},
  removedItems: { [STORAGE_KEY]: true },
};

/**
 * The cookie writes + headers the INSTALLED library emits for `scenario`.
 *
 * `existing` is the cookie jar the library reads; a removal needs the cookie
 * to be there or there is nothing to remove and `setAll` is never called.
 */
export async function libraryEmission(scenario = REFRESH) {
  let emitted = null;
  const existing =
    Object.keys(scenario.removedItems ?? {}).length > 0
      ? [{ name: STORAGE_KEY, value: "stale" }]
      : [];

  await applyServerStorage(
    {
      getAll: () => existing,
      setAll: (cookies, headers) => {
        emitted = { cookies, headers };
      },
      setItems: scenario.setItems ?? {},
      removedItems: scenario.removedItems ?? {},
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
export async function loadUpdateSession() {
  // The stub reads a hook off `globalThis` at call time rather than closing
  // over test state: a `data:` URL module cannot share a binding with us.
  const stub = `data:text/javascript;base64,${Buffer.from(
    "export function createServerClient(url, key, options) {" +
      "  return globalThis.__supabaseStub(url, key, options);" +
      "}",
  ).toString("base64")}`;

  const { outputText } = ts.transpileModule(readMiddlewareSource(), {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: MIDDLEWARE_PATH,
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
 * Run `updateSession` against a request whose session changes mid-flight, and
 * return the response it produced.
 *
 * `auth.getUser()` is where the real client triggers the silent refresh, so the
 * stub drives `applyServerStorage` from inside it — the same ordering the real
 * client has, and the ordering that matters, since `setAll` fires while
 * `updateSession` is still building its response.
 *
 * `user` selects which branch of `updateSession` is taken: `null` models a
 * session the server could not revive (redirect to `/login` on a protected
 * path), the default models a live one.
 */
export async function runUpdateSession(
  pathname,
  { scenario = REFRESH, user = SESSION.user } = {},
) {
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
              setItems: scenario.setItems ?? {},
              removedItems: scenario.removedItems ?? {},
            },
            STORAGE,
          );
          return { data: { user }, error: null };
        },
      },
    };
  };

  try {
    return await updateSession(
      new NextRequest(`https://applied.test${pathname}`, {
        headers: { cookie: `${STORAGE_KEY}=stale` },
      }),
    );
  } finally {
    delete globalThis.__supabaseStub;
  }
}
