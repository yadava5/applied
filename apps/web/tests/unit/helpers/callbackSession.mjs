/**
 * Harness for driving the REAL PKCE callback route handlers under
 * `node --test`, through the REAL `lib/supabase/server.ts`, with the cookie
 * writes produced by the INSTALLED `@supabase/ssr`.
 *
 * Sibling of `helpers/middlewareSession.mjs`, which does the same job for
 * `lib/supabase/middleware.ts`. The two exist because the app has two `setAll`
 * implementations and they must agree; this one covers the second.
 *
 * WHAT IS REAL AND WHAT IS STUBBED. Stubbed: `@supabase/ssr`'s
 * `createServerClient` (so no network and no live project) and `next/headers`'
 * `cookies()` (so there is no Next request scope to stand up). Real: the
 * factory in `lib/supabase/server.ts`, the route handler under test, and
 * `applyServerStorage` — the library function that actually calls `setAll`
 * with the headers. Nothing here restates what those headers are; the tests
 * ask the library at runtime.
 *
 * WHY THE COOKIE JAR MUST NOT THROW. `lib/supabase/server.ts` wraps its cookie
 * writes in a try/catch, because a Server Component cannot set cookies. A jar
 * that threw would exercise the swallowed path and the assertions would pass
 * for the wrong reason. A Route Handler CAN set cookies — observed on a
 * production build for #242, `cookieStore.set` succeeded and the catch did not
 * fire — so the jar here succeeds, matching what the route actually meets.
 */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve as resolvePath } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import ts from "typescript";

const require = createRequire(import.meta.url);

// `lib/env.ts` validates at import time and `lib/supabase/server.ts` imports
// it. Never dialled — the Supabase client is stubbed — but they must parse.
process.env.NEXT_PUBLIC_SUPABASE_URL ??= "https://stub.supabase.co";
process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??= "stub-anon-key";

/** `apps/web` — what the `@/*` path alias in tsconfig.json points at. */
const WEB_ROOT = resolvePath(dirname(fileURLToPath(import.meta.url)), "../../..");

/**
 * Deep import: the package publishes no `exports` map, so the subpath is
 * reachable. `applyServerStorage` is the function that calls `setAll` with the
 * headers, and using the installed one is the entire point.
 */
const { applyServerStorage } = require("@supabase/ssr/dist/main/cookies.js");

const STORAGE = { cookieEncoding: "base64url", cookieOptions: null };
const STORAGE_KEY = "sb-test-auth-token";

/** Enough of a session for the library to encode into cookies. */
const SESSION = {
  access_token: "test-access-token",
  refresh_token: "test-refresh-token",
  expires_at: Math.floor(Date.now() / 1000) + 3600,
  token_type: "bearer",
  user: { id: "00000000-0000-0000-0000-000000000000" },
};

/** The code that makes the stubbed exchange fail, for the error branches. */
export const FAILING_CODE = "code-that-does-not-exchange";

/** The three cookie names a PKCE flow start writes, for this storage key. */
export const LEGACY_VERIFIER = `${STORAGE_KEY}-code-verifier`;
export const FLOW_INDEX = `${STORAGE_KEY}-flows-code-verifier`;
export const slotFor = (flowId) => `${STORAGE_KEY}-flow-${flowId}-code-verifier`;

/**
 * The verifier cookies a browser holds after starting `flows` in order, the
 * last one being the flow the callback is about to exchange (#321).
 *
 * Built by running the INSTALLED library's own `applyServerStorage` over the
 * storage keys auth-js's `storePKCEVerifier` writes, rather than by hand: the
 * property the fix turns on is that the flow slot and the fixed legacy key
 * carry BYTE-IDENTICAL `base64-…` values, and that has to come out of the real
 * encoder or the test only asserts what this file believes.
 *
 * `storePKCEVerifier` writes the slot, then the index of pending ids, then
 * dual-writes the newest verifier to the fixed key — which is the key, and the
 * only key, a server-side exchange can read.
 */
export async function mintVerifierCookies(flows) {
  const setItems = { [FLOW_INDEX]: JSON.stringify(flows.map((f) => f.flowId)) };
  for (const { flowId, verifier } of flows) {
    setItems[slotFor(flowId)] = JSON.stringify(verifier);
  }
  setItems[LEGACY_VERIFIER] = JSON.stringify(flows.at(-1).verifier);

  const minted = [];
  await applyServerStorage(
    {
      getAll: () => [],
      setAll: (cookies) => minted.push(...cookies),
      setItems,
      removedItems: {},
    },
    STORAGE,
  );
  return minted.map(({ name, value }) => ({ name, value }));
}

/** The two handlers under test, and the query each needs to reach the exchange. */
export const CALLBACK_ROUTES = [
  {
    name: "/callback",
    file: "app/(auth)/callback/route.ts",
    url: (code) => `https://applied.test/callback?code=${code}`,
  },
  {
    name: "/reset-password/callback",
    file: "app/(auth)/reset-password/callback/route.ts",
    url: (code) => `https://applied.test/reset-password/callback?code=${code}`,
  },
];

