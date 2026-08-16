/**
 * The Supabase auth cookies must go out with `Secure` and `SameSite=Lax`
 * (CASA AL1, controls 2.3.1 / 2.3.2).
 *
 * WHY THIS GATE EXISTS, AND WHAT IT IS ALLOWED TO ASSUME
 * ------------------------------------------------------
 * `@supabase/ssr` 0.12.4's `DEFAULT_COOKIE_OPTIONS`
 * (`dist/main/utils/constants.js`) is `{ path: "/", sameSite: "lax",
 * httpOnly: false, maxAge: 400 * 24 * 60 * 60 }`. There is no `secure` key in
 * it at all — so an app that constructs its clients with no `cookieOptions`,
 * as this one did, ships session cookies a browser will replay over plain
 * HTTP. Nothing in the type system says so and nothing at runtime complains:
 * `secure` is simply absent, and an absent attribute is a valid cookie.
 *
 * So the assertions below are made against the INSTALLED library, not against
 * a literal frozen into this file. Every expectation is produced by running
 * the real `applyServerStorage` over the real `cookieOptions` the app's own
 * factories hand to `createServerClient` / `createBrowserClient` — the same
 * merge (`{ ...DEFAULT_COOKIE_OPTIONS, ...cookieOptions, maxAge }`) that
 * decides what reaches the wire. A version bump is then compared against what
 * the new version actually emits.
 *
 * THE CONTROL IS THE POINT. `libraryEmission(null)` — the library with no
 * `cookieOptions` — is asserted to carry NO `secure`. That is the defect this
 * fix closes, and it is what makes the rest of the file capable of failing: if
 * a factory stops passing `cookieOptions`, its emission collapses onto the
 * control and the test goes red. Proven by reverting `lib/supabase/client.ts`
 * before this landed.
 *
 * WHAT IS DELIBERATELY *NOT* ASSERTED TRUE. `httpOnly` is pinned at `false`,
 * on purpose. The browser client's session transport is `document.cookie`, so
 * an HttpOnly auth cookie is invisible to it and breaks sign-in outright; the
 * `false` here is a recorded decision with a compensating control, not a
 * finding to be "hardened" by a later edit.
 *
 * ALL THREE factories are covered — the two server ones and the browser one.
 * They are separate call sites with separate options objects, and a fix
 * applied to one of them passes any gate that only probes another.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve as resolvePath } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

import ts from "typescript";

import { LEGACY_VERIFIER } from "./helpers/callbackSession.mjs";
import { WEB_ROOT, loadUpdateSession } from "./helpers/middlewareSession.mjs";

// `lib/env.ts` validates at import time and all three factories import it.
// Never dialled — the Supabase client is stubbed — but they must parse.
process.env.NEXT_PUBLIC_SUPABASE_URL ??= "https://stub.supabase.co";
process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??= "stub-anon-key";

const require = createRequire(import.meta.url);

/**
 * Deep import, for the reason the sibling helpers give: the package publishes
 * no `exports` map, and using the installed `applyServerStorage` — the
 * function that performs the option merge — is the entire point.
 */
const { applyServerStorage } = require("@supabase/ssr/dist/main/cookies.js");

/**
 * Next's own `Set-Cookie` parser/serializer, the pair the PKCE deletion has to
 * survive. `callback-verifier-cookies.test.mjs` explains at length why reading
 * attributes off the raw response object is a check that cannot fail here:
 * `compact()` drops every falsy field on the way through, which is why the
 * deletion carries a `Date` `expires` as well as `maxAge: 0` — and why a
 * `secure: false` under `next dev` legitimately disappears.
 */
const { parseSetCookie, stringifyCookie } = require(
  "next/dist/compiled/@edge-runtime/cookies",
);

const STORAGE_KEY = "sb-test-auth-token";

