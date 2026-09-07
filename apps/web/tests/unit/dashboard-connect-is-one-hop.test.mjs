/**
 * "Connect Gmail" on the dashboard connects Gmail, in one hop (#494).
 *
 * THE DEFECT THIS CLOSES. The tile said "Connect Gmail" and linked to
 * `/settings`, where the reader then had to find `ConnectGmailButton` and press
 * it. #494's shape (b) shipped for a first Google signup only — every other
 * route into the product still paid the extra hop.
 *
 * WHY THIS EXECUTES RATHER THAN READS SOURCE. Both halves of the fix are
 * runtime facts: what the tile actually renders as `href`, and which page the
 * route handler redirects a dashboard-initiated FAILURE to. A regex over the
 * source reads intent — this repo has already paid for that twice (see
 * `helpers/mountApp.mjs`). So the component is mounted and its DOM is read, and
 * the real `GET` handler is driven with the href the component produced, with
 * only `lib/gmail/server` stubbed. The href is never written down twice: the
 * route is fed whatever the tile renders, so the two cannot drift apart and
 * still pass.
 *
 * WHAT IS STUBBED AND WHY. `lib/gmail/server.ts` alone. It is a real backend
 * client — it imports `lib/env.server`, resolves a Supabase session out of
 * `next/headers`, and issues a `fetch` — and none of that is what this file is
 * about. Everything else is the real thing: the real component, the real route
 * module, the real `next/server`. Same technique, and the same reasoning, as
 * `helpers/callbackSession.mjs`.
 *
 * Run:  node --test tests/unit/dashboard-connect-is-one-hop.test.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve as resolvePath } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import ts from "typescript";

import { React, importApp, mount } from "./helpers/mountApp.mjs";

/** `apps/web` — this file sits at `tests/unit/`. */
const WEB_ROOT = resolvePath(dirname(fileURLToPath(import.meta.url)), "..", "..");

/** The host the handler believes it was reached on. Any origin will do; what
 *  matters is that every redirect it builds is same-origin with it. */
const ORIGIN = "https://applied.test";

const dataModule = (source) =>
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;

/**
 * `lib/gmail/server.ts`, stubbed.
 *
 * Reads its answer off `globalThis` at call time, and records its arguments
 * there, because a `data:` URL module cannot share a binding with this file.
 * Recording `chained` is half the point: the SUCCESS path never comes back
 * through the web app at all — the browser goes to Google — so the only
 * observable "this connect belongs to the dashboard" on that leg is the
 * boolean the route hands the backend to sign into the OAuth state.
 */
const GMAIL_STUB = dataModule(
  "export async function getGmailAuthorizeUrl(returnOrigin, chained) {" +
    "  globalThis.__authorizeCall = { returnOrigin, chained };" +
    "  return globalThis.__authorizeResult;" +
    "}",
);