/**
 * The cookie writes + headers the INSTALLED library emits when a session is
 * written. Probed through a bare `setAll` so the tests compare the app against
 * whatever the installed version does, not against a literal frozen into a
 * test file — a version bump is then compared with the new value.
 */
export async function libraryEmission() {
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
 * A `next/headers` cookie store that behaves like a Route Handler's: writes
 * succeed and are recorded.
 */
function cookieJar(initial = []) {
  const jar = new Map(initial.map(({ name, value }) => [name, value]));
  const writes = [];
  return {
    getAll: () => [...jar].map(([name, value]) => ({ name, value })),
    set(name, value, options) {
      writes.push({ name, value, options });
      if (options?.maxAge === 0) jar.delete(name);
      else jar.set(name, value);
    },
    writes,
  };
}

const dataModule = (source) =>
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;

// Both stubs read a hook off `globalThis` at call time rather than closing over
// test state: a `data:` URL module cannot share a binding with us.
const SSR_STUB = dataModule(
  "export function createServerClient(url, key, options) {" +
    "  return globalThis.__callbackSupabaseStub(url, key, options);" +
    "}",
);
const HEADERS_STUB = dataModule(
  "export async function cookies() { return globalThis.__callbackCookieStore; }",
);

function transpile(absPath, rewrite) {
  const { outputText } = ts.transpileModule(readFileSync(absPath, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: absPath,
  });
  return outputText.replace(
    /(\bfrom\s*|\bimport\s*\(\s*)["']([^"']+)["']/g,
    (_match, head, spec) => `${head}"${rewrite(spec)}"`,
  );
}

/** `lib/supabase/server.ts`, as a module URL, with only its two edges stubbed. */
const SERVER_MODULE = dataModule(
  transpile(resolvePath(WEB_ROOT, "lib/supabase/server.ts"), (spec) => {
    if (spec === "@supabase/ssr") return SSR_STUB;
    if (spec === "next/headers") return HEADERS_STUB;
    return localOrPackage(spec);
  }),
);

function localOrPackage(spec) {
  if (spec.startsWith("@/"))
    return pathToFileURL(resolvePath(WEB_ROOT, `${spec.slice(2)}.ts`)).href;
  // `next/server` has no ESM resolution without the extension under plain
  // `node --test`; Next's own bundler adds it.
  return import.meta.resolve(spec.startsWith("next/") ? `${spec}.js` : spec);
}

/** The real route handler, wired to the real (stub-edged) server factory. */
async function loadRoute(file) {
  const source = transpile(resolvePath(WEB_ROOT, file), (spec) =>
    spec === "@/lib/supabase/server" ? SERVER_MODULE : localOrPackage(spec),
  );
  return import(dataModule(source));
}

/**
 * Run one callback route's `GET` against a PKCE exchange, and hand back the
 * response it returned plus the cookie writes it made.
 *
 * `exchange` drives the library from inside `exchangeCodeForSession`, which is
 * the ordering that matters: `setAll` fires while the handler is still deciding
 * what to return, exactly as it does in production.
 */
export async function runCallback(
  route,
  { code = "valid-code", cookies = [] } = {},
) {
  const { NextRequest } = await import("next/server.js");
  const { GET } = await loadRoute(route.file);

  const store = cookieJar(cookies);
  globalThis.__callbackCookieStore = store;
  globalThis.__callbackSupabaseStub = (_url, _key, options) => ({
    auth: {
      async exchangeCodeForSession(authCode) {
        if (authCode === FAILING_CODE) {
          // Nothing is flushed. Measured against the installed packages: a
          // failed exchange buffers the legacy verifier's removal but emits
          // only INITIAL_SESSION, which is not an event `createServerClient`
          // applies storage on — so NO Set-Cookie of any kind leaves here.
          // The route is the only thing that can clean up after this (#321).
          return {
            data: { session: null, user: null },
            error: { message: "invalid flow state", name: "AuthApiError" },
          };
        }
        await applyServerStorage(
          {
            getAll: () => options.cookies.getAll(),
            setAll: (cookies, headers) =>
              options.cookies.setAll(cookies, headers),
            setItems: { [STORAGE_KEY]: JSON.stringify(SESSION) },
            // What `removePKCEVerifier` asks for with no flow id — the fixed
            // key alone — flushed on SIGNED_IN. The flow slot and the index
            // are NOT in here, which is the whole of #321: the server has no
            // flow id, so it cannot name them.
            removedItems: store
              .getAll()
              .some(({ name }) => name === LEGACY_VERIFIER)
              ? { [LEGACY_VERIFIER]: true }
              : {},
          },
          STORAGE,
        );
        return {
          data: { session: SESSION, user: SESSION.user },
          error: null,
        };
      },
    },
  });

  const request = new NextRequest(route.url(code), {
    headers: cookies.length
      ? { cookie: cookies.map(({ name, value }) => `${name}=${value}`).join("; ") }
      : {},
  });

  try {
    const response = await GET(request);
    return { response, writes: store.writes };
  } finally {
    delete globalThis.__callbackCookieStore;
    delete globalThis.__callbackSupabaseStub;
  }
}