/** Enough of a session for the library to encode into cookies. */
const SESSION = {
  access_token: "test-access-token",
  refresh_token: "test-refresh-token",
  expires_at: Math.floor(Date.now() / 1000) + 3600,
  token_type: "bearer",
  user: { id: "00000000-0000-0000-0000-000000000000" },
};

/** A session being written, and a session being cleared. */
const WRITE = {
  name: "a session write",
  setItems: { [STORAGE_KEY]: JSON.stringify(SESSION) },
  removedItems: {},
};
const SIGN_OUT = {
  name: "a sign-out",
  setItems: {},
  removedItems: { [STORAGE_KEY]: true },
};
const SCENARIOS = [WRITE, SIGN_OUT];

/**
 * The cookie writes the INSTALLED library emits for `scenario` when configured
 * with `cookieOptions`. `null` models the app as it was: no options at all.
 *
 * A removal needs the cookie to be present or there is nothing to remove and
 * `setAll` is never called — hence the seeded jar.
 */
async function libraryEmission(cookieOptions, scenario = WRITE) {
  let emitted = null;
  const existing =
    Object.keys(scenario.removedItems).length > 0
      ? [{ name: STORAGE_KEY, value: "stale" }]
      : [];

  await applyServerStorage(
    {
      getAll: () => existing,
      setAll: (cookies) => {
        emitted = cookies;
      },
      setItems: scenario.setItems,
      removedItems: scenario.removedItems,
    },
    { cookieEncoding: "base64url", cookieOptions: cookieOptions ?? null },
  );
  return emitted;
}