function transpile(absPath, rewrite) {
  const { outputText } = ts.transpileModule(readFileSync(absPath, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: absPath,
  });
  // The lookbehind is load-bearing, and the bug it fixes is live in this
  // repo's other copy of this rewrite. Without it, `searchParams.get("from")`
  // matches: the word `from` sits immediately before a quote, so the pattern
  // reads it as an import specifier and swallows everything up to the NEXT
  // quote — which under this exact route produced
  // `Cannot find package ');\n const fromSignIn = from === '`. A `from` that
  // introduces a module specifier is never itself inside a string.
  return outputText.replace(
    /((?<!["'])\bfrom\s*|\bimport\s*\(\s*)["']([^"']+)["']/g,
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

const ROUTE_FILE = "app/api/gmail/authorize/route.ts";

/** The real `GET`, wired to the stub. */
async function loadAuthorizeRoute() {
  const source = transpile(resolvePath(WEB_ROOT, ROUTE_FILE), (spec) =>
    spec === "@/lib/gmail/server" ? GMAIL_STUB : localOrPackage(spec),
  );
  return import(dataModule(source));
}

/**
 * Drive the route at `href` with `result` as the backend's answer, and hand
 * back the response plus what the stub was called with.
 */
async function runAuthorize(href, result) {
  const { NextRequest } = await import("next/server.js");
  const { GET } = await loadAuthorizeRoute();
  globalThis.__authorizeResult = result;
  delete globalThis.__authorizeCall;
  try {
    const response = await GET(new NextRequest(new URL(href, ORIGIN).toString()));
    return { response, call: globalThis.__authorizeCall };
  } finally {
    delete globalThis.__authorizeResult;
    delete globalThis.__authorizeCall;
  }
}

/** Where the response is sending the browser, parsed. */
const landing = (response) => {
  const location = response.headers.get("location");
  assert.ok(location, "the handler returned no Location header at all");
  return new URL(location);
};

/**
 * Every non-`ok` answer the backend can give this route, in the shapes
 * `GmailAuthorizeResult` declares. `unauthenticated` is deliberately absent:
 * it is the one outcome that is NOT a connect failure — nothing can be
 * connected before a sign-in — and it has its own `/login` branch, pinned by
 * `tests/e2e/connect.spec.ts`.
 */
const FAILURES = [
  { kind: "auth", status: 401 },
  { kind: "unavailable" },
  { kind: "at_capacity" },
  { kind: "rate_limited", retryAfterSeconds: 60 },
  { kind: "backend", message: "Backend responded 502", status: 502 },
];

const CONSENT_URL = "https://accounts.google.com/o/oauth2/v2/auth?client_id=x";

/** Mounted once and reused: the source cannot change mid-run, and `next/link`
 *  schedules a prefetch on every mount that has nothing to do with this file. */
let tileHrefOnce;

/** What the dashboard's "Connect Gmail" tile actually renders as its href. */
async function connectTileHref() {
  if (tileHrefOnce !== undefined) return tileHrefOnce;
  const { ForwardRoutes } = await importApp(
    "components/dashboard/DashboardEmptyState.tsx",
  );
  const view = await mount(React.createElement(ForwardRoutes));
  const tile = view
    .queryAll("a")
    .find((a) => (a.textContent ?? "").includes("Connect Gmail"));
  assert.ok(
    tile,
    "no rendered link says 'Connect Gmail' — the tile this file is about is gone, " +
      "so every assertion below would be vacuous.",
  );
  const href = tile.getAttribute("href");
  assert.ok(href, "the 'Connect Gmail' tile rendered without an href");
  tileHrefOnce = href;
  return href;
}

test("the dashboard tile reaches the authorize route, not the page that holds the button", async () => {
  const href = await connectTileHref();

  assert.notEqual(
    href,
    "/settings",
    "the 'Connect Gmail' tile is back to costing two hops: it lands on the " +
      "settings page, where the reader still has to find and press Connect.",
  );
  assert.equal(
    new URL(href, ORIGIN).pathname,
    "/api/gmail/authorize",
    `the tile must navigate to the authorize route; it renders ${href}`,
  );
});

test("a dashboard-initiated connect that FAILS returns to the dashboard", async () => {
  const href = await connectTileHref();

  for (const result of FAILURES) {
    const { response } = await runAuthorize(href, result);
    assert.equal(
      landing(response).pathname,
      "/dashboard",
      `a '${result.kind}' failure from the dashboard tile landed on ` +
        `${landing(response).pathname} — the reader pressed a control on the ` +
        "dashboard and was answered on a preferences page.",
    );
  }
});

test("CONTROL: the same failures WITHOUT the flag still land on Settings, flag and all", async () => {
  // Directional, and it is the assertion that makes the test above mean
  // something: without it, a route that sent EVERY failure to `/dashboard`
  // would pass — and it would have broken the Settings surface, where the
  // explanation belongs next to the button that was pressed.
  for (const result of FAILURES) {
    const { response } = await runAuthorize("/api/gmail/authorize", result);
    const to = landing(response);
    assert.equal(to.pathname, "/settings", `'${result.kind}' left Settings`);
    assert.ok(
      to.searchParams.get("gmail"),
      `'${result.kind}' reached Settings carrying no reason at all`,
    );
  }
});

test("a dashboard-initiated connect that SUCCEEDS asks the backend to return to the dashboard", async () => {
  const href = await connectTileHref();

  const fromTile = await runAuthorize(href, { kind: "ok", url: CONSENT_URL });
  assert.equal(
    fromTile.response.headers.get("location"),
    CONSENT_URL,
    "a successful authorize must 302 the browser to Google's consent screen",
  );
  assert.equal(
    fromTile.call.chained,
    true,
    "the backend was not told this connect belongs to the dashboard, so its " +
      "callback will sign `/settings` into the OAuth state and the reader will " +
      "come back from Google onto a preferences page.",
  );
  assert.equal(fromTile.call.returnOrigin, ORIGIN);

  // The other half of the same control: the flag has to be what turns it on.
  const bare = await runAuthorize("/api/gmail/authorize", {
    kind: "ok",
    url: CONSENT_URL,
  });
  assert.equal(
    bare.call.chained,
    false,
    "a Settings-initiated connect asked the backend to return to the dashboard",
  );
});

test("TRIPWIRE: `from=signin` and `from=dashboard` are two live values, not one", async () => {
  // The sign-in chain (#510) predates the tile and must not have been
  // displaced by it. Both values return to the dashboard; they are kept
  // distinct because they describe different readers — see the route's own
  // comment. An unknown value must do neither.
  for (const flag of ["signin", "dashboard"]) {
    const { response, call } = await runAuthorize(
      `/api/gmail/authorize?from=${flag}`,
      { kind: "ok", url: CONSENT_URL },
    );
    assert.equal(response.headers.get("location"), CONSENT_URL);
    assert.equal(call.chained, true, `from=${flag} did not return to the dashboard`);
  }

  const { call } = await runAuthorize("/api/gmail/authorize?from=elsewhere", {
    kind: "ok",
    url: CONSENT_URL,
  });
  assert.equal(
    call.chained,
    false,
    "an unrecognised `from` value was treated as a dashboard connect — the " +
      "flag is being read as 'present' rather than as one of two names.",
  );
});

test("WIRING: the tile's flag is one the route actually reads", async () => {
  // Derived from the component, not written down again: this compares the two
  // readers of the vocabulary against each other, so a rename of the value on
  // either side reds here instead of shipping a tile the route ignores.
  const href = await connectTileHref();
  const flag = new URL(href, ORIGIN).searchParams.get("from");
  assert.ok(flag, "the tile carries no `from` flag, so it cannot come back here");

  const source = readFileSync(resolvePath(WEB_ROOT, ROUTE_FILE), "utf8");
  assert.match(
    source,
    new RegExp(`===\\s*"${flag}"`),
    `the tile sends ?from=${flag} and the authorize route names no such value`,
  );
});