/** Run `fn` with `NODE_ENV` set, then put it back exactly as it was. */
async function withNodeEnv(value, fn) {
  const previous = process.env.NODE_ENV;
  process.env.NODE_ENV = value;
  try {
    return await fn();
  } finally {
    if (previous === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = previous;
  }
}

const dataModule = (source) =>
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;

// Both stubs read a hook off `globalThis` at call time rather than closing
// over test state: a `data:` URL module cannot share a binding with us.
const SSR_STUB = dataModule(
  "export function createServerClient(url, key, options) {" +
    "  return globalThis.__cookieAttrStub(url, key, options);" +
    "}" +
    "export function createBrowserClient(url, key, options) {" +
    "  return globalThis.__cookieAttrStub(url, key, options);" +
    "}",
);
const HEADERS_STUB = dataModule(
  "export async function cookies() { return globalThis.__cookieAttrCookieStore; }",
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

function localOrPackage(spec) {
  if (spec.startsWith("@/"))
    return pathToFileURL(resolvePath(WEB_ROOT, `${spec.slice(2)}.ts`)).href;
  // `next/server` has no ESM resolution without the extension under plain
  // `node --test`; Next's own bundler adds it.
  return import.meta.resolve(spec.startsWith("next/") ? `${spec}.js` : spec);
}

/** A shipping module with only its `@supabase/ssr` (and `next/headers`) edge stubbed. */
function loadModule(relPath) {
  return import(
    dataModule(
      transpile(resolvePath(WEB_ROOT, relPath), (spec) => {
        if (spec === "@supabase/ssr") return SSR_STUB;
        if (spec === "next/headers") return HEADERS_STUB;
        return localOrPackage(spec);
      }),
    )
  );
}

/** A Supabase client stub that satisfies whatever each factory does with it. */
const clientStub = {
  auth: {
    async getUser() {
      return { data: { user: null }, error: null };
    },
  },
};

/**
 * The three call sites, each driven through the SHIPPING factory rather than
 * by reading the source: what is asserted is the options object the library
 * was actually handed.
 *
 * `install` exists because the middleware harness owns its own global hook
 * name; each factory installs the same stub wherever its loader looks for it.
 */
const FACTORIES = [
  {
    name: "lib/supabase/server.ts",
    async capture(stub) {
      globalThis.__cookieAttrStub = stub;
      globalThis.__cookieAttrCookieStore = { getAll: () => [], set() {} };
      try {
        const { createClientWithSessionHeaders } = await loadModule(
          "lib/supabase/server.ts",
        );
        await createClientWithSessionHeaders();
      } finally {
        delete globalThis.__cookieAttrStub;
        delete globalThis.__cookieAttrCookieStore;
      }
    },
  },
  {
    name: "lib/supabase/middleware.ts",
    async capture(stub) {
      const { NextRequest } = await import("next/server.js");
      // The middleware harness stubs `createServerClient` under its own name.
      globalThis.__supabaseStub = stub;
      try {
        const updateSession = await loadUpdateSession();
        // `/` is not protected and the stub reports no user, so no branch
        // redirects; the client is constructed either way, which is all this
        // needs.
        await updateSession(new NextRequest("https://applied.test/"));
      } finally {
        delete globalThis.__supabaseStub;
      }
    },
  },
  {
    name: "lib/supabase/client.ts",
    async capture(stub) {
      globalThis.__cookieAttrStub = stub;
      try {
        const { createClient } = await loadModule("lib/supabase/client.ts");
        createClient();
      } finally {
        delete globalThis.__cookieAttrStub;
      }
    },
  },
];

/** The `cookieOptions` a factory hands the library, under a given `NODE_ENV`. */
async function cookieOptionsFrom(factory, nodeEnv) {
  let called = false;
  let captured;
  const stub = (_url, _key, options) => {
    called = true;
    captured = options?.cookieOptions;
    return clientStub;
  };

  await withNodeEnv(nodeEnv, () => factory.capture(stub));
  assert.ok(
    called,
    `${factory.name} never constructed a Supabase client — nothing was captured, so every assertion about it would be vacuous`,
  );
  return captured;
}

test("the installed @supabase/ssr sets no Secure of its own — the whole reason for this file", async () => {
  for (const scenario of SCENARIOS) {
    const emitted = await libraryEmission(null, scenario);

    assert.ok(
      emitted !== null && emitted.length > 0,
      `applyServerStorage wrote no cookies for ${scenario.name} — the fixture is broken and every assertion here would be vacuous`,
    );
    for (const { name, options } of emitted) {
      assert.notEqual(
        options.secure,
        true,
        `@supabase/ssr now sets secure on "${name}" by itself. If a version bump legitimately added it, re-derive this file rather than weakening it — but do NOT drop the app's own cookieOptions on the strength of one scenario.`,
      );
    }
  }
});

for (const factory of FACTORIES) {
  test(`${factory.name} asks for Secure cookies in production`, async () => {
    const cookieOptions = await cookieOptionsFrom(factory, "production");

    assert.equal(
      cookieOptions?.secure,
      true,
      `${factory.name} passed ${JSON.stringify(cookieOptions)} as cookieOptions. Without secure:true the library's defaults apply and the session cookie goes out with no Secure attribute (CASA 2.3.1/2.3.2).`,
    );
  });

  for (const scenario of SCENARIOS) {
    test(`${factory.name}'s options make the library emit Secure, Lax, path / on ${scenario.name}`, async () => {
      const cookieOptions = await cookieOptionsFrom(factory, "production");
      const emitted = await libraryEmission(cookieOptions, scenario);

      assert.ok(
        emitted !== null && emitted.length > 0,
        `the library wrote no cookies for ${scenario.name} — the assertions below would be vacuous`,
      );

      for (const { name, options } of emitted) {
        assert.equal(
          options.secure,
          true,
          `"${name}" would be sent without Secure, from ${factory.name}`,
        );
        assert.equal(
          options.sameSite,
          "lax",
          `"${name}" would be sent without SameSite=Lax, from ${factory.name}`,
        );
        assert.equal(
          options.path,
          "/",
          `"${name}" would be scoped to ${options.path}, not the whole site — the app reads it on every route`,
        );
        assert.equal(
          options.httpOnly,
          false,
          `"${name}" became HttpOnly. That is not a hardening: the browser client's session transport is document.cookie, so this breaks sign-in. See lib/supabase/server.ts.`,
        );
      }
    });
  }

  test(`${factory.name} does not ask for Secure under next dev`, async () => {
    // The gate is `NODE_ENV`, and `lib/auth/recoverySession.ts` states why:
    // every deployed environment gets Secure and only `next dev` does not. A
    // local `next start` is NODE_ENV=production and so sets it over plain
    // HTTP, which is fine — browsers treat `http://localhost` as a secure
    // origin and store Secure cookies from it.
    const cookieOptions = await cookieOptionsFrom(factory, "development");

    assert.notEqual(
      cookieOptions?.secure,
      true,
      `${factory.name} demands Secure under next dev`,
    );
  });
}

/**
 * The one cookie write the app makes itself: the PKCE verifier deletion in
 * `lib/supabase/pkceVerifierCookies.ts`.
 *
 * Asserted through Next's `Set-Cookie` round-trip rather than off the response
 * object, for the reason that file's comment gives — and the round-trip is
 * also what proves the load-bearing `expires` survived the edit that added
 * these two attributes.
 */
function attributesOf(setCookie) {
  const raw = stringifyCookie(parseSetCookie(setCookie));
  const [pair, ...attrs] = raw.split(";").map((s) => s.trim());
  const parts = attrs.map((a) => a.split("="));
  return {
    name: pair.slice(0, pair.indexOf("=")),
    has: (key) => parts.some(([k]) => k.toLowerCase() === key),
    value: (key) => parts.find(([k]) => k.toLowerCase() === key)?.[1],
  };
}

async function expireVerifier(nodeEnv) {
  const { NextRequest, NextResponse } = await import("next/server.js");
  const { expireSpentPkceVerifierCookies } = await import(
    pathToFileURL(resolvePath(WEB_ROOT, "lib/supabase/pkceVerifierCookies.ts"))
      .href
  );

  const request = new NextRequest("https://applied.test/callback?code=spent", {
    headers: { cookie: `${LEGACY_VERIFIER}=base64-spent-verifier` },
  });
  const response = await withNodeEnv(nodeEnv, () =>
    expireSpentPkceVerifierCookies(request, NextResponse.next()),
  );

  const emitted = response.headers
    .getSetCookie()
    .map(attributesOf)
    .find(({ name }) => name === LEGACY_VERIFIER);
  assert.ok(
    emitted,
    `the sweep expired nothing for ${LEGACY_VERIFIER} — the assertions below would be vacuous`,
  );
  return emitted;
}

test("the PKCE verifier deletion carries the attributes the cookie was set with", async () => {
  const cookie = await expireVerifier("production");

  assert.ok(cookie.has("secure"), "the deletion went out without Secure");
  assert.equal(
    cookie.value("samesite")?.toLowerCase(),
    "lax",
    "the deletion went out without SameSite=Lax",
  );
  assert.equal(cookie.value("path"), "/", "a deletion at the wrong path shadows the cookie instead of dropping it");

  // The reason the deletion carries a Date at all: `maxAge: 0` is falsy and
  // `compact()` strips it on the way through this very round-trip. Adding
  // attributes must not have cost this.
  const expires = cookie.value("expires");
  assert.ok(
    expires !== undefined && Date.parse(expires) <= 0,
    `the deletion lost its past Expires (got ${expires}) — with Max-Age stripped by compact() it is no longer a deletion at all`,
  );
});

test("the PKCE verifier deletion is not Secure under next dev", async () => {
  const cookie = await expireVerifier("development");

  // `secure: false` is falsy, so `compact()` drops the attribute entirely —
  // absent and false are the same thing on the wire, and both are right here:
  // the cookie being deleted was written without Secure too.
  assert.ok(
    !cookie.has("secure"),
    "the deletion demands Secure under next dev, where the cookie it targets has no Secure",
  );
});
